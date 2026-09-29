import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "notes_transcription_worker", SCRIPTS / "notes_transcription_worker.py"
)
WORKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(WORKER)


class NotesTranscriptionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audio = self.root / "call.m4a"
        self.audio.write_bytes(b"audio")
        self.call = {
            "id": "CALL-A1111111-1111-1111-1111-111111111111",
            "path": str(self.audio),
            "started_at": "2026-08-11T10:00:00",
            "title": "Call with Alice",
            "note_pk": 1,
        }
        self.patches = [
            mock.patch.object(WORKER, "STATE_ROOT", self.root / "state"),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_apple_transcript_is_preferred_even_before_audio_materializes(self):
        call = {**self.call, "path": None}
        with (
            mock.patch.object(WORKER.source, "read_calls", return_value=[call]),
            mock.patch.object(WORKER.source, "apple_transcript", return_value="Apple text") as apple,
            mock.patch.object(WORKER.shutil, "which") as which,
        ):
            result = WORKER.reconcile()

        self.assertEqual(result["counts"]["completed"], 1)
        item = WORKER.show_transcript(call["id"])
        self.assertEqual(item["provider"], "apple")
        self.assertEqual(item["text"], "Apple text\n")
        self.assertIsNone(item["source_path"])
        apple.assert_called_once_with(call)
        which.assert_not_called()

    def test_absent_apple_transcript_uses_path_cli_scribe_v2_and_auto_diarization(self):
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            output = Path(command[command.index("--out") + 1])
            output.write_text("Speaker 1: Hello\nSpeaker 2: Hi\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with (
            mock.patch.object(WORKER.source, "read_calls", return_value=[self.call]),
            mock.patch.object(WORKER.source, "apple_transcript", return_value=""),
            mock.patch.object(WORKER.shutil, "which", return_value="/opt/bin/elevenlabs") as which,
            mock.patch.object(WORKER.subprocess, "run", side_effect=fake_run),
        ):
            result = WORKER.reconcile()

        self.assertEqual(result["counts"]["completed"], 1)
        which.assert_called_once_with("elevenlabs")
        command = commands[0]
        self.assertEqual(command[:3], ["/opt/bin/elevenlabs", "transcribe", str(self.audio)])
        self.assertEqual(command[command.index("--model") + 1], "scribe_v2")
        self.assertEqual(command[command.index("--response-format") + 1], "diarized_text")
        self.assertIn("--diarize", command)
        self.assertNotIn("--num-speakers", command)
        item = WORKER.show_transcript(self.call["id"])
        self.assertTrue(item["diarized"])
        self.assertEqual(item["provider"], "elevenlabs")

    def test_success_is_idempotent_and_final_artifact_is_atomic(self):
        with (
            mock.patch.object(WORKER.source, "read_calls", return_value=[self.call]),
            mock.patch.object(WORKER.source, "apple_transcript", return_value="Cached") as apple,
            mock.patch.object(WORKER.os, "replace", wraps=os.replace) as replace,
        ):
            first = WORKER.reconcile()
            second = WORKER.reconcile()

        self.assertEqual(first["counts"]["completed"], 1)
        self.assertEqual(second["counts"]["cached"], 1)
        apple.assert_called_once()
        replace.assert_called_once()
        transcript_dir = WORKER.STATE_ROOT / "transcripts"
        self.assertEqual([path.suffix for path in transcript_dir.iterdir()], [".txt"])

    def test_same_uuid_dedupes_after_source_path_and_mtime_change(self):
        moved = self.root / "renamed-call.m4a"
        moved.write_bytes(b"audio")
        renamed = {**self.call, "path": str(moved)}
        with (
            mock.patch.object(
                WORKER.source,
                "read_calls",
                side_effect=([self.call], [renamed]),
            ),
            mock.patch.object(WORKER.source, "apple_transcript", return_value="Once") as apple,
        ):
            first = WORKER.reconcile()
            second = WORKER.reconcile()

        self.assertEqual(first["counts"]["completed"], 1)
        self.assertEqual(second["counts"]["cached"], 1)
        apple.assert_called_once()

    def test_corrupt_cached_artifact_is_rebuilt(self):
        with mock.patch.object(WORKER.source, "apple_transcript", return_value="Original"):
            first = WORKER.process_call(self.call)
        Path(first["transcript_path"]).write_text("corrupt", encoding="utf-8")

        with mock.patch.object(WORKER.source, "apple_transcript", return_value="Rebuilt") as apple:
            second = WORKER.process_call(self.call)

        self.assertEqual(second["state"], "completed")
        self.assertEqual(WORKER.show_transcript(self.call["id"])["text"], "Rebuilt\n")
        apple.assert_called_once()

    def test_completed_status_exposes_call_provenance_without_reading_notes(self):
        with mock.patch.object(WORKER.source, "apple_transcript", return_value="Text"):
            WORKER.process_call(self.call)

        with (
            mock.patch.object(WORKER.source, "read_calls") as read_source,
            mock.patch.object(WORKER.source, "apple_transcript") as apple,
        ):
            status = WORKER.cache_status(state="completed", limit=10)

        self.assertEqual(status["returned"], 1)
        item = status["items"][0]
        self.assertEqual(item["uuid"], self.call["id"])
        self.assertEqual(item["call_started_at"], self.call["started_at"])
        self.assertEqual(item["title"], self.call["title"])
        self.assertEqual(item["source_path"], str(self.audio))
        self.assertEqual(item["state"], "completed")
        self.assertTrue(item["transcript_sha256"])
        read_source.assert_not_called()
        apple.assert_not_called()

    def test_completed_cursor_cannot_skip_a_later_completion_in_the_same_second(self):
        fixed_now = dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.timezone.utc)
        first = {**self.call, "id": "Z-CALL", "note_pk": 9}
        later = {**self.call, "id": "A-CALL", "note_pk": 10}
        with (
            mock.patch.object(WORKER, "_now", return_value=fixed_now),
            mock.patch.object(WORKER.source, "apple_transcript", return_value="Text"),
        ):
            WORKER.process_call(first)
            cursor = WORKER.cache_status(state="completed", limit=1)["next_cursor"]
            WORKER.process_call(later)
            page = WORKER.cache_status(
                state="completed", limit=1, after_cursor=cursor
            )

        self.assertEqual([later["id"]], [item["uuid"] for item in page["items"]])

    def test_show_rejects_a_tampered_cached_transcript(self):
        with mock.patch.object(WORKER.source, "apple_transcript", return_value="Original"):
            WORKER.process_call(self.call)
        item = WORKER.cache_status(state="completed")["items"][0]
        Path(item["transcript_path"]).write_text("Tampered", encoding="utf-8")

        with self.assertRaisesRegex(
            WORKER.TranscriptionWorkerError, "hash does not match"
        ):
            WORKER.show_transcript(self.call["id"])

    def test_reconcile_receipt_proves_a_worker_run_completed(self):
        with mock.patch.object(WORKER.source, "read_calls", return_value=[]):
            result = WORKER._reconcile_with_receipt(limit=10, retry_failed=False)

        receipt = json.loads(WORKER._receipt_path().read_text())
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(receipt["source"], "notes")
        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["attempted"], 0)

    def test_failure_has_durable_backoff_and_explicit_retry(self):
        now = dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.timezone.utc)
        failure = WORKER.TranscriptionWorkerError("temporary failure")
        with (
            mock.patch.object(WORKER.source, "read_calls", return_value=[self.call]),
            mock.patch.object(WORKER.source, "apple_transcript", return_value=""),
            mock.patch.object(WORKER, "_elevenlabs_transcribe", side_effect=failure) as transcribe,
            mock.patch.object(WORKER, "_now", return_value=now),
        ):
            first = WORKER.reconcile()
            second = WORKER.reconcile()

        self.assertEqual(first["counts"]["failed"], 1)
        self.assertEqual(second["counts"]["deferred"], 1)
        transcribe.assert_called_once()
        failed = WORKER.cache_status()["items"][0]
        self.assertEqual(failed["attempts"], 1)
        self.assertEqual(failed["next_retry_at"], "2026-08-11T12:01:00+00:00")

        with (
            mock.patch.object(WORKER.source, "resolve", return_value=self.call),
            mock.patch.object(WORKER.source, "apple_transcript", return_value="Recovered"),
        ):
            retried = WORKER.retry_one(self.call["id"])
        self.assertEqual(retried["state"], "completed")
        self.assertEqual(WORKER.cache_status()["items"][0]["attempts"], 0)

    def test_unmaterialized_call_retries_without_blocking_the_next_uuid(self):
        waiting = {
            **self.call,
            "id": "CALL-WAITING",
            "path": None,
            "note_pk": 2,
        }
        with (
            mock.patch.object(WORKER.source, "read_calls", return_value=[waiting, self.call]),
            mock.patch.object(
                WORKER.source,
                "apple_transcript",
                side_effect=("", "Available"),
            ),
            mock.patch.object(WORKER.shutil, "which") as which,
        ):
            result = WORKER.reconcile()

        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(result["counts"]["completed"], 1)
        waiting_row = next(
            item for item in WORKER.cache_status()["items"] if item["source_id"] == "CALL-WAITING"
        )
        self.assertEqual(waiting_row["attempts"], 1)
        which.assert_not_called()

    def test_paid_work_uses_an_exclusive_per_uuid_file_lock(self):
        with (
            mock.patch.object(WORKER.source, "apple_transcript", return_value="Locked"),
            mock.patch.object(WORKER.fcntl, "flock") as flock,
        ):
            result = WORKER.process_call(self.call)

        self.assertEqual(result["state"], "completed")
        self.assertEqual(flock.call_args_list[0].args[1], WORKER.fcntl.LOCK_EX)
        self.assertEqual(flock.call_args_list[-1].args[1], WORKER.fcntl.LOCK_UN)

    def test_initial_baseline_replaces_failed_rows_without_touching_completed_rows(self):
        waiting = {**self.call, "id": "CALL-WAITING", "path": None, "note_pk": 2}
        with mock.patch.object(WORKER.source, "apple_transcript", return_value=""):
            WORKER.process_call(waiting)
        with mock.patch.object(WORKER.source, "apple_transcript", return_value="Done"):
            WORKER.process_call(self.call)

        with mock.patch.object(WORKER.source, "read_calls", return_value=[waiting, self.call]):
            result = WORKER.baseline_current()

        self.assertEqual(result["baselined"], 1)
        states = {
            item["source_id"]: item["state"] for item in WORKER.cache_status()["items"]
        }
        self.assertEqual(states["CALL-WAITING"], "baseline")
        self.assertEqual(states[self.call["id"]], "completed")

    def test_top_level_cli_exposes_transcriptions(self):
        help_result = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "notes"), "calls", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("transcriptions", help_result.stdout)

    def test_transcription_cli_is_on_demand_only(self):
        help_result = subprocess.run(
            [
                str(PLUGIN_ROOT / "bin" / "notes"),
                "calls",
                "transcriptions",
                "--help",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("retry", help_result.stdout)
        self.assertIn("reconcile", help_result.stdout)
        self.assertNotIn("launch-agent", help_result.stdout)

        retired = subprocess.run(
            [
                str(PLUGIN_ROOT / "bin" / "notes"),
                "calls",
                "transcriptions",
                "launch-agent",
                "install",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(retired.returncode, 2)
        self.assertIn("invalid choice", retired.stderr)


if __name__ == "__main__":
    unittest.main()
