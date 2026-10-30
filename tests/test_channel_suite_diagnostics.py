"""Optional-module diagnostics; no Core or platform process is started."""
from pathlib import Path
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
