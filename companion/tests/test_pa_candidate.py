"""Candidate receipt and worker boundaries; synthetic bytes are not model weights."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import companion.tests.test_pa_training as fixtures
from companion.config import Config
from companion.model import ModelManager
from companion.model.candidate import inspect_candidate
from companion.model.finetune import prepare


class CandidateArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReviewedTrainingTests()
        self.fixture.setUp()
        self.root = self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def receipt(self):
        exported, model = self.fixture.export_pair(), self.fixture.model()
        plan = prepare(model, exported['directory'], self.root / 'synthetic-run')
        adapter = Path(plan['config']['adapter_path'])
        adapter.mkdir()
        weights = adapter / 'adapters.safetensors'
        weights.write_bytes(b'Synthetic receipt fixture, not usable tensor weights')
        config = adapter / 'adapter_config.json'
        config.write_text(json.dumps(plan['config']))
        plan.update(status='completed', training='COMPLETED',
            trained_weights={'path':str(weights), 'bytes':weights.stat().st_size,
                             'sha256':hashlib.sha256(weights.read_bytes()).hexdigest()},
            adapter_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest())
        (adapter.parent / 'run.json').write_text(json.dumps(plan))
        return model, adapter, plan

    def test_candidate_inspection_returns_explicit_config_without_loading_or_promotion(self):
        model, adapter, _ = self.receipt()
        result = inspect_candidate(model, adapter)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['inference'], 'NOT_RUN')
        self.assertEqual(result['quality'], 'NOT_EVALUATED')
        self.assertFalse(result['model_promoted'])
        self.assertFalse(result['base_weights_verified'])
        self.assertEqual(result['config_fragment'], {'backend':'mlx', 'model_path':str(model), 'model_adapter_path':str(adapter)})
        self.assertFalse((adapter.parent / 'training.log').exists())

    def test_candidate_requires_a_completed_run_and_exact_adapter_configuration(self):
        model, adapter, plan = self.receipt()
        receipt = adapter.parent / 'run.json'
        receipt.write_text(json.dumps(plan | {'training':'NOT_RUN'}))
        with self.assertRaisesRegex(ValueError, 'completed'):
            inspect_candidate(model, adapter)
        receipt.write_text(json.dumps(plan))
        path = adapter / 'adapter_config.json'
        path.write_text(json.dumps(plan['config'] | {'num_layers':9}))
        with self.assertRaisesRegex(ValueError, 'configuration differs'):
            inspect_candidate(model, adapter)

    def test_changed_base_configuration_or_candidate_weights_are_rejected(self):
        model, adapter, _ = self.receipt()
        path = model / 'tokenizer_config.json'
        original = path.read_bytes()
        path.write_bytes(b'{"chat_template":"changed"}')
        with self.assertRaisesRegex(ValueError, 'Base model configuration'):
            inspect_candidate(model, adapter)
        path.write_bytes(original)
        weights = adapter / 'adapters.safetensors'
        content = weights.read_bytes()
        weights.write_bytes(b'X' + content[1:])
        with self.assertRaisesRegex(ValueError, 'weight hash'):
            inspect_candidate(model, adapter)

    def test_unrelated_base_path_or_symlinked_weights_are_not_substituted(self):
        model, adapter, _ = self.receipt()
        with self.assertRaisesRegex(ValueError, 'recorded training paths'):
            inspect_candidate(self.root, adapter)
        weights = adapter / 'adapters.safetensors'
        moved = self.root / 'moved.safetensors'
        weights.rename(moved)
        weights.symlink_to(moved)
        with self.assertRaises(OSError):
            inspect_candidate(model, adapter)

    def test_cli_validation_is_real_and_keeps_inference_not_run(self):
        model, adapter, _ = self.receipt()
        result = subprocess.run([sys.executable, '-m', 'companion.model.candidate', '--model', str(model), '--adapter', str(adapter)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response['inference'], 'NOT_RUN')
        self.assertEqual(response['config_fragment']['model_adapter_path'], str(adapter))

    def test_real_worker_rejects_changed_receipt_before_importing_optional_mlx(self):
        model, adapter, _ = self.receipt()
        (adapter / 'adapters.safetensors').write_bytes(b'Changed bytes')
        config = Config(backend='mlx', model_path=str(model), model_adapter_path=str(adapter),
                        low_power_policy='off', allow_local_on_battery=True)
        manager = ModelManager(config)
        try:
            response = manager.complete([{'role':'user', 'content':'Synthetic question'}], max_tokens=16)
            self.assertEqual(response['status'], 'unavailable')
            self.assertEqual(response['error_stage'], 'candidate_validation')
            self.assertIn('Candidate weights', response['error'])
            self.assertIsNone(manager.child)
        finally:
            manager.unload()

    def test_candidate_cannot_be_silently_ignored_by_an_http_backend(self):
        config_file = self.root / 'invalid-config.json'
        config_file.write_text(json.dumps({'backend':'local-http', 'model_adapter_path':'/selected/candidate'}))
        with self.assertRaisesRegex(ValueError, 'mlx backend'):
            Config.load(str(config_file))
        manager = ModelManager(Config(backend='local-http', model_adapter_path='/selected/candidate', low_power_policy='off'))
        response = manager.complete([{'role':'user', 'content':'Synthetic question'}])
        self.assertEqual(response['error_stage'], 'candidate_configuration')
        self.assertIsNone(manager.child)
        self.assertEqual(manager.inferences, 0)


if __name__ == '__main__':
    unittest.main()
