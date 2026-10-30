import unittest
from copy import deepcopy
from unittest.mock import patch
from catalog import MODELS
from recommender import memory_estimate, recommend
import recommender


def observation(context=128, rss=3.8, allocator=17.273, model=None):
    model = model or MODELS[0]
    return {'measurement_id': f'{model["id"]}-{context}', 'identity': {
        'repo_id': model['repo_id'], 'model_revision': model['revision'],
        'quantization': model['quantization'], 'backend': model['backend'],
        'backend_version': '0.7.1', 'context_k': context},
        'metrics': {'peak_process_rss_gb': rss, 'mlx_peak_memory_gb': allocator}}


class RecommenderTests(unittest.TestCase):
    def test_low_rss_high_allocator_cannot_look_like_small_requirement(self):
        result = memory_estimate(MODELS[0], 128, {'measurements': [observation()]})
        self.assertGreater(result['admission_envelope_gib'], 17.273)
        self.assertEqual(result['provenance'], 'estimated')
        # Overlapping measurements are not summed.
        self.assertAlmostEqual(result['admission_envelope_gib'], round(17.273 * 1.2 + 1, 2))

    def test_upper_context_prevents_optimistic_fallback_at_unmeasured_short_context(self):
        estimate = memory_estimate(MODELS[0], 16, {'measurements': [observation(32, 3.4, 7.5)]})
        self.assertGreater(estimate['admission_envelope_gib'], 7.5)
        self.assertEqual(estimate['basis'], 'observed_upper_context')

    def test_rss_alone_is_not_measured_total_memory(self):
        estimate = memory_estimate(MODELS[0], 128, {'measurements': [observation(128, 3.8, None)]})
        self.assertEqual(estimate['basis'], 'heuristic_rss_lower_bound')
        self.assertGreater(estimate['admission_envelope_gib'], 3.8)

    def test_missing_allocator_cannot_ignore_high_observed_rss(self):
        estimate = memory_estimate(MODELS[0], 32, {'measurements': [observation(32, 100, None)]})
        self.assertGreater(estimate['admission_envelope_gib'], 100)

    def test_incompatible_revision_backend_and_quantization_are_excluded(self):
        for field in ('model_revision', 'backend', 'quantization', 'repo_id'):
            point = observation(128, 1, 100)
            point['identity'][field] = 'different'
            self.assertEqual(memory_estimate(MODELS[0], 128, {'measurements': [point]})['measurement_ids'], [])

    def test_requested_backend_version_never_silently_uses_another(self):
        result = memory_estimate(MODELS[0], 128, {'measurements': [observation()]}, backend_version='other')
        self.assertEqual(result['measurement_ids'], [])

    def test_memory_evidence_cannot_mark_quality_or_latency_measured(self):
        result = recommend(64, 'speed', 128, profiles={'measurements': [observation()]})
        self.assertEqual(result['data_source'], 'estimated')
        self.assertEqual(result['metric_provenance']['capability_quality'], 'unknown')
        self.assertEqual(result['metric_provenance']['latency'], 'unknown')
        self.assertIn('heuristic', result['ranking_provenance'])

    def test_8gb_declines_unsafe_original_9b_32k_or_4b_128k_claim(self):
        data = {'measurements': [observation(32, 3.4, 7.511), observation(32, 6.1, 10.215, MODELS[1])]}
        self.assertIsNone(recommend(8, 'quality', 32, profiles=data))
        self.assertIsNone(recommend(8, 'speed', 128, profiles=data))

    def test_all_recommendations_fit_estimated_budget_and_output_headroom(self):
        for ram in (8, 16, 24, 32, 48, 64):
            for performance in ('quality', 'speed', 'efficiency', 'balanced'):
                result = recommend(ram, performance, 256, profiles={'measurements': [observation()]})
                if result is not None:
                    self.assertLessEqual(result['admission_envelope_gib'] + result['system_reserve_gb'], ram)
                    self.assertLessEqual(result['context_length'] + result['reserved_output_tokens'], result['model']['max_context_tokens'])

    def test_platforms_and_missing_memory(self):
        self.assertEqual(recommend(64, arch='x86_64')['status'], 'deferred')
        self.assertEqual(recommend(64, os_name='Linux')['status'], 'unsupported')
        self.assertIsNone(recommend(None))

    def test_invalid_context(self):
        with self.assertRaises(ValueError):
            recommend(16, context_k=73)

    def test_catalog_and_preferences_remain_separate(self):
        self.assertEqual(len(MODELS), 4)
        self.assertTrue(all(m['bits'] == 4 for m in MODELS))
        quality = recommend(64, 'quality', 256, 'balanced', profiles={})
        speed = recommend(64, 'speed', 256, 'balanced', profiles={})
        self.assertNotEqual(quality['model_id'], speed['model_id'])

    def test_moe_speed_uses_active_parameters_while_memory_uses_total_weights(self):
        moe = MODELS[2]
        self.assertEqual(moe['parameters_b'], 35)
        self.assertEqual(moe['active_parameters_b'], 3)
        self.assertGreater(memory_estimate(moe, 32, {})['admission_envelope_gib'], moe['artifact_gb'])
        result = recommend(64, 'speed', 256, 'balanced', profiles={})
        self.assertEqual(result['model_id'], moe['repo_id'])
        self.assertEqual(result['speed_basis'], 'heuristic_active_parameters')
        dense_copy = deepcopy(MODELS)
        dense_copy[2]['active_parameters_b'] = 35
        with patch.object(recommender, 'MODELS', dense_copy):
            self.assertNotEqual(recommend(64, 'speed', 256, 'balanced', profiles={})['model_id'], moe['repo_id'])

    def test_measured_speed_overrides_active_size_heuristic(self):
        smaller, larger = deepcopy(MODELS[:2])
        smaller['capability_rank'] = larger['capability_rank'] = 1
        profiles = {'measurements': []}
        for model, tps in ((smaller, 5.0), (larger, 40.0)):
            point = observation(32, model=model)
            point['identity']['hardware'] = {'chip': 'Test Chip', 'memory_gb': 64}
            point['metrics']['decode_tps_median'] = tps
            point['metric_provenance'] = {'latency': 'measured'}
            profiles['measurements'].append(point)
        with patch.object(recommender, 'MODELS', [smaller, larger]):
            fallback = recommend(64, 'speed', 32, profiles={}, chip='Test Chip')
            measured = recommend(64, 'speed', 32, profiles=profiles, chip='Test Chip')
        self.assertEqual(fallback['model_id'], smaller['repo_id'])
        self.assertEqual(measured['model_id'], larger['repo_id'])
        self.assertEqual(measured['speed_basis'], 'observed_decode_tps')
        self.assertEqual(measured['metric_provenance']['latency'], 'measured_same_host_context_decode')

    def test_speed_preference_retains_agent_capability_in_target_scenario(self):
        result = recommend(64, 'speed', 256, 'balanced', chip='Apple M1 Max')
        self.assertEqual(result['model_id'], MODELS[2]['repo_id'])
        self.assertEqual(result['context_k'], 192)
        self.assertEqual(result['speed_basis'], 'observed_upper_context_proxy')
        self.assertEqual(result['metric_provenance']['latency'], 'estimated_from_observed_upper_context')
        self.assertNotEqual(result['model_id'], MODELS[0]['repo_id'])
