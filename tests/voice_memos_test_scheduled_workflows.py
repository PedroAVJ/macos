import datetime as dt
import importlib.util
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "voice_memos_scheduled_workflows", SCRIPTS / "scheduled_workflows.py"
)
WORKFLOWS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(WORKFLOWS)


def recording(uuid: str, recorded_at: str) -> dict:
    return {
        "uuid": uuid,
        "recorded_at": recorded_at,
        "path": f"/private/recordings/{uuid}.m4a",
        "title": uuid,
    }


def transcript(value: dict) -> dict:
    return {
        "uuid": value["uuid"],
        "source_id": value["uuid"],
        "recorded_at": value["recorded_at"],
        "completed_at": "2030-01-01T00:00:00Z",
        "transcript_path": f"/private/cache/{value['uuid']}.txt",
        "transcript_sha256": f"hash-{value['uuid']}",
        "state": "completed",
        "text": "untrusted transcript text",
    }


class VoiceMemosScheduledWorkflowTests(unittest.TestCase):
    def run_scan(self, values, **kwargs):
        by_id = {value["uuid"]: value for value in values}
        with (
            mock.patch.object(WORKFLOWS.transcripts.source, "read_recordings", return_value=values),
            mock.patch.object(
                WORKFLOWS.transcripts,
                "process_recording",
                side_effect=lambda value, **_: {
                    "source_id": value["uuid"], "state": "cached", "attempted": False
                },
            ) as process,
            mock.patch.object(
                WORKFLOWS.transcripts,
                "show_transcript",
                side_effect=lambda source_id: transcript(by_id[source_id]),
            ),
        ):
            result = WORKFLOWS.scan("questions", **kwargs)
        return result, process

    def test_omitted_start_defaults_to_previous_24_hours_of_recording_time(self):
        values = [
            recording("inside", "2026-08-11T12:00:00Z"),
            recording("too-old", "2026-08-11T11:59:59Z"),
            recording("at-end", "2026-08-12T12:00:00Z"),
        ]
        result, process = self.run_scan(values, until="2026-08-12T12:00:00Z")
        self.assertEqual(["inside"], [item["uuid"] for item in result["items"]])
        self.assertEqual(["inside"], [call.args[0]["uuid"] for call in process.call_args_list])
        self.assertEqual("recorded_at", result["window"]["field"])
        self.assertTrue(result["window"]["defaulted_to_previous_24_hours"])

    def test_transcript_completion_time_never_controls_selection(self):
        value = recording("recorded-in-window", "2026-08-12T11:00:00Z")
        result, _ = self.run_scan(
            [value], since="2h", until="2026-08-12T12:00:00Z"
        )
        self.assertEqual(1, result["count"])
        self.assertNotIn("text", result["items"][0])
        self.assertEqual("2030-01-01T00:00:00Z", result["items"][0]["completed_at"])

    def test_missing_transcript_is_created_for_a_recording_in_the_window(self):
        value = recording("needs-transcript", "2026-08-12T11:00:00Z")
        with (
            mock.patch.object(WORKFLOWS.transcripts.source, "read_recordings", return_value=[value]),
            mock.patch.object(
                WORKFLOWS.transcripts,
                "process_recording",
                return_value={"source_id": value["uuid"], "state": "completed", "attempted": True},
            ) as process,
            mock.patch.object(WORKFLOWS.transcripts, "show_transcript", return_value=transcript(value)),
        ):
            result = WORKFLOWS.scan(
                "questions", since="2h", until="2026-08-12T12:00:00Z"
            )
        self.assertEqual(1, result["attempted_transcriptions"])
        self.assertTrue(process.call_args.kwargs["include_baseline"])
        self.assertTrue(process.call_args.kwargs["retry_failed"])

    def test_same_window_is_repeatable_without_semantic_cursor_state(self):
        value = recording("repeatable", "2026-08-12T11:00:00Z")
        arguments = {"since": "24h", "until": "2026-08-12T12:00:00Z"}
        first, _ = self.run_scan([value], **arguments)
        second, _ = self.run_scan([value], **arguments)
        self.assertEqual(first, second)
        self.assertTrue(first["stateless"])

    def test_offset_pages_are_stateless_and_keep_the_same_explicit_window(self):
        values = [
            recording("a", "2026-08-12T10:00:00Z"),
            recording("b", "2026-08-12T11:00:00Z"),
        ]
        first, _ = self.run_scan(
            values, since="24h", until="2026-08-12T12:00:00Z", limit=1
        )
        second, _ = self.run_scan(
            values,
            since=first["window"]["since"],
            until=first["window"]["until"],
            limit=1,
            offset=first["next_offset"],
        )
        self.assertEqual(["a"], [item["uuid"] for item in first["items"]])
        self.assertEqual(["b"], [item["uuid"] for item in second["items"]])
        self.assertTrue(first["has_more"])
        self.assertFalse(second["has_more"])

    def test_failed_transcription_is_reported_without_widening_the_window(self):
        value = recording("failed", "2026-08-12T11:00:00Z")
        with (
            mock.patch.object(WORKFLOWS.transcripts.source, "read_recordings", return_value=[value]),
            mock.patch.object(
                WORKFLOWS.transcripts,
                "process_recording",
                return_value={
                    "source_id": value["uuid"],
                    "state": "failed",
                    "attempted": True,
                    "last_error": "transcription unavailable",
                },
            ),
        ):
            result = WORKFLOWS.scan(
                "questions", since="2h", until="2026-08-12T12:00:00Z"
            )
        self.assertEqual([], result["items"])
        self.assertEqual("failed", result["unavailable"][0]["uuid"])

    def test_naive_source_times_are_interpreted_as_local_recording_time(self):
        parsed = WORKFLOWS._recorded_time(recording("local", "2026-08-12T11:00:00"))
        self.assertEqual(dt.timezone.utc, parsed.tzinfo)


if __name__ == "__main__":
    unittest.main()
