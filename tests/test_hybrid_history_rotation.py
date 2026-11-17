"""Hybrid request identities survive real pre-dispatch failures and rotation."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from agent.backends import ModelInfo
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.persistence import PersistenceError, snapshot_runtime
from agent.registry import ToolRegistry
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskRequest, TaskService
from tests.test_runtime_api import Backend, answer


class HybridHistoryRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.backend = Backend(answer('first answer'), answer('third answer'))
        self.backend.model_info = ModelInfo('bounded-hybrid-fixture', 'scripted', 4000)
        self.backend.service_cache_stable_prefix = True
        self.services = []

    def tearDown(self):
        for service in self.services:
            if service.store.connection:
                if service.store.failed:
                    service.store.close()
                else:
                    service.shutdown()
        self.temp.cleanup()

    def factory(self, callback):
        return AgentSession(ToolRegistry(self.workspace), backend=self.backend,
            policy='cloud-only', streaming=False, event_callback=callback,
            system_prompt='Complete the request.', runtime_tools=False,
            engine_policy=EngineV5Policy(max_completion_repairs=0),
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
            hybrid_backends={'selected': self.backend}, hybrid_primary='selected',
            budgets=SessionBudgets(max_steps=12, max_token_units=1000000, max_output_tokens=256))

    def service(self):
        service = TaskService({'localpilot': self.factory}, persistence=self.root / 'runtime.sqlite3',
                              history_rotation_bytes=1)
        self.services.append(service)
        return service

    def test_zero_dispatch_turn_keeps_attempt_identity_after_rotation_commit_and_restart(self):
        service = self.service()
        first_request = TaskRequest('Keep this exact original question.', idempotency_key='first')
        first = service.wait(service.create_task(first_request)['id'])
        self.assertEqual(first['status'], 'completed')
        first_window = deepcopy(self.backend.requests[-1]['messages'])
        sid = first['session_id']
        oversized_input = 'Z' * 4000
        second = service.wait(service.create_task(TaskRequest(oversized_input, session_id=sid))['id'])
        self.assertEqual(second['status'], 'failed')
        self.assertIn('protected task', second['result']['text'])
        self.assertEqual(len(self.backend.requests), 1)
        runtime = service.sessions[sid].runtime
        original = snapshot_runtime(runtime)
        original_id = runtime.hybrid.state['attempts'][-1]['id']
        self.assertEqual(runtime.turn_id, 2)
        self.assertFalse(any(attempt['turn_id'] == 2 for attempt in runtime.hybrid.state['attempts']))

        def fail(stage, point):
            if stage == 'after_commit' and point == 'history_rotated':
                raise OSError('interrupted after history rotation commit')

        service.store.fault_hook = fail
        third_request = TaskRequest('Continue with a short question.', session_id=sid, idempotency_key='third')
        with self.assertRaises(PersistenceError):
            service.create_task(third_request)
        self.assertTrue(service.store.failed)
        self.assertEqual(len(self.backend.requests), 1)
        service.store.close()

        service = self.service()
        archived = service.store.runtime_segment(sid, 0)
        self.assertEqual(archived['runtime'], original)
        self.assertTrue(any(message['content'] == oversized_input for message in archived['runtime']['messages']))
        self.assertEqual(service.task_snapshot(first['id']), first)
        self.assertEqual(service.task_snapshot(second['id']), second)
        self.assertEqual(service.create_task(first_request), first)
        self.assertEqual(len(self.backend.requests), 1)
        restored = service.sessions[sid].runtime
        self.assertEqual(restored.messages[restored._request_history.source_count].content, 'first answer')
        self.assertEqual(sum(message.role == 'system' for message in restored.messages), 1)
        third = service.wait(service.create_task(third_request)['id'])
        self.assertEqual(third['status'], 'completed')
        self.assertEqual(len(self.backend.requests), 2)
        admitted = self.backend.requests[-1]['messages']
        self.assertEqual(admitted[:len(first_window)], first_window)
        self.assertEqual(sum(message.content == 'first answer' for message in admitted), 1)
        self.assertEqual(sum(message.role == 'system' for message in admitted), 1)
        attempts = service.sessions[sid].runtime.hybrid.state['attempts']
        self.assertEqual(attempts[-1]['id'], original_id + 1)
        self.assertEqual(attempts[-1]['turn_id'], 3)
        self.assertEqual(attempts[-1]['task_identity']['task_id'], third['id'])
        self.assertEqual(third['result']['runtime_metrics']['hybrid']['calls'], 1)
        final_attempts = deepcopy(attempts)
        service.suspend()
        service = self.service()
        self.assertEqual(service.sessions[sid].runtime.hybrid.state['attempts'], final_attempts)
        self.assertEqual(service.task_snapshot(third['id']), third)
        self.assertEqual(service.create_task(third_request), third)
        self.assertEqual(len(self.backend.requests), 2)


if __name__ == '__main__':
    unittest.main()
