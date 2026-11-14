"""Real temporary bundle swaps; codesign/LaunchServices need native Mac acceptance."""
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'desktop/scripts/install-local-app.py'
spec = importlib.util.spec_from_file_location('pa_mac_installer', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class IsolatedInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.source = self.bundle(self.root / 'candidate/LocalPilot Test.app', 'new')
        self.daily = self.bundle(self.home / 'Applications/LocalPilot.app', 'daily', 'io.localpilot.desktop')
        self.daily_hash = installer.digest(self.daily)
        self.commands = []

    def bundle(self, path, version, identity='io.localpilot.desktop.test'):
        (path / 'Contents/MacOS').mkdir(parents=True)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': identity, 'CFBundleShortVersionString': version}))
        (path / 'Contents/MacOS/localpilot').write_text(version)
        return path

    def native(self, command, **kwargs):
        self.commands.append(command)
        if command[0] == 'ditto':
            shutil.copytree(command[-2], command[-1])
        return subprocess.CompletedProcess(command, 0)

    def plan(self, old=True):
        if old:
            self.bundle(self.home / 'Applications/LocalPilot Test.app', 'old')
        with patch.object(installer.subprocess, 'run', side_effect=self.native):
            return installer.make_plan(self.source, test_app=True, home=self.home)

    def stage(self, plan):
        shutil.copytree(self.source, plan['stage'])

    def assert_daily_unchanged(self):
        self.assertEqual(installer.digest(self.daily), self.daily_hash)

    def test_test_identity_has_a_separate_target_and_archive(self):
        plan = self.plan()
        self.assertEqual(Path(plan['destination']), self.home / 'Applications/LocalPilot Test.app')
        self.assertIn('localpilot-test-app-archives', plan['archive_directory'])
        self.assertFalse(Path(plan['stage']).exists())
        self.assertFalse(Path(plan['backup']).exists())
        self.assert_daily_unchanged()

    def test_identity_opt_in_is_required_in_both_directions(self):
        with patch.object(installer.subprocess, 'run', side_effect=self.native):
            with self.assertRaisesRegex(ValueError, 'identity'):
                installer.make_plan(self.source, home=self.home)
            with self.assertRaisesRegex(ValueError, 'identity'):
                installer.make_plan(self.daily, test_app=True, home=self.home)
        self.assertEqual(self.commands, [])

    def test_reviewed_plan_detects_a_changed_source_or_old_bundle(self):
        plan = self.plan()
        with patch.object(installer.subprocess, 'run', side_effect=self.native):
            same = installer.make_plan(self.source, test_app=True, home=self.home)
            installer.check_reviewed_plan(same, plan)
            (self.source / 'Contents/MacOS/localpilot').write_text('modified')
            changed = installer.make_plan(self.source, test_app=True, home=self.home)
        with self.assertRaisesRegex(ValueError, 'source_sha256'):
            installer.check_reviewed_plan(changed, plan)
        changed = dict(same, old_sha256='changed-installed-app')
        with self.assertRaisesRegex(ValueError, 'old_sha256'):
            installer.check_reviewed_plan(changed, plan)

    def test_first_install_copies_and_verifies_the_real_bundle(self):
        plan = self.plan(old=False)
        with patch.object(installer.subprocess, 'run', side_effect=self.native), \
             patch.object(installer.subprocess, 'check_output', return_value=''):
            installer.install(plan)
        self.assertTrue(plan['executed'])
        self.assertEqual(installer.digest(Path(plan['destination'])), installer.digest(self.source))
        self.assertFalse(Path(plan['backup']).exists())
        self.assert_daily_unchanged()

    def test_successful_activation_keeps_the_old_bundle_in_trash(self):
        plan = self.plan()
        self.stage(plan)
        with patch.object(installer.subprocess, 'run', side_effect=self.native):
            installer.activate(plan)
        self.assertEqual(installer.info(Path(plan['destination']))['CFBundleShortVersionString'], 'new')
        self.assertEqual(installer.digest(Path(plan['old_app_trash'])), plan['old_sha256'])
        self.assertFalse(Path(plan['backup']).exists())
        self.assert_daily_unchanged()

    def test_signature_failure_after_rename_restores_previous_bundle(self):
        plan = self.plan()
        self.stage(plan)

        def fail_new_signature(command, **kwargs):
            if command[0] == 'codesign':
                raise subprocess.CalledProcessError(1, command)
            return self.native(command, **kwargs)

        with patch.object(installer.subprocess, 'run', side_effect=fail_new_signature):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.activate(plan)
        self.assertEqual(installer.digest(Path(plan['destination'])), plan['old_sha256'])
        self.assertEqual(installer.digest(Path(plan['failed_app_trash'])), plan['source_sha256'])
        self.assertEqual(plan['rollback'], 'restored_previous_app')
        self.assertFalse(Path(plan['backup']).exists())
        self.assert_daily_unchanged()

    def test_registration_failure_also_rolls_back(self):
        plan = self.plan()
        self.stage(plan)

        def fail_registration(command, **kwargs):
            if command[:2] == [installer.LS, '-f'] and kwargs.get('check'):
                raise subprocess.CalledProcessError(1, command)
            return self.native(command, **kwargs)

        with patch.object(installer.subprocess, 'run', side_effect=fail_registration):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.activate(plan)
        self.assertEqual(installer.digest(Path(plan['destination'])), plan['old_sha256'])
        self.assert_daily_unchanged()

    def test_failed_first_install_restores_absent_entry(self):
        plan = self.plan(old=False)
        self.stage(plan)
        with patch.object(installer.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'codesign')):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.activate(plan)
        self.assertFalse(Path(plan['destination']).exists())
        self.assertTrue(Path(plan['failed_app_trash']).is_dir())
        self.assertEqual(plan['rollback'], 'restored_absent_entry')
        self.assert_daily_unchanged()

    def test_invalid_rollback_archive_blocks_before_the_swap(self):
        plan = self.plan()
        with patch.object(installer, 'archive', return_value={'signature': {'code': 1}}), \
             patch.object(installer.subprocess, 'check_output', return_value=''):
            with self.assertRaisesRegex(ValueError, 'rollback APP'):
                installer.install(plan)
        self.assertEqual(installer.digest(Path(plan['destination'])), plan['old_sha256'])
        self.assertFalse(Path(plan['stage']).exists())
        self.assert_daily_unchanged()

    def test_receipt_is_preserved_and_cannot_be_overwritten(self):
        path = self.root / 'result.json'
        installer.save_receipt(path, {'status': 'failed', 'rollback': 'restored_previous_app'})
        with self.assertRaises(FileExistsError):
            installer.save_receipt(path, {'status': 'installed'})
        self.assertEqual(json.loads(path.read_text())['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
