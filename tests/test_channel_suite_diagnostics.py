"""Optional-module diagnostics, including real local child cleanup; no platform accounts."""
import errno
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
try:
    from localpilot_suite import channels
except ImportError:
    channels = None


@unittest.skipIf(channels is None, 'Installed candidate Suite wheel required')
class OptionalChannelDiagnosticsTests(unittest.TestCase):
    def test_missing_node_has_an_actionable_status(self):
        with patch.object(channels.shutil, 'which', return_value=None):
            result = channels.node()
        self.assertEqual(result['code'], 'NODE_NOT_INSTALLED')

    def test_old_node_is_rejected_without_touching_any_service(self):
        class Run:
            returncode = 0
            stdout = '{"version":"20.1.0","ok":false}'
        with patch.object(channels.shutil, 'which', return_value='/synthetic/node'), patch.object(channels.subprocess, 'run', return_value=Run()):
            result = channels.node()
        self.assertEqual(result['code'], 'NODE_TOO_OLD_OR_FEATURES_MISSING')

    def test_missing_bridge_modules_are_not_mistaken_for_an_installed_node_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'CHANNEL_BRIDGE_MODULE_MISSING'):
                channels.assets(Path(directory), 'qq')

    def test_normal_uninstalled_suite_listing_never_probes_node(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(channels, 'node', side_effect=AssertionError('Node must not be probed')):
            result = channels.main(['list'], Path(directory)/'unused-home')
        self.assertEqual(result['status'], 'not_installed')
        self.assertFalse(result['node_required_by_gui'])


@unittest.skipIf(channels is None or os.name != 'posix', 'Installed Suite and POSIX child lifecycle required')
class ChannelLaunchDiagnosticsTests(unittest.TestCase):
    def test_record_failure_keeps_only_type_errno_and_reaps_real_child(self):
        import psutil
        cases = [(PermissionError(errno.EACCES, 'PRIVATE_EXCEPTION_BODY'), 'PermissionError', str(errno.EACCES)),
                 (ValueError('PRIVATE_EXCEPTION_BODY'), 'ValueError', 'none')]
        for error, name, number in cases:
            with self.subTest(error=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                command = [sys.executable, '-I', '-c', 'import time; time.sleep(60)', 'PRIVATE_ARGV']
                env = dict(os.environ, LP_DIAGNOSTIC_PRIVATE='PRIVATE_ENV')
                with patch.object(channels, 'save', side_effect=error) as record:
                    with self.assertRaisesRegex(ValueError, '^CHANNEL_PROCESS_RECORD_FAILED$'):
                        channels.launch(root, 'qq', command, env)
                record.assert_called_once()
                self.assertFalse(psutil.pid_exists(record.call_args.args[1]['pid']))
                log = root/'qq.error.log'
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
                self.assertEqual(log.read_text().strip(),
                                 f'CHANNEL_PROCESS_RECORD_FAILED stage=identity_record exception={name} errno={number}')
                self.assertIsNone(channels.recent_error(root, 'qq'))

    def test_failed_diagnostic_write_preserves_public_error_and_child_cleanup(self):
        import psutil
        real_open = os.open
        append_attempts = []

        def fail_append(path, flags, *args, **kwargs):
            if flags & os.O_APPEND:
                append_attempts.append(path)
                raise OSError(errno.ENOSPC, 'PRIVATE_LOG_WRITE_FAILURE')
            return real_open(path, flags, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, '-I', '-c', 'import time; time.sleep(60)']
            with patch.object(channels, 'save', side_effect=ValueError('PRIVATE_EXCEPTION_BODY')) as record, \
                    patch.object(channels.os, 'open', side_effect=fail_append):
                with self.assertRaisesRegex(ValueError, '^CHANNEL_PROCESS_RECORD_FAILED$'):
                    channels.launch(root, 'qq', command, dict(os.environ))
            record.assert_called_once()
            self.assertEqual(append_attempts, [root/'qq.error.log'])
            self.assertFalse(psutil.pid_exists(record.call_args.args[1]['pid']))

    def test_installed_cli_failure_report_includes_only_fixed_diagnostic_lines(self):
        from tests.test_channel_suite_integration import InstalledSuiteChannelTests
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'channels').mkdir(mode=0o700)
            fixed = 'CHANNEL_PROCESS_RECORD_FAILED stage=identity_record exception=OSError errno=5'
            (home/'channels/adapter.error.log').write_text(
                'PRIVATE_CHILD_STDERR\n'+fixed+'\n'+fixed+' PRIVATE_SUFFIX\n'
                'CHANNEL_PROCESS_RECORD_FAILED stage=identity_record exception=ValueError errno=PRIVATE_ERRNO\n')
            case = InstalledSuiteChannelTests('test_sigint_releases_adapter_sqlite_and_allows_explicit_restart')
            case.home, case.env = home, dict(os.environ)
            with self.assertRaises(AssertionError) as failed:
                case.cli('invalid-action')
            message = str(failed.exception)
            self.assertEqual(message.count(fixed), 1)
            self.assertNotIn('PRIVATE_', message)
