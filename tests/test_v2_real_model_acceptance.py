"""Child capability denial found with REAL Qwen; model responses are scripted here."""
import tempfile
import unittest
from pathlib import Path
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskService, TaskRequest, SETTLED
from tests.test_runtime_api import Backend, answer, call


class ChildCapabilityDenialTests(unittest.TestCase):
    def test_denied_child_write_remains_unfinished_in_runtime_and_api(self):
        for use_api in (False, True):
            with self.subTest(use_api=use_api), tempfile.TemporaryDirectory() as directory:
                model = Backend(answer(None, call('delegate', {'task': 'Create first.txt.',
                    'backend_preference': 'cloud', 'read_only': True}, 'delegate')),
                    answer(None, call('apply_patch', {'changes': [{'operation': 'create',
                        'path': 'first.txt', 'content': 'FIRST'}]}, 'create-first')),
                    answer('Write denied; file not created.'), answer('Unable to create the file.'))
                sessions = []
                def factory(callback=None):
                    session = AgentSession(create_default_registry(directory, permission_mode='approve-mutations'),
                        backend=model, policy='cloud-only', streaming=False, event_callback=callback,
                        retry_policy=RetryPolicy(max_attempts=1), budgets=SessionBudgets(max_steps=12,
                            max_worker_steps=6, max_token_units=1048576, max_worker_token_units=262144))
                    sessions.append(session)
                    return session
                service = None
                try:
                    if use_api:
                        service = TaskService({'localpilot': factory})
                        initial = service.create_task(TaskRequest('Create the file using a worker.'))
                        with service.condition:
                            self.assertTrue(service.condition.wait_for(lambda: service.tasks[initial['id']].status in SETTLED and not service.tasks[initial['id']].executing, 5))
                        pending = service.task_snapshot(initial['id'])
                        service.act(pending['id'], 'approve', pending['required_action']['id'])
                        with service.condition:
                            self.assertTrue(service.condition.wait_for(lambda: service.tasks[pending['id']].status in SETTLED and not service.tasks[pending['id']].executing, 5))
                        status = service.task_snapshot(pending['id'])['status']
                    else:
                        session = factory()
                        session.run_turn('Create the file using a worker.')
                        status = session.approve().status
                    parent = sessions[0]
                    worker = parent.subagents[0]
                    self.assertFalse((Path(directory) / 'first.txt').exists())
                    self.assertEqual(worker['receipts'][0]['payload']['result']['status'], 'denied')
                    self.assertEqual(status, 'incomplete')
                    self.assertEqual(worker['obligation_status'], 'unresolved')
                    self.assertEqual(len(worker['unfinished_calls']), 1)
                    self.assertEqual(len(parent._usage), len(model.requests))
                    self.assertTrue(all(c.pending_approval is None for c in parent._children.values()))
                finally:
                    if service:
                        service.shutdown()
                    for session in sessions:
                        session.close()
