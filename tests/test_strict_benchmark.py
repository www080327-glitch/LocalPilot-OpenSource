import json
import tempfile
from pathlib import Path
import unittest

from agent.loop import AgentResult
from benchmarks.contracts import Event, Result, Run
from benchmarks.run import check_answer
from benchmarks.tasks import TASKS as LEGACY_TASKS
from benchmarks.strict import run_episode, strict_json, verify, hidden_add_checks
from benchmarks.strict_tasks import TASKS, fixture
from tests.test_agent_loop import FakeBackend, assistant_message


class StrictBenchmarkTests(unittest.TestCase):
    def test_reference_controls_pass_all_tasks_in_all_profile_combinations(self):
        for prompt in ('standard', 'minimal_0', 'minimal_1'):
            for tools in ('full', 'compact'):
                for task in TASKS:
                    with self.subTest(prompt=prompt, tools=tools, task=task.task_id):
                        result, events = run_episode(task, prompt_profile=prompt, tool_profile=tools)
                        self.assertTrue(result.success, result.failure_reason)
                        self.assertTrue(result.safety_pass)
                        self.assertIsNone(result.input_tokens)
                        self.assertIsNone(result.retries)
                        self.assertIsNone(result.ttft_seconds)
                        self.assertIsNone(result.memory_metrics['backend_allocator_peak_bytes'])
                        self.assertEqual(result.tool_calls, sum(e.event_type == 'tool_result' for e in events))

    def test_prompt_contains_answer_but_no_read_must_fail(self):
        task = next(t for t in TASKS if t.task_id == 'prompt_answer_leak')
        answer = {'value': 'local-first', 'path': 'claim.txt', 'line': 1}
        result, _ = run_episode(task, FakeBackend(assistant_message(json.dumps(answer))))
        self.assertFalse(result.success)
        self.assertTrue(result.assertions['exact_answer'])
        self.assertFalse(result.assertions['read_evidence'])
        self.assertEqual(result.tool_calls, 0)

    def test_exact_hidden_answer_without_tools_fails_each_read_task(self):
        for task in TASKS:
            if task.task_id not in {'read_file', 'repository_search', 'missing_file', 'evidence_answer'}:
                continue
            _, _, gold = fixture(task, 0)
            result, _ = run_episode(task, FakeBackend(assistant_message(json.dumps(gold))))
            self.assertFalse(result.success, task.task_id)

    def test_claimed_edit_without_file_change_fails(self):
        for task in TASKS:
            if task.task_id in {'single_file_modification', 'constrained_patch', 'benign_verification'}:
                result, _ = run_episode(task, FakeBackend(assistant_message('All changes and tests passed.')))
                self.assertFalse(result.success)
                self.assertFalse(result.assertions['filesystem'])
                self.assertTrue(result.safety_pass)

    def test_wrong_marker_fails_even_after_genuine_read(self):
        task = next(t for t in TASKS if t.task_id == 'read_file')
        from tests.test_agent_loop import tool_call
        backend = FakeBackend(assistant_message(tool_calls=[tool_call('r', 'read_file', '{"path":"facts.txt"}')]),
            assistant_message('{"value":"wrong","path":"facts.txt","line":2}'))
        result, _ = run_episode(task, backend)
        self.assertTrue(result.assertions['read_evidence'])
        self.assertFalse(result.success)

    def test_searching_unrelated_line_is_not_evidence_of_hidden_fact(self):
        from tests.test_agent_loop import tool_call
        task = next(t for t in TASKS if t.task_id == 'read_file')
        _, _, gold = fixture(task, 0)
        backend = FakeBackend(assistant_message(tool_calls=[tool_call('s', 'search_text', '{"query":"Fixture record"}')]),
            assistant_message(json.dumps(gold)))
        result, _ = run_episode(task, backend)
        self.assertFalse(result.success)
        self.assertFalse(result.assertions['read_evidence'])

    def test_fixture_seed_changes_hidden_answer(self):
        task = TASKS[0]
        self.assertNotEqual(fixture(task, 0)[2], fixture(task, 1)[2])
        result, _ = run_episode(task, seed=173)
        self.assertTrue(result.success)

    def test_json_parser_rejects_ambiguous_answers(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{} {}', '```json\n{}\n```'):
            with self.assertRaises(ValueError):
                strict_json(text)

    def test_hidden_verifier_does_not_execute_extra_code(self):
        self.assertFalse(hidden_add_checks('import os\ndef add(a,b): return a+b'))
        self.assertFalse(hidden_add_checks('def add(a,b): return a-b'))
        self.assertTrue(hidden_add_checks('def add(a,b): return a+b'))

    def test_tampered_extra_file_and_outside_changes_fail_safety(self):
        task = next(t for t in TASKS if t.task_id == 'prompt_answer_leak')
        files, expected, answer = fixture(task, 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, content in files.items():
                target = root / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content)
            (root / 'unexpected.txt').write_text('tamper')
            result = AgentResult(json.dumps(answer), [], [])
            events = [Event('r', 1, 'tool_result', 0.1, {'name': 'read_file', 'arguments': {'path': 'claim.txt'}, 'ok': True, 'result': files['claim.txt']})]
            assertions, safety = verify(task, result, events, root, expected, answer, True)
            self.assertTrue(assertions['exact_answer'])
            self.assertFalse(safety)
            (root / 'unexpected.txt').unlink()
            self.assertFalse(verify(task, result, events, root, expected, answer, False)[1])

    def test_legacy_remains_explicitly_smoke_and_retains_old_oracle(self):
        self.assertTrue(check_answer(LEGACY_TASKS[0], 'LocalPilot local-first', 0)[0])

    def test_minimal_result_schema_keeps_unknown_not_zero(self):
        record = Result(Run('id', 'task', '1'), 'agent').to_dict()
        for field in ('success', 'model_calls', 'tool_calls', 'retries', 'input_tokens', 'cached_tokens', 'latency_seconds'):
            self.assertIsNone(record[field])
        self.assertEqual(record['schema_version'], 'v0.1')
