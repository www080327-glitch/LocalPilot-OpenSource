"""Deterministic selection and actual HTTP protocol fixtures, never model scores."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.public_model_eval import final_answer, freeze_questions, read_protocol, run_study
from tests.test_local_http_backend import MockServer, completion


class PublicModelEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows = [{'question_id': index, 'category': f'category-{index%14}',
                      'question': f'Public protocol fixture {index}',
                      'options': ['first', 'second'], 'answer': 'A', 'answer_index': 0,
                      'cot_content': 'ANSWER_KEY_REASONING_MUST_NOT_REACH_PROVIDER'} for index in range(56)]
        self.source = {'repository': 'TIGER-Lab/MMLU-Pro', 'revision': 'a'*40, 'sha256': 'b'*64}

    def test_frozen_selection_is_reproducible_and_covers_all_categories(self):
        first = freeze_questions(self.rows, self.source, self.root/'first.json')
        second = freeze_questions(list(reversed(self.rows)), self.source, self.root/'second.json')
        ids = [row['question_id'] for row in first['questions']]
        self.assertEqual(ids, [row['question_id'] for row in second['questions']])
        self.assertEqual(len(ids), 32)
        self.assertEqual(len(set(ids)), 32)
        counts = Counter(row['category'] for row in first['questions'])
        self.assertEqual(len(counts), 14)
        self.assertGreaterEqual(min(counts.values()), 2)
        self.assertEqual(read_protocol(self.root/'first.json'), first)
        first['questions'][0]['answer'] = 'B'
        (self.root/'first.json').write_text(json.dumps(first))
        with self.assertRaisesRegex(ValueError, 'changed'):
            read_protocol(self.root/'first.json')

    def test_malformed_dataset_and_existing_protocol_are_not_silently_changed(self):
        invalid = deepcopy(self.rows)
        invalid.append(invalid[0])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            freeze_questions(invalid, self.source, self.root/'bad.json')
        self.assertFalse((self.root/'bad.json').exists())
        freeze_questions(self.rows, self.source, self.root/'fixed.json')
        original = (self.root/'fixed.json').read_bytes()
        with self.assertRaises(FileExistsError):
            freeze_questions(self.rows, self.source, self.root/'fixed.json')
        self.assertEqual((self.root/'fixed.json').read_bytes(), original)

    def test_only_an_exact_final_answer_line_is_graded(self):
        for value, expected in [('Explanation mentions A and B.\nAnswer: B', 'B'),
                                ('Answer: A\nThis is not a final answer.', None),
                                ('The answer is A', None), ('Answer: A or B', None),
                                ('Answer: B.', None), ('Answer: J', None),
                                ('Question: A) first B) second', None), ('', None)]:
            with self.subTest(value=value):
                self.assertEqual(final_answer(value, 2), expected)

    def test_real_http_keeps_all_32_attempts_errors_usage_and_raw_responses(self):
        model = MockServer()
        self.addCleanup(model.close)
        protocol = self.root/'protocol.json'
        frozen = freeze_questions(self.rows, self.source, protocol)
        model.add(completion('The answer is A'))
        model.add(completion('Answer: A', finish='length'))
        model.add({'error': {'message': 'fixture failure'}}, status=500)
        for _ in range(29):
            response = completion('Answer: A')
            response['id'] = 'fixture-provider-id'
            response['timings'] = {'predicted_ms': 5}
            model.add(response)
        result = run_study(protocol, endpoint=model.base_url, evidence=self.root/'results',
            model_identity={'model_name': 'mock-local', 'model_revision': 'a'*40,
                'model_sha256': 'b'*64, 'server_commit': 'c'*40, 'server_binary_sha256': 'd'*64},
            generation_parameters={'temperature': 0})
        self.assertEqual(result['counts'], {'FAIL': 2, 'ERROR': 1, 'PASS': 29})
        self.assertTrue(result['complete'])
        self.assertEqual(result['planned'], 32)
        self.assertEqual(len(model.requests), 32)
        self.assertEqual(result['accuracy_all_planned'], 29/32)
        self.assertFalse(result['ranking_claim'])
        self.assertEqual(result['usage']['prompt_tokens']['missing_questions'], 1)
        self.assertEqual([row['question_id'] for row in result['rows']],
                         [row['question_id'] for row in frozen['questions']])
        for request in model.requests:
            self.assertNotIn('tools', request)
            self.assertEqual(request['max_tokens'], 512)
            self.assertNotIn('ANSWER_KEY_REASONING_MUST_NOT_REACH_PROVIDER', json.dumps(request))
        last = result['rows'][-1]['question_id']
        raw = json.loads((self.root/'results'/f'question-{last}-response.json').read_text())
        self.assertEqual(raw['provider_response']['id'], 'fixture-provider-id')
        self.assertEqual(raw['provider_response']['timings'], {'predicted_ms': 5})
        self.assertEqual(raw['parsed_response']['message']['content'], 'Answer: A')
