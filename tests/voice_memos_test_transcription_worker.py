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
    "voice_memos_transcription_worker", SCRIPTS / "voice_memos_transcription_worker.py"
)
WORKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(WORKER)


class VoiceMemosTranscriptionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audio = self.root / "memo.m4a"
        self.audio.write_bytes(b"audio")
        self.recording = {
            "uuid": "A1111111-1111-1111-1111-111111111111",
            "filename": "20260811-A1111111.m4a",
            "path": str(self.audio),
            "recorded_at": "2026-08-11T10:00:00",
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

    def test_apple_transcript_is_preferred_and_keyed_by_stable_uuid(self):
        apple_result = {"text": "On-device text", "locale": "en_US", "segments": []}
        with (
            mock.patch.object(WORKER.source, "read_recordings", return_value=[self.recording]),
            mock.patch.object(WORKER.source, "apple_transcript", return_value=apple_result) as apple,
            mock.patch.object(WORKER.shutil, "which") as which,
        ):
            result = WORKER.reconcile()

        self.assertEqual(result["counts"]["completed"], 1)
        item = WORKER.show_transcript(self.recording["uuid"])
        self.assertEqual(item["source_id"], self.recording["uuid"])
        self.assertEqual(item["provider"], "apple")
        self.assertEqual(item["text"], "On-device text\n")
        apple.assert_called_once_with(self.audio)
        which.assert_not_called()

    def test_absent_apple_transcript_uses_scribe_v2_without_forced_diarization(self):
        commands = []

        def fake_run(command, **_kwargs):
            commands.append(command)
            output = Path(command[command.index("--out") + 1])
            output.write_text("Remember the dentist.\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with (
            mock.patch.object(WORKER.source, "read_recordings", return_value=[self.recording]),
            mock.patch.object(WORKER.source, "apple_transcript", return_value=None),
            mock.patch.object(WORKER.shutil, "which", return_value="/usr/local/bin/elevenlabs") as which,
            mock.patch.object(WORKER.subprocess, "run", side_effect=fake_run),
        ):
            result = WORKER.reconcile()

        self.assertEqual(result["counts"]["completed"], 1)
        which.assert_called_once_with("elevenlabs")
        command = commands[0]
        self.assertEqual(command[command.index("--model") + 1], "scribe_v2")
        self.assertEqual(command[command.index("--response-format") + 1], "text")
        self.assertNotIn("--diarize", command)
        self.assertNotIn("--num-speakers", command)
        self.assertEqual(WORKER.show_transcript(self.recording["uuid"])["provider"], "elevenlabs")

    def test_completed_recording_is_idempotent_and_written_atomically(self):
        apple_result = {"text": "Cached memo"}
        with (
            mock.patch.object(WORKER.source, "read_recordings", return_value=[self.recording]),
            mock.patch.object(WORKER.source, "apple_transcript", return_value=apple_result) as apple,
            mock.patch.object(WORKER.os, "replace", wraps=os.replace) as replace,
        ):
            first = WORKER.reconcile()
            second = WORKER.reconcile()

        self.assertEqual(first["counts"]["completed"], 1)
        self.assertEqual(second["counts"]["cached"], 1)
        apple.assert_called_once()
        replace.assert_called_once()

    def test_same_uuid_dedupes_after_source_path_and_mtime_change(self):
        moved = self.root / "renamed-memo.m4a"
        moved.write_bytes(b"audio")
        renamed = {**self.recording, "path": str(moved), "filename": moved.name}
        with (
            mock.patch.object(
                WORKER.source,
                "read_recordings",
                side_effect=([self.recording], [renamed]),
            ),
            mock.patch.object(
                WORKER.source,
                "apple_transcript",
                return_value={"text": "Once"},
            ) as apple,
        ):
            first = WORKER.reconcile()
            second = WORKER.reconcile()

        self.assertEqual(first["counts"]["completed"], 1)
        self.assertEqual(second["counts"]["cached"], 1)
        apple.assert_called_once()

    def test_completed_status_is_bounded_cursor_paged_and_never_transcribes(self):
        second_audio = self.root / "memo-2.m4a"
        second_audio.write_bytes(b"more audio")
        second = {
            **self.recording,
            "uuid": "B2222222-2222-2222-2222-222222222222",
            "filename": second_audio.name,
            "path": str(second_audio),
            "recorded_at": "2026-08-11T11:00:00",
            "title": "Dentist reminder",
        }
        with mock.patch.object(
            WORKER.source,
            "apple_transcript",
            side_effect=({"text": "First"}, {"text": "Second"}),
        ):
            WORKER.process_recording(self.recording)
            WORKER.process_recording(second)

        with (
            mock.patch.object(WORKER.source, "read_recordings") as read_source,
            mock.patch.object(WORKER.source, "apple_transcript") as apple,
            mock.patch.object(WORKER, "_elevenlabs_transcribe") as elevenlabs,
        ):
            page_one = WORKER.cache_status(state="completed", limit=1)
            page_two = WORKER.cache_status(
                state="completed",
                limit=1,
                after_cursor=page_one["next_cursor"],
            )

        self.assertEqual(page_one["returned"], 1)
        self.assertTrue(page_one["has_more"])
        self.assertEqual(page_two["returned"], 1)
        self.assertFalse(page_two["has_more"])
        self.assertNotEqual(
            page_one["items"][0]["uuid"], page_two["items"][0]["uuid"]
        )
        item = page_two["items"][0]
        for field in (
            "uuid",
            "recorded_at",
            "title",
            "source_path",
            "transcript_path",
            "transcript_sha256",
            "state",
            "completed_at",
        ):
            self.assertIn(field, item)
        self.assertEqual(item["title"], "Dentist reminder")
        read_source.assert_not_called()
        apple.assert_not_called()
        elevenlabs.assert_not_called()

    def test_completed_cursor_cannot_skip_a_later_completion_in_the_same_second(self):
        fixed_now = dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.timezone.utc)
        first_audio = self.root / "z-first.m4a"
        first_audio.write_bytes(b"first")
        first = {
            **self.recording,
            "uuid": "Z9999999-9999-9999-9999-999999999999",
            "path": str(first_audio),
        }
        later = {**self.recording, "uuid": "A0000000-0000-0000-0000-000000000000"}
        with (
            mock.patch.object(WORKER, "_now", return_value=fixed_now),
            mock.patch.object(WORKER.source, "apple_transcript", return_value={"text": "Text"}),
        ):
            WORKER.process_recording(first)
            cursor = WORKER.cache_status(state="completed", limit=1)["next_cursor"]
            WORKER.process_recording(later)
            page = WORKER.cache_status(
                state="completed", limit=1, after_cursor=cursor
            )

        self.assertEqual([later["uuid"]], [item["uuid"] for item in page["items"]])

    def test_paid_work_uses_an_exclusive_per_uuid_file_lock(self):
        with (
            mock.patch.object(WORKER.source, "apple_transcript", return_value={"text": "Locked"}),
            mock.patch.object(WORKER.fcntl, "flock") as flock,
        ):
            result = WORKER.process_recording(self.recording)

        self.assertEqual(result["state"], "completed")
        self.assertEqual(flock.call_args_list[0].args[1], WORKER.fcntl.LOCK_EX)
        self.assertEqual(flock.call_args_list[-1].args[1], WORKER.fcntl.LOCK_UN)

    def test_show_rejects_a_tampered_cached_transcript(self):
        with mock.patch.object(
            WORKER.source, "apple_transcript", return_value={"text": "Original"}
        ):
            WORKER.process_recording(self.recording)
        item = WORKER.cache_status(state="completed")["items"][0]
        Path(item["transcript_path"]).write_text("Tampered", encoding="utf-8")

        with self.assertRaisesRegex(
            WORKER.TranscriptionWorkerError, "hash does not match"
        ):
            WORKER.show_transcript(self.recording["uuid"])

    def test_reconcile_receipt_proves_a_worker_run_completed(self):
        with mock.patch.object(WORKER.source, "read_recordings", return_value=[]):
            result = WORKER._reconcile_with_receipt(limit=10, retry_failed=False)

        receipt = json.loads(WORKER._receipt_path().read_text())
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(receipt["source"], "voice-memos")
        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["attempted"], 0)

    def test_initial_baseline_replaces_failed_rows_without_touching_completed_rows(self):
        waiting_audio = self.root / "waiting.m4a"
        waiting = {
            **self.recording,
            "uuid": "WAITING-UUID",
            "path": str(waiting_audio),
        }
        with mock.patch.object(WORKER.source, "apple_transcript", return_value=None):
            WORKER.process_recording(waiting)
        with mock.patch.object(
            WORKER.source, "apple_transcript", return_value={"text": "Done"}
        ):
            WORKER.process_recording(self.recording)

        with mock.patch.object(
            WORKER.source, "read_recordings", return_value=[waiting, self.recording]
        ):
            result = WORKER.baseline_current()

        self.assertEqual(result["baselined"], 1)
        states = {
            item["source_id"]: item["state"] for item in WORKER.cache_status()["items"]
        }
        self.assertEqual(states["WAITING-UUID"], "baseline")
        self.assertEqual(states[self.recording["uuid"]], "completed")

    def test_top_level_cli_exposes_transcriptions(self):
        help_result = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "voice-memos"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("transcriptions", help_result.stdout)

    def test_transcription_cli_is_on_demand_only(self):
        help_result = subprocess.run(
            [
                str(PLUGIN_ROOT / "bin" / "voice-memos"),
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
                str(PLUGIN_ROOT / "bin" / "voice-memos"),
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
