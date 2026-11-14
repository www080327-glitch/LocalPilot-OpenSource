"""Intel discovery and the existing local HTTP route; no physical Intel qualification."""
import contextlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hardware
from recommender import recommend

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'suite'))
from localpilot_suite import product_control


INTEL = '''Hardware Overview:
    Model Name: MacBook Pro
    Processor Name: Quad-Core Intel Core i7
    Memory: 16 GB
'''


class MacHardwareTests(unittest.TestCase):
    def test_import_does_not_run_macos_programs(self):
        with patch.object(subprocess, 'run', side_effect=AssertionError('import must not probe')):
            importlib.reload(hardware)

    def test_intel_identity_is_preserved_without_guessing_mps(self):
        with patch.object(hardware.platform, 'system', return_value='Darwin'), \
             patch.object(hardware.platform, 'machine', return_value='x86_64'), \
             patch.object(hardware, 'get_system_output', return_value=INTEL):
            result = hardware.get_hardware()
        self.assertEqual(result['arch'], 'x86_64')
        self.assertEqual(result['chip'], 'Quad-Core Intel Core i7')
        self.assertEqual(result['memory'], 16)
        self.assertEqual(result['mps_availability'], 'NOT_PROBED')
        self.assertIn('local OpenAI-compatible', result['platform_reason'])

    def test_apple_silicon_recommendation_scope_is_preserved(self):
        with patch.object(hardware.platform, 'system', return_value='Darwin'), \
             patch.object(hardware.platform, 'machine', return_value='arm64'), \
             patch.object(hardware, 'get_system_output', return_value=INTEL.replace('Processor Name: Quad-Core Intel Core i7', 'Chip: Apple M1 Max')):
            result = hardware.get_hardware()
        self.assertEqual(result['platform_status'], 'supported')
        self.assertEqual(result['chip'], 'Apple M1 Max')
        self.assertIsNone(result['platform_reason'])

    def test_intel_recommendation_declares_configured_endpoint_fallback(self):
        result = recommend(64, arch='x86_64')
        self.assertEqual(result['status'], 'deferred')
        self.assertEqual(result['local_backend_alternative'], 'local-openai')
        self.assertNotIn('model', result)
        self.assertEqual(result['mps_availability'], 'NOT_PROBED')

    def test_product_hardware_does_not_treat_deferred_result_as_a_model(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(hardware.platform, 'system', return_value='Darwin'), \
             patch.object(hardware.platform, 'machine', return_value='x86_64'), \
             patch.object(hardware, 'get_system_output', return_value=INTEL), \
             patch.object(product_control.subprocess, 'run', side_effect=OSError('macOS probe unavailable')), \
             patch.object(product_control, 'backend_settings', return_value=('http://127.0.0.1:1234', {})), \
             patch('localpilot_suite.desktop_setup.discover_omlx', side_effect=OSError('no provider')):
            result = product_control.hardware(Path(tmp))
            self.assertIsNone(result['recommendation'])
            self.assertEqual(result['recommendation_status']['local_backend_alternative'], 'local-openai')
            self.assertEqual(result['installation'], 'first_launch')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_system_profiler_failure_returns_unknown_instead_of_breaking_importers(self):
        with patch.object(hardware.platform, 'system', return_value='Darwin'), \
             patch.object(hardware.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(hardware.get_system_output(), '')
        self.assertEqual(hardware.get_chip(''), 'Unknown')
        self.assertIsNone(hardware.get_memory('Memory: UNKNOWN'))

    def test_existing_core_cli_can_configure_an_intel_local_http_provider(self):
        from localpilot_service.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / 'workspace'
            workspace.mkdir()
            home = root / 'service'
            with patch.object(hardware.platform, 'machine', return_value='x86_64'), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(['--home', str(home), '--json', 'init', '--workspace', str(workspace),
                             '--model', 'configured-cpu-model', '--base-url', 'http://127.0.0.1:19999/v1'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())['model_health'], 'NOT_PROBED')
            config = json.loads((home / 'service.json').read_text())
            for route in config['routes'].values():
                self.assertEqual(route['backend']['kind'], 'local-openai')
                self.assertEqual(route['backend']['model'], 'configured-cpu-model')
                self.assertEqual(route['cloud_egress'], 'LOCAL_ONLY')
                self.assertNotIn('managed_local_model', route)


if __name__ == '__main__':
    unittest.main()
