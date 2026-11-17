"""Truncated worker output through the real Session, Gateway and child ledger."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

from agent.async_runtime import AsyncPolicy
from agent.backends import ToolCall
from agent.engine_v5 import EngineV5Policy
from agent.persistence import PersistenceError, restore_runtime, snapshot_runtime
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import StabilizationControls
from localpilot_api.service import TaskRequest, TaskService
from localpilot_service.desktop_sessions import apply_options
from tests.test_runtime_api import Backend, answer, call


class WorkerOutputRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'fact.txt').write_text('required value: 42')
        self.runtimes = []
        self.budgets = SessionBudgets(max_steps=8, max_tool_calls=12, max_token_units=1000000,
            max_output_tokens=4096)

    def tearDown(self):
        for runtime in reversed(self.runtimes):
            runtime.close()
        self.temp.cleanup()

    @staticmethod
    def truncated():
        response = answer('INCOMPLETE-TEXT',
            ToolCall('partial-patch', 'apply_patch', '{"changes":['),
            call('apply_patch', {'changes': [{'operation': 'create', 'path': 'discarded.txt',
                'content': 'must not execute'}]}, 'complete-but-discarded'))
        response.finish_reason = 'length'
        response.usage['completion_tokens'] = 4096
        response.message.native_replay = {'kind': 'discarded-provider-state'}
        return response

    @staticmethod
    def write():
        return answer(None, call('apply_patch', {'changes': [{'operation': 'create',
            'path': 'delivered.py', 'content': 'ANSWER = 42\n'}]}, 'small-patch'))

    def child(self, *steps, budgets=None, controls=None, **options):
        runtime = AgentSession(create_default_registry(self.workspace,
            permission_mode=options.pop('permission_mode', 'full-permission')),
            backend=Backend(*steps), policy='cloud-only', streaming=False, depth=1,
            engine_policy=EngineV5Policy(), runtime_tools=False,
            budgets=budgets or self.budgets,
            stabilization=controls or StabilizationControls(stagnation_limit=0),
            retry_policy=RetryPolicy(max_attempts=1), **options)
        self.runtimes.append(runtime)
        return runtime

    def test_async_child_keeps_earlier_receipts_and_runs_actual_check_after_truncation(self):
        (self.workspace / 'test_delivery.py').write_text(
            'import unittest\nfrom delivered import ANSWER\n'
            'class DeliveryTests(unittest.TestCase):\n'
            '    def test_answer(self): self.assertEqual(ANSWER, 42)\n')
        worker = Backend(answer(None, call('read_file', {'path': 'fact.txt'}, 'prior-read')),
            self.truncated(), self.write(),
            answer(None, call('shell', {'command': shlex.quote(sys.executable)
                + ' -S -m unittest test_delivery -v', 'timeout': 10}, 'owned-check')),
            answer('Delivered and checked.'))
        parent = Backend(answer(None, call('delegate', {'task': 'Read fact.txt, implement delivered.py and run test_delivery.',
            'backend_preference': 'cloud', 'tier': 'LIGHT', 'read_only': False, 'mode': 'async'}, 'spawn')),
            answer(None, call('wait_children', {}, 'collect')), answer('Collected delivery.'))
        policy = AsyncPolicy(max_children_per_turn=2)
        budgets = replace(self.budgets, max_steps=32, max_token_units=4000000, max_tool_calls=32,
            max_worker_steps=8, max_worker_tool_calls=12, max_worker_token_units=1000000,
            max_worker_output_tokens=4096, max_subagents_per_turn=2)

        def factory(callback):
            runtime = AgentSession(create_default_registry(self.workspace, permission_mode='full-permission'),
                cloud_backend=parent, cloud_worker_backends={'LIGHT': worker}, policy='cloud-only',
                streaming=False, engine_policy=EngineV5Policy(), async_policy=policy,
                event_callback=callback, budgets=budgets,
                retry_policy=RetryPolicy(max_attempts=1))
            apply_options(runtime, {'permission_mode': 'full', 'agent_profile': 'standard',
                'prompt_revision': 2, 'scope_revision': 3, 'execution_budget': 'standard'})
            return runtime

        service = TaskService({'localpilot': factory}, async_policy=policy,
            persistence=self.root / 'runtime.sqlite3')
        try:
            task = service.wait(service.create_task(TaskRequest('Delegate and verify delivery.'))['id'])
            runtime = service.sessions[task['session_id']].runtime
            child = runtime._children['1.1']
            self.assertEqual(task['status'], 'completed', task.get('error'))
            self.assertEqual(len(task['subagents']), 1)
            self.assertEqual(runtime._subagent_count, 1)
            self.assertEqual(runtime.budgets, budgets)
            self.assertEqual(child.budgets.max_output_tokens, 4096)
            self.assertEqual(child.budgets.max_steps, 8)
            self.assertTrue(task['subagents'][0]['collected'])
            self.assertEqual([r['id'] for r in child.tool_history], ['prior-read', 'small-patch', 'owned-check'])
            self.assertIn('Ran 1 test', child.tool_history[-1]['payload']['result']['stderr'])
            self.assertEqual(child.tool_history[-1]['payload']['result']['exit_code'], 0)
            self.assertFalse((self.workspace / 'discarded.txt').exists())
            self.assertEqual((self.workspace / 'delivered.py').read_text(), 'ANSWER = 42\n')
            self.assertEqual(child._usage[1].output_tokens, 4096)
            self.assertEqual(child._usage[1].finish_reason, 'length')
            self.assertEqual(sum(u.finish_reason == 'length' for u in runtime._usage), 1)
            self.assertEqual(child._attempts, 5)
            self.assertEqual(child._tool_proposals, 5)
            self.assertTrue(all(r['max_tokens'] == 4096 for r in worker.requests))
            continued = worker.requests[2]['messages']
            self.assertTrue(any(m.role == 'tool' and m.tool_call_id == 'prior-read' for m in continued))
            self.assertTrue(any('shorter complete tool calls' in (m.content or '') for m in continued))
            self.assertFalse(any(m.native_replay or 'INCOMPLETE-TEXT' in (m.content or '')
                or any(c.id in {'partial-patch', 'complete-but-discarded'} for c in m.tool_calls)
                for m in continued))
            recovery = [e for e in child.events.events if e.type == 'WorkerOutputRecovery']
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].data['worker_id'], '1.1')
            self.assertEqual(recovery[0].data['discarded_tool_proposals'], 2)
            self.assertTrue((self.root / 'runtime.sqlite3').is_file())
        finally:
            service.shutdown(timeout=10)

    def test_second_truncation_stops_without_dispatch_or_extra_request(self):
        runtime = self.child(self.truncated(), self.truncated(), self.write())
        result = runtime.run_turn('Write delivered.py.')
        self.assertEqual(result.status, 'error')
        self.assertEqual(len(runtime.cloud_backend.requests), 2)
        self.assertEqual(runtime.tool_history, [])
        self.assertFalse((self.workspace / 'discarded.txt').exists())
        self.assertFalse((self.workspace / 'delivered.py').exists())
        self.assertEqual(sum(e.type == 'WorkerOutputRecovery' for e in runtime.events.events), 1)

    def test_no_remaining_step_or_only_final_reserve_does_not_recover(self):
        for steps, reserve in [(1, False), (2, True)]:
            with self.subTest(steps=steps, reserve=reserve):
                runtime = self.child(self.truncated(), self.write(),
                    budgets=replace(self.budgets, max_steps=steps),
                    controls=StabilizationControls(reserve=reserve, working_state=False, cache_mode='off', stagnation_limit=0))
                result = runtime.run_turn('Write delivered.py.')
                self.assertEqual(result.status, 'error')
                self.assertEqual(len(runtime.cloud_backend.requests), 1)
                self.assertFalse(any(e.type == 'WorkerOutputRecovery' for e in runtime.events.events))
                self.assertFalse((self.workspace / 'discarded.txt').exists())

    def test_remaining_token_budget_can_refuse_the_continuation(self):
        runtime = self.child(self.truncated(), self.write(),
            budgets=replace(self.budgets, max_token_units=16000),
            controls=StabilizationControls(False, False, 'off', 0))
        result = runtime.run_turn('Write delivered.py.')
        self.assertEqual(result.status, 'error')
        self.assertEqual(len(runtime.cloud_backend.requests), 1)
        self.assertEqual(len(runtime._usage), 1)
        self.assertEqual(runtime._usage[0].finish_reason, 'length')
        self.assertIn('token admission budget exhausted', result.text)
        self.assertFalse((self.workspace / 'delivered.py').exists())

    def test_recovery_still_requires_mutation_approval(self):
        runtime = self.child(self.truncated(), self.write(), answer('done'),
            permission_mode='approve-mutations')
        result = runtime.run_turn('Write delivered.py.')
        self.assertEqual(result.status, 'approval_required')
        self.assertFalse((self.workspace / 'delivered.py').exists())
        result = runtime.approve()
        self.assertEqual(result.status, 'completed')
        self.assertEqual((self.workspace / 'delivered.py').read_text(), 'ANSWER = 42\n')
        self.assertEqual(len(runtime.tool_history), 1)

    def test_checkpoint_keeps_used_recovery_and_discards_partial_native_history(self):
        saved = []
        runtime = self.child(self.truncated())
        def checkpoint(point):
            if point == 'worker_output_recovery':
                saved.append(json.loads(json.dumps(snapshot_runtime(runtime))))
                raise PersistenceError('test checkpoint boundary')
        runtime._persistence_hook = checkpoint
        with self.assertRaises(PersistenceError):
            runtime.run_turn('Write delivered.py.')
        resumed = self.child(self.truncated(), self.write())
        restore_runtime(resumed, saved[0])
        result = resumed.continue_checkpoint()
        self.assertEqual(result.status, 'error')
        self.assertEqual(len(resumed.cloud_backend.requests), 1)
        self.assertEqual([u.finish_reason for u in resumed._usage], ['length', 'length'])
        self.assertEqual(sum(e.type == 'WorkerOutputRecovery' for e in resumed.events.events), 1)
        self.assertEqual(asdict(resumed.budgets), asdict(self.budgets))
        self.assertFalse((self.workspace / 'discarded.txt').exists())

    def test_host_cancellation_after_recovery_feedback_prevents_next_request(self):
        runtime = self.child(self.truncated(), self.write())
        def stop(event):
            if event.type == 'WorkerOutputRecovery':
                runtime.request_cancel('timed_out')
        runtime.events.callback = stop
        result = runtime.run_turn('Write delivered.py.')
        self.assertEqual(result.status, 'timed_out')
        self.assertEqual(len(runtime.cloud_backend.requests), 1)
        self.assertFalse((self.workspace / 'delivered.py').exists())

    def test_other_incomplete_reasons_are_not_recovered(self):
        for reason in ['content_filter', 'stream_interrupted']:
            with self.subTest(reason=reason):
                response = self.truncated()
                response.finish_reason = reason
                runtime = self.child(response, self.write())
                self.assertEqual(runtime.run_turn('Write delivered.py.').status, 'error')
                self.assertEqual(len(runtime.cloud_backend.requests), 1)
                self.assertFalse(any(e.type == 'WorkerOutputRecovery' for e in runtime.events.events))


if __name__ == '__main__':
    unittest.main()
