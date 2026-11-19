"""Run the real qualification parser and offline acceptance negative control."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import qualify_openai_engineering as engineering


class EngineeringQualificationTests(unittest.TestCase):
    def test_model_and_reasoning_are_explicit_with_legacy_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'unused'
            base = ['--output', str(output), '--preflight-only']
            original = engineering.arguments(base)
            self.assertEqual((original.model, original.reasoning), ('gpt-6-luna', 'medium'))
            upgraded = engineering.arguments(base + ['--model', 'gpt-6.1-sol', '--reasoning', 'medium'])
            self.assertEqual((upgraded.model, upgraded.reasoning), ('gpt-6.1-sol', 'medium'))

    def test_preflight_reports_selected_effort_and_keeps_the_original_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'preflight'
            result = subprocess.run([sys.executable, str(Path(engineering.__file__).resolve()),
                '--output', str(output), '--preflight-only', '--model', 'gpt-6-luna', '--reasoning', 'high'],
                cwd=Path(engineering.__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / 'RESULTS.json').read_text())
            protocol = json.loads((output / 'PROTOCOL.json').read_text())
            self.assertEqual((report['model'], report['reasoning']), ('gpt-6-luna', 'high'))
            self.assertEqual(report['preflight']['cloud_calls'], 0)
            self.assertFalse(report['preflight']['core_started'])
            self.assertTrue(report['preflight']['stub_rejected'])
            self.assertEqual(protocol['expected_unittest_count'], 17)
            self.assertEqual(protocol['expected_child_unittest_counts'], {'ParserTests': 9, 'AggregateTests': 3})
            self.assertEqual(protocol['original_fixture_sha256'], engineering.hashes(engineering.fixture_files()))
            self.assertEqual(report['engineering_status'], 'NOT_RUN')
            retry = subprocess.run([sys.executable, str(Path(engineering.__file__).resolve()),
                '--output', str(output), '--preflight-only'], capture_output=True, text=True, timeout=10)
            self.assertEqual(retry.returncode, 2)
            self.assertIn('prior attempts are preserved', retry.stderr)


if __name__ == '__main__':
    unittest.main()
