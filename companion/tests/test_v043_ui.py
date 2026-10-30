"""The native UI must use Host authority and preserve exact process ownership."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from companion.config import PrivateData
from companion.ui.build import _owned_process, build_ui, source_digest, stop_ui


class UIProcessBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.private = PrivateData(Path(self.temporary.name).resolve() / "private")
        self.expected = str(self.private.root / "CompanionUI.app/Contents/MacOS/CompanionUI")
        self.record = {"pid": 123, "created": 456.0, "token": "owned-token", "executable": self.expected}
        self.process = Mock()
        self.process.create_time.return_value = 456.0
        self.process.exe.return_value = self.expected
        self.process.cmdline.return_value = [self.expected, str(self.private.file("runtime.json"))]

    def tearDown(self):
        self.temporary.cleanup()

    def test_reused_pid_is_never_signalled(self):
        self.process.create_time.return_value = 460.0
        self.private.write("ui.json", json.dumps(self.record))
        with patch("psutil.Process", return_value=self.process):
            self.assertEqual(stop_ui(self.private, "owned-token")["status"], "ui_not_signalled")
        self.process.terminate.assert_not_called()
        self.assertTrue(self.private.file("ui.json").exists())

    def test_other_session_token_is_never_signalled(self):
        self.private.write("ui.json", json.dumps(self.record))
        with patch("psutil.Process", return_value=self.process):
            self.assertEqual(stop_ui(self.private, "other-token")["status"], "ui_not_signalled")
        self.process.terminate.assert_not_called()

    def test_validation_process_is_not_a_resident_ui(self):
        self.process.cmdline.return_value.insert(1, "--self-test")
        with patch("psutil.Process", return_value=self.process), self.assertRaises(RuntimeError):
            _owned_process(self.record, self.private, "owned-token")

    def test_exact_owned_ui_is_terminated_without_host_shutdown(self):
        self.private.write("ui.json", json.dumps(self.record))
        with patch("psutil.Process", return_value=self.process):
            self.assertEqual(stop_ui(self.private, "owned-token")["status"], "ui_stopped")
        self.process.terminate.assert_called_once_with()
        self.process.wait.assert_called_once_with(timeout=3)
        self.assertFalse(self.private.file("ui.json").exists())

    def test_explicit_show_mode_remains_owned_and_other_arguments_fail(self):
        self.process.cmdline.return_value.append("--show")
        with patch("psutil.Process", return_value=self.process):
            self.assertIs(_owned_process(self.record, self.private, "owned-token"), self.process)
        self.process.cmdline.return_value[-1] = "--arbitrary-mode"
        with patch("psutil.Process", return_value=self.process), self.assertRaises(RuntimeError):
            _owned_process(self.record, self.private, "owned-token")


class UIBuildTests(unittest.TestCase):
    def test_source_content_digest_controls_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            files = [root / name for name in ("CompanionClient.swift", "MenuBarController.swift", "main.swift")]
            for source in files:
                source.write_text("public source")

            def compiler(command, **kwargs):
                Path(command[-1]).write_bytes(b"synthetic compiler output")

            with patch("companion.ui.build.sources", return_value=files), patch("companion.ui.build.sys.platform", "darwin"), patch("companion.ui.build.subprocess.run", side_effect=compiler) as run:
                binary = build_ui(root / "CompanionUI.app")
                build_ui(root / "CompanionUI.app")
                self.assertEqual(run.call_count, 2)
                before = source_digest()
                mtime = files[0].stat().st_mtime
                files[0].write_text("changed content, deliberately preserved mtime")
                os.utime(files[0], (mtime, mtime))
                self.assertNotEqual(before, source_digest())
                build_ui(root / "CompanionUI.app")
                self.assertEqual(run.call_count, 4)
                self.assertEqual(binary.stat().st_mode & 0o777, 0o700)

    def test_failure_preserves_existing_binary_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "CompanionUI.app"
            with patch("companion.ui.build.sys.platform", "darwin"), patch("companion.ui.build.subprocess.run", side_effect=RuntimeError("compiler failure")):
                with self.assertRaises(RuntimeError):
                    build_ui(root)
            self.assertFalse((root / "Contents/MacOS/CompanionUI.building").exists())


if __name__ == "__main__":
    unittest.main()
