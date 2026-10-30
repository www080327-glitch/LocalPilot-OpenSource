"""Independent adversarial integration controls; no fabricated quality labels."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from recommender import recommend_primary, recommend


class SelectorIntegrationTests(unittest.TestCase):
    def select(self, **kwargs):
        return recommend_primary(64, 'speed', 64, chip='Apple M1 Max', **kwargs)

    def test_shipped_artifact_is_used_by_product_entry_point(self):
        result = self.select()
        self.assertEqual(result['selector_used'], 'mlp')
        self.assertEqual(result['selector_requested'], 'auto')
        self.assertEqual(result['metric_provenance']['capability_quality'], 'unknown')

    def test_source_permission_is_a_hard_gate_before_ranking(self):
        with patch('selector_mlp.rank', side_effect=AssertionError('must not rank')):
            self.assertIsNone(self.select(local_allowed=False))
            self.assertIsNone(self.select(allowed_model_ids=[]))
            self.assertIsNone(self.select(available_memory_gb=0))

    def test_runtime_exception_and_out_of_admission_results_fall_back(self):
        expected = recommend(64, 'speed', 64, chip='Apple M1 Max')
        def tamper(options, *args):
            options[0]['context_k'] = 999999
            options[0]['model_id'] = 'unapproved/model'
            return options[0], 50
        for effect in [RuntimeError('invalid predictor'), tamper]:
            with patch('selector_mlp.rank', side_effect=effect):
                result = self.select()
                self.assertEqual(result['selector_used'], 'rules')
                self.assertEqual(result['model_id'], expected['model_id'])
                self.assertEqual(result['context_k'], expected['context_k'])

    def test_nonfinite_or_negative_prediction_is_never_accepted(self):
        for value in [float('nan'), float('inf'), -1, 0, True]:
            with patch('selector_mlp.rank', side_effect=lambda options,*args:(options[0],value)):
                self.assertEqual(self.select()['selector_used'], 'rules')

    def test_memory_budget_does_not_change_physical_hardware_features(self):
        from selector_mlp import rank
        with patch('selector_mlp.rank', wraps=rank) as call:
            result = self.select(available_memory_gb=30)
            self.assertEqual(call.call_args.args[1], 64)
            self.assertTrue(all(o['admission_envelope_gib']<=30 for o in call.call_args.args[0]))
            self.assertLessEqual(result['admission_envelope_gib'],30)

    def test_quality_and_unknown_hardware_are_explicit_fallbacks(self):
        for request in [dict(preference='quality',chip='Apple M1 Max'),dict(preference='speed',chip='other')]:
            result=recommend_primary(64, **request)
            self.assertEqual(result['selector_used'],'rules')
            self.assertIn('selector_fallback',result)

    def test_allowlist_and_agent_context_survive_mlp_selection(self):
        from catalog import MODELS
        result=self.select(allowed_model_ids=[MODELS[2]['repo_id']], minimum_context_k=64,
                           excluded_size_classes=('4B','9B'))
        self.assertEqual(result['model_id'],MODELS[2]['repo_id'])
        self.assertGreaterEqual(result['context_k'],64)

    def test_training_regularization_and_capacity_have_validated_limits(self):
        from selector_mlp import train
        samples=[([1,2,3,4,5],1.0),([2,3,4,5,6],1.1)]
        for width,l2 in [(True,0),(0,0),(33,0),(4,-1),(4,float('nan'))]:
            with self.assertRaises(ValueError):train(samples,hidden_units=width,l2=l2)
        one=train(samples,epochs=10,hidden_units=4,l2=.01)
        self.assertEqual(len(one['w1']),4)
        self.assertEqual(one,train(samples,epochs=10,hidden_units=4,l2=.01))


if __name__ == '__main__':
    unittest.main()
