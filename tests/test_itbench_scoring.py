"""Synthetic scoring and real local TLS transport; no benchmark labels or paid API."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from agent.backends import BackendResponse, Message
from agent.local_http import LocalBackendError
from scripts import grade_itbench_aa as grading
from tests.test_openai_cloud_backend import OpenAICloudFixture
from tests.test_openai_responses import response_payload


def synthetic_truth():
    return {'groups': [
        {'id': 'cause-a', 'kind': 'Deployment', 'namespace': 'test',
         'filter': ['REFERENCE-ONLY-SYNTHETIC-MARKER'], 'root_cause': True},
        {'id': 'pod-a', 'kind': 'Pod', 'namespace': 'test', 'filter': ['workload-a-.*'],
         'root_cause': False},
        {'id': 'cause-b', 'kind': 'ConfigMap', 'namespace': 'test', 'name': 'config-b',
         'root_cause': True},
        {'id': 'symptom', 'kind': 'Service', 'namespace': 'test', 'name': 'dependent',
         'root_cause': False},
        {'id': 'symptom-alias', 'kind': 'Service', 'namespace': 'test', 'name': 'other-dependent',
         'root_cause': False}],
        'aliases': [['cause-a', 'pod-a'], ['symptom', 'symptom-alias']],
        'fault': 'Reference-only causal description excluded from the judge input'}


def factors(*names):
    return [{'name': name, 'reasoning': 'Synthetic candidate reasoning',
             'evidence': 'Synthetic candidate evidence'} for name in names]


def normalization(prediction, ids):
    return {'contributing_factor_entities': [
        {'submitted_entity_name': factor['name'], 'normalized_gt_entity_id': entity_id,
         'reasoning': 'Synthetic identity match'} for factor, entity_id in zip(prediction, ids)]}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def completed_run(directory, predictions=None):
    predictions = predictions or {}
    study = {'revision': grading.DATASET_REVISION, 'source_split': 'public',
             'scenarios': list(grading.PUBLIC_SCENARIOS), 'repeats': 1,
             'ground_truth_file_sha256': grading.LABEL_SHA256,
             'candidate': 'SYNTHETIC-CANDIDATE-IDENTITY-NOT-FOR-JUDGE'}
    write_json(directory / 'study.json', study)
    receipts = []
    for index, scenario in enumerate(grading.PUBLIC_SCENARIOS, 1):
        receipt = {'index': index, 'scenario': scenario, 'dataset_revision': grading.DATASET_REVISION,
                   'attempt': 1, 'owned_core_stopped': True, 'task_status': 'failed', 'output_valid': False}
        if index in predictions:
            receipt.update(task_status='completed', output_valid=True)
            write_json(directory / f'case-{index:03d}' / 'agent_output.json', predictions[index])
        write_json(directory / f'case-{index:03d}' / 'case-result.json', receipt)
        receipts.append(receipt)
    write_json(directory / 'RUN_SUMMARY.json', {'planned': 40, 'cases': receipts})
    return receipts


class ScriptedJudge:
    """Only the model response is scripted; scoring, validation and files are real."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, messages, **options):
        self.calls.append((messages, options))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return BackendResponse(Message('assistant', json.dumps(reply)),
                               usage={'total_tokens': 37}, model='synthetic-judge', finish_reason='stop')


class ITBenchScoringTests(unittest.TestCase):
    def setUp(self):
        self.truth = grading.ground_truth(synthetic_truth())

    def test_full_recall_precision_uses_unique_groups_and_unmatched_predictions(self):
        cases = [
            (['cause-a', 'cause-b'], 1.0, 2, 0, 0, 0),
            (['cause-a'], 0.0, 1, 0, 0, 1),
            (['cause-a', 'symptom'], 0.0, 1, 1, 0, 1),
            (['cause-a', 'cause-b', 'symptom'], 2 / 3, 2, 1, 0, 0),
            (['cause-a', 'cause-b', None], 2 / 3, 2, 0, 1, 0),
            (['cause-a', 'pod-a', 'cause-a', 'cause-b'], 1.0, 2, 0, 0, 0),
            (['cause-a', 'cause-b', 'symptom', 'symptom-alias', 'symptom'], 2 / 3, 2, 1, 0, 0),
            (['cause-a', 'cause-b', None, None], 0.5, 2, 0, 2, 0),
            ([], 0.0, 0, 0, 0, 2),
        ]
        for ids, score, tp, fp, unmatched, missing in cases:
            with self.subTest(ids=ids):
                actual = grading.score_entities(self.truth, ids)
                self.assertAlmostEqual(actual.score, score)
                self.assertEqual((actual.true_positive_groups, actual.false_positive_groups,
                                  actual.unmatched_predictions, actual.missed_root_groups),
                                 (tp, fp, unmatched, missing))

    def test_transitive_aliases_and_any_root_member_define_one_target(self):
        value = synthetic_truth()
        value['aliases'] = [['pod-a', 'symptom'], ['symptom', 'cause-a'], ['cause-a', 'cause-b']]
        truth = grading.ground_truth({'spec': value})
        score = grading.score_entities(truth, ['pod-a', 'cause-a', 'cause-b'])
        self.assertEqual(score.root_groups, 1)
        self.assertEqual(score.true_positive_groups, 1)
        self.assertEqual(score.score, 1)
        self.assertNotIn('fault', truth.judge_input)
        self.assertTrue(all('root_cause' not in entity for entity in truth.judge_input['groups']))

    def test_ground_truth_rejects_unknown_alias_ids_and_invalid_root_flags(self):
        bad = []
        value = synthetic_truth()
        value['aliases'].append(['cause-a', 'unknown'])
        bad.append(value)
        value = synthetic_truth()
        value['groups'][0]['root_cause'] = 'true'
        bad.append(value)
        value = synthetic_truth()
        value['groups'].append(deepcopy(value['groups'][0]))
        bad.append(value)
        value = synthetic_truth()
        for entity in value['groups']:
            entity['root_cause'] = False
        bad.append(value)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                grading.ground_truth(value)

    def test_judge_format_order_names_length_and_ids_are_checked(self):
        prediction = factors('test/Deployment/a', 'test/ConfigMap/b')
        valid = normalization(prediction, ['cause-a', None])
        self.assertEqual(grading.parse_normalization(json.dumps(valid), prediction, self.truth),
                         ['cause-a', None])
        invalid = ['```json\n' + json.dumps(valid) + '\n```', '[]', '{}', 'not json']
        wrong_order = deepcopy(valid)
        wrong_order['contributing_factor_entities'].reverse()
        invalid.append(json.dumps(wrong_order))
        short = deepcopy(valid)
        short['contributing_factor_entities'].pop()
        invalid.append(json.dumps(short))
        for entity_id in ('made-up', 7, True, ['cause-a']):
            value = deepcopy(valid)
            value['contributing_factor_entities'][0]['normalized_gt_entity_id'] = entity_id
            invalid.append(json.dumps(value))
        extra = deepcopy(valid)
        extra['contributing_factor_entities'][0]['extra'] = True
        invalid.append(json.dumps(extra))
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                grading.parse_normalization(text, prediction, self.truth)

    def test_candidate_schema_matches_runner_and_accepts_extra_fields(self):
        receipt = {'task_status': 'completed', 'output_valid': True}
        value = {'contributing_factors': factors('test/Pod/a'), 'extra': 'runner permits this'}
        value['contributing_factors'][0]['extra'] = 42
        parsed, error = grading.candidate_factors(receipt, json.dumps(value).encode())
        self.assertIsNone(error)
        self.assertEqual(parsed, factors('test/Pod/a'))
        for raw in (b'bad-json', b'[]', b'{"contributing_factors":[{"name":1}]}', None):
            with self.subTest(raw=raw):
                self.assertIsNotNone(grading.candidate_factors(receipt, raw)[1])
        failed = {**receipt, 'task_status': 'failed'}
        self.assertEqual(grading.candidate_factors(failed, json.dumps(value).encode())[1], 'candidate_failed')

    def test_scoring_is_over_all_40_and_judge_errors_remain_visible(self):
        results = [{'scenario': scenario, 'status': 'candidate_zero', 'score': 0.0}
                   for scenario in grading.PUBLIC_SCENARIOS]
        results[0].update(status='graded', score=1.0)
        results[1].update(status='graded', score=0.5)
        results[2].update(status='judge_error')
        summary = grading.summarize(results)
        self.assertEqual(summary['denominator'], 40)
        self.assertEqual(summary['mean_score'], 1.5 / 40)
        self.assertEqual(summary['judge_error_cases'], 1)
        self.assertFalse(summary['grading_complete'])
        for changed in (results[:3], results[::-1], [results[0]] * 40):
            with self.assertRaises(ValueError):
                grading.summarize(changed)

    def test_reference_parser_accepts_both_yaml_shapes_without_saving_answers(self):
        rows = []
        for index, scenario in enumerate(grading.PUBLIC_SCENARIOS):
            value = synthetic_truth()
            rows.append({'id_aa': str(index), 'scenario_id': scenario, 'category': 'sre',
                         'source_split': 'public', 'scenario_root': 'unused',
                         'ground_truth_yaml': yaml.safe_dump({'spec': value} if index % 2 else value)})
        body = b'\n'.join(json.dumps(row).encode() for row in rows)
        labels = grading.parse_labels(body)
        self.assertEqual(len(labels), 40)
        self.assertEqual(grading.score_entities(labels['Scenario-1'], ['cause-a', 'cause-b']).score, 1)
        rows[0]['ground_truth_yaml'] = 'REFERENCE-ONLY-SYNTHETIC-MARKER: [invalid'
        with self.assertRaises(ValueError) as rejected:
            grading.parse_labels(b'\n'.join(json.dumps(row).encode() for row in rows))
        self.assertNotIn('REFERENCE-ONLY-SYNTHETIC-MARKER', str(rejected.exception))


class ITBenchRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / 'candidate'
        self.prediction = factors('test/Deployment/a', 'test/ConfigMap/b')
        self.labels = {scenario: grading.ground_truth(synthetic_truth())
                       for scenario in grading.PUBLIC_SCENARIOS}

    def run_grade(self, judge, *, loader=None, processes=()):
        with redirect_stdout(io.StringIO()):
            return grading.grade_run(self.output, Path('/never-read-a-real-key'),
                label_loader=loader or (lambda: self.labels), backend_factory=lambda key: judge,
                processes=processes)

    def test_scoped_process_check_does_not_reject_other_core_jobs(self):
        process = lambda pid, path: {'pid': pid, 'cmdline': [sys.executable, '-m',
                    'localpilot_service', '--config', str(path)]}
        rows = [process(1, self.output / 'case-001/core-private/service.json'),
                process(2, self.output.parent / 'soak/core-private/service.json'),
                process(3, self.output.with_name('candidate-copy') / 'core-private/service.json'),
                {'pid': 4, 'cmdline': ['some-other-tool', '--config', str(self.output / 'config.json')]}]
        self.assertEqual(grading.candidate_core_pids(self.output, processes=rows), [1])
        rows[0]['cmdline'][-2:] = ['--config=' + str(self.output / 'core-private/service.json')]
        self.assertEqual(grading.candidate_core_pids(self.output, processes=rows), [1])

    def test_active_core_or_missing_stop_receipt_blocks_label_fetch(self):
        receipts = completed_run(self.output)
        calls = []
        loader = lambda: calls.append(True) or self.labels
        active = [{'pid': 42, 'cmdline': [sys.executable, '-m', 'localpilot_service',
                   '--config', str(self.output / 'case-001/core-private/service.json')]}]
        with self.assertRaisesRegex(ValueError, 'still running'):
            self.run_grade(None, loader=loader, processes=active)
        receipts[0]['owned_core_stopped'] = False
        write_json(self.output / 'case-001/case-result.json', receipts[0])
        write_json(self.output / 'RUN_SUMMARY.json', {'planned': 40, 'cases': receipts})
        with self.assertRaisesRegex(ValueError, 'stop receipt'):
            self.run_grade(None, loader=loader)
        self.assertEqual(calls, [])
        self.assertFalse((self.output / 'grading').exists())

    def test_fixed_subset_and_unfinished_runner_rejected_before_labels(self):
        completed_run(self.output)
        study_path = self.output / 'study.json'
        study = json.loads(study_path.read_text())
        study['scenarios'].pop()
        write_json(study_path, study)
        with self.assertRaisesRegex(ValueError, '40-case'):
            grading.completed_run(self.output, processes=[])
        completed_run(self.output)
        (self.output / 'RUN_SUMMARY.json').unlink()
        with self.assertRaises(FileNotFoundError):
            grading.completed_run(self.output, processes=[])

    def test_grade_run_preserves_inputs_outputs_usage_and_fixed_denominator(self):
        completed_run(self.output, {1: {'contributing_factors': self.prediction},
                                    2: {'contributing_factors': []}})
        before = {path: path.read_bytes() for path in self.output.rglob('*') if path.is_file()}
        judge = ScriptedJudge([normalization(self.prediction, ['cause-a', 'cause-b'])])
        summary = self.run_grade(judge)
        self.assertEqual(summary['mean_score'], 1 / 40)
        self.assertEqual(summary['graded_cases'], 1)
        self.assertEqual(summary['candidate_zero_cases'], 39)
        self.assertTrue(summary['grading_complete'])
        self.assertEqual(len(judge.calls), 1)
        messages, options = judge.calls[0]
        payload = json.loads(messages[1].content)
        self.assertEqual(set(payload), {'ground_truth', 'prediction'})
        self.assertTrue(all('root_cause' not in entity for entity in payload['ground_truth']['groups']))
        self.assertNotIn('SYNTHETIC-CANDIDATE-IDENTITY-NOT-FOR-JUDGE', messages[1].content)
        self.assertEqual(options, {'thinking': 'medium', 'max_tokens': grading.JUDGE_MAX_TOKENS})
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        for path in (self.output / 'grading').rglob('*'):
            if path.is_file():
                self.assertNotIn('REFERENCE-ONLY-SYNTHETIC-MARKER', path.read_text())
                self.assertNotIn('Reference-only causal description', path.read_text())
        first = json.loads((self.output / 'grading/case-001.json').read_text())
        self.assertEqual(first['response']['usage'], {'total_tokens': 37})
        self.assertEqual(json.loads(first['response']['message']['content']),
                         normalization(self.prediction, ['cause-a', 'cause-b']))
        resumed = self.run_grade(judge)
        self.assertEqual(resumed, summary)
        self.assertEqual(len(judge.calls), 1)

    def test_resume_cannot_silently_change_the_frozen_candidate_study(self):
        completed_run(self.output)
        self.run_grade(None)
        path = self.output / 'study.json'
        study = json.loads(path.read_text())
        study['max_steps'] = 200
        write_json(path, study)
        with self.assertRaisesRegex(ValueError, 'different code or protocol'):
            self.run_grade(None)

    def test_judge_errors_are_zero_without_retry_and_cannot_be_selectively_replaced(self):
        completed_run(self.output, {1: {'contributing_factors': self.prediction},
                                    2: {'contributing_factors': self.prediction}})
        judge = ScriptedJudge([normalization(self.prediction, ['cause-a', 'unknown']),
                               LocalBackendError('Synthetic HTTP failure', status_code=429, retryable=True)])
        summary = self.run_grade(judge)
        self.assertEqual(summary['mean_score'], 0)
        self.assertEqual(summary['judge_error_cases'], 2)
        self.assertFalse(summary['grading_complete'])
        self.assertEqual(summary['cases'][1]['error']['status_code'], 429)
        self.assertIsNotNone(summary['cases'][0]['response'])
        self.run_grade(judge)
        self.assertEqual(len(judge.calls), 2)
        write_json(self.output / 'case-001/agent_output.json', {'contributing_factors': []})
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.run_grade(judge)

    def test_interrupted_judge_receipt_is_not_a_license_to_repeat_inference(self):
        completed_run(self.output, {1: {'contributing_factors': self.prediction}})
        judge = ScriptedJudge([normalization(self.prediction, ['cause-a', 'cause-b'])])
        self.run_grade(judge)
        (self.output / 'grading/case-001.json').unlink()
        summary = self.run_grade(judge)
        self.assertEqual(len(judge.calls), 1)
        self.assertEqual(summary['cases'][0]['status'], 'judge_error')
        self.assertEqual(summary['cases'][0]['error']['type'], 'InterruptedJudge')

    def test_digest_mismatch_stops_before_parsing_any_reference(self):
        class Download:
            def __enter__(self):
                return io.BytesIO(b'synthetic-not-the-pinned-dataset')

            def __exit__(self, *args):
                pass

        with patch.object(grading, 'urlopen', return_value=Download()) as download:
            with self.assertRaisesRegex(ValueError, 'digest'):
                grading.load_labels()
        self.assertEqual(download.call_args.args, (grading.LABEL_URL,))

    def test_judge_factory_fixes_model_reasoning_capability_and_private_key_path(self):
        path = Path(self.temporary.name) / 'synthetic-key'
        path.write_text('fixture-only-not-real\n')
        path.chmod(0o600)
        backend = grading.make_judge(path)
        self.assertIsInstance(backend, grading.ServiceOpenAIResponsesBackend)
        self.assertEqual(backend.model, 'gpt-5.5')
        self.assertEqual(backend.timeout, 180)
        self.assertFalse(backend.capabilities.supports_tool_calling)
        self.assertIn('medium', backend.capabilities.supported_thinking_efforts)


class ITBenchJudgeTransportTests(OpenAICloudFixture):
    def test_actual_responses_adapter_keeps_provider_output_and_sends_only_normalization_inputs(self):
        truth = grading.ground_truth(synthetic_truth())
        prediction = factors('test/Deployment/a', 'test/ConfigMap/b')
        inputs = {'ground_truth': truth.judge_input, 'prediction': {'contributing_factors': prediction}}
        backend = grading.RecordingJudgeBackend(model=grading.JUDGE_MODEL, base_url=self.model.base_url,
                                                api_key='synthetic-key', supports_tool_calling=False)
        payload = response_payload(text=json.dumps(normalization(prediction, ['cause-a', 'cause-b'])))
        payload['model'] = 'gpt-5.5-synthetic-fixture'
        self.model.add(payload)
        result = grading.normalize_and_score(truth, prediction, inputs, backend)
        self.assertEqual(result['status'], 'graded')
        self.assertEqual(result['score'], 1)
        self.assertEqual(result['provider_response'], payload)
        self.assertEqual(result['response']['usage']['total_tokens'], 25)
        request = self.model.requests[0]
        self.assertEqual(self.model.headers[0][0], '/v1/responses')
        self.assertEqual(request['model'], 'gpt-5.5')
        self.assertEqual(request['reasoning'], {'effort': 'medium'})
        self.assertFalse(request['store'])
        self.assertNotIn('tools', request)
        self.assertEqual(len(request['input']), 2)
        self.assertEqual(json.loads(request['input'][1]['content']), inputs)
        self.assertNotIn('root_cause', request['input'][1]['content'])

    def test_incomplete_and_provider_error_outputs_preserve_raw_response_and_score_zero(self):
        truth = grading.ground_truth(synthetic_truth())
        prediction = factors('test/Deployment/a', 'test/ConfigMap/b')
        inputs = {'ground_truth': truth.judge_input, 'prediction': {'contributing_factors': prediction}}
        backend = grading.RecordingJudgeBackend(model=grading.JUDGE_MODEL, base_url=self.model.base_url,
                                                api_key='synthetic-key', supports_tool_calling=False)
        incomplete = response_payload(text=json.dumps(normalization(prediction, ['cause-a', 'cause-b'])),
                                      status='incomplete')
        error = {'status': 'failed', 'error': {'code': 'synthetic_error'}, 'output': [],
                 'usage': {'input_tokens': 3, 'output_tokens': 0}}
        for payload in (incomplete, error):
            self.model.add(payload)
            result = grading.normalize_and_score(truth, prediction, inputs, backend)
            self.assertEqual(result['status'], 'judge_error')
            self.assertEqual(result['score'], 0)
            self.assertEqual(result['provider_response'], payload)
        self.assertEqual(len(self.model.requests), 2)


if __name__ == '__main__':
    unittest.main()
