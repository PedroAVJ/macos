import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_ROOT / "scripts" / "notes.py"
SPEC = importlib.util.spec_from_file_location("notes_cli", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class NotesCallMechanismTests(unittest.TestCase):
    def test_core_data_epoch_maps_to_the_correct_absolute_time(self):
        self.assertEqual(MODULE._stamp(0).timestamp(), MODULE.CORE_DATA_EPOCH)

    def test_resolve_accepts_unique_uuid_prefix(self):
        calls = [
            {"id": "A1B2C3D4-1111", "contact": "Alice", "date": "2026-08-01"},
            {"id": "FFEEDDCC-2222", "contact": "Bob", "date": "2026-08-02"},
        ]
        with mock.patch.object(MODULE, "read_calls", return_value=calls):
            self.assertEqual(MODULE.resolve("a1b2")["contact"], "Alice")

    def test_resolve_rejects_ambiguous_contact(self):
        calls = [
            {"id": "A1B2C3D4-1111", "contact": "Alice", "date": "2026-08-01"},
            {"id": "FFEEDDCC-2222", "contact": "Alice", "date": "2026-08-02"},
        ]
        with mock.patch.object(MODULE, "read_calls", return_value=calls):
            with self.assertRaisesRegex(MODULE.CallRecordingsError, "matches 2 calls"):
                MODULE.resolve("Alice")

    def test_cli_exposes_sources_and_transcription_without_event_commands(self):
        result = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "notes"), "calls", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Usage: notes <area> <command>", result.stdout)
        for command in ("list", "path", "transcript", "doctor", "transcriptions"):
            self.assertIn(command, result.stdout)
        self.assertNotIn("events", result.stdout)

        rejected = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "notes"), "calls", "events"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(rejected.returncode, 2)

    def test_python_cli_uses_notes_calls_program_name(self):
        result = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "notes"), "calls", "list", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("usage: notes calls list", result.stdout)

    def test_root_cli_exposes_non_python_note_writes(self):
        result = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "notes"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("notes create --help", result.stdout)
        self.assertIn("notes checklist create --help", result.stdout)
        self.assertIn("without Python", result.stdout)

        checklist = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "notes"), "checklist", "create", "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("native interactive checklist items", checklist.stdout)


if __name__ == "__main__":
    unittest.main()
