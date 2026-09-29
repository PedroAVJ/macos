import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "voice_memos_source", PLUGIN_ROOT / "scripts" / "voice_memos.py"
)
SOURCE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SOURCE)


class VoiceMemosSourceTests(unittest.TestCase):
    def test_sync_nudge_launches_voice_memos_hidden_and_waits_briefly(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.object(SOURCE.subprocess, "run", return_value=completed) as run,
            mock.patch.object(SOURCE.time, "sleep") as sleep,
        ):
            SOURCE.ensure_current_store()

        run.assert_called_once_with(
            ["/usr/bin/open", "-gj", "/System/Applications/VoiceMemos.app"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        sleep.assert_called_once_with(SOURCE.SYNC_NUDGE_DELAY_SECONDS)

    def test_sync_nudge_reports_background_launch_failure(self):
        failed = subprocess.CompletedProcess([], 1, "", "launch failed")
        with (
            mock.patch.object(SOURCE.subprocess, "run", return_value=failed),
            mock.patch.object(SOURCE.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(
                SOURCE.VoiceMemosError, "background.*launch failed"
            ):
                SOURCE.ensure_current_store()

        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
