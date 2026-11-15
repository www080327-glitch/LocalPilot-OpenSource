"""Explicit scheduler upgrades against real SQLite, receipts and host factories."""
from pathlib import Path
import tempfile
import unittest

from agent.async_runtime import AsyncPolicy, policy_snapshot
from agent.persistence import PersistenceError, snapshot_runtime
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_api.service import TaskRequest, TaskService
from localpilot_service.restore_migration import async_policy_migration, configured_migration
from tests.test_runtime_api import Backend, answer, call


class AsyncMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.policy = None
        self.permission = 'full-permission'
        self.backend = Backend(answer('original answer'))
        self.services = []
        self.service = self.open()

    def tearDown(self):
        for service in self.services:
            if not service.closed:
                service.shutdown()
        self.temp.cleanup()

    def factory(self, callback):
        return AgentSession(create_default_registry(self.work, permission_mode=self.permission),
            backend=self.backend, policy='cloud-only', async_policy=self.policy, event_callback=callback)

    def open(self, migration=None):
        service = TaskService({'agent':self.factory}, persistence=self.root/'runtime.db',
                              async_policy=self.policy, configuration_migration=migration)
        self.services.append(service)
        return service

    def populated(self):
        sid = self.service.create_session('agent')['id']
        self.backend.steps = [answer(None, call('apply_patch', {
            'changes':[{'path':'written.txt', 'operation':'create', 'content':'write once'}]}, 'write-once')),
            answer('saved')]
        task = self.service.create_task(TaskRequest('Save the marker.', model='agent', session_id=sid,
                                                   idempotency_key='one-task'))
        self.service.wait(task['id'])
        self.assertEqual(self.service.task_snapshot(task['id'])['status'], 'completed')
        return sid, task['id']

    def pinned(self, sid):
        payload = next(p for p in self.service.store.load() if p['session']['id'] == sid)
        return {'version':1, 'sessions':[{'session_id':sid, 'configuration_sha256':payload['configuration']}]}

    def test_enable_resize_disable_and_restart_preserve_receipts_and_requests(self):
        sid, tid = self.populated()
        original = snapshot_runtime(self.service.sessions[sid].runtime)
        for policy in (AsyncPolicy(), AsyncPolicy(max_running_per_session=4, max_model_requests=3), None):
            spec = self.pinned(sid)
            self.service.suspend()
            self.policy = policy
            self.service = self.open(async_policy_migration(spec))
            actual = snapshot_runtime(self.service.sessions[sid].runtime)
            for key in ('messages', 'history', 'completed', 'children'):
                self.assertEqual(actual[key], original[key], key)
            self.assertEqual(actual.get('async'), {'policy':policy_snapshot(policy)} if policy else None)
            retry = self.service.create_task(TaskRequest('Save the marker.', model='agent', session_id=sid,
                                                        idempotency_key='one-task'))
            self.assertEqual(retry['id'], tid)
            self.assertEqual((self.work/'written.txt').read_text(), 'write once')
            self.service.suspend()
            self.service = self.open()
            self.assertEqual(self.service.sessions[sid].runtime.async_policy, policy)
        self.assertEqual(len(self.backend.requests), 2)

    def test_no_plan_wrong_fingerprint_and_changed_permission_are_rejected(self):
        sid, _ = self.populated()
        spec = self.pinned(sid)
        self.service.suspend()
        self.policy = AsyncPolicy()
        with self.assertRaises(PersistenceError):
            self.open()
        wrong = {'version':1, 'sessions':[{'session_id':sid, 'configuration_sha256':'0'*64}]}
        with self.assertRaises(PersistenceError):
            self.open(async_policy_migration(wrong))
        self.permission = 'approve-mutations'
        with self.assertRaises(PersistenceError):
            self.open(async_policy_migration(spec))
        self.assertEqual((self.work/'written.txt').read_text(), 'write once')

    def test_waiting_approval_cannot_be_migrated(self):
        self.permission = 'approve-mutations'
        sid = self.service.create_session('agent')['id']
        self.backend.steps = [answer(None, call('apply_patch', {
            'changes':[{'path':'pending.txt','operation':'create','content':'pending'}]}, 'pending'))]
        task = self.service.create_task(TaskRequest('Write pending.', model='agent', session_id=sid))
        self.service.wait(task['id'])
        self.assertEqual(self.service.task_snapshot(task['id'])['status'], 'requires_approval')
        spec = self.pinned(sid)
        self.service.suspend()
        self.policy = AsyncPolicy()
        with self.assertRaises(PersistenceError):
            self.open(async_policy_migration(spec))
        self.assertFalse((self.work/'pending.txt').exists())

    def test_unknown_effects_remain_blocked(self):
        sid = self.service.create_session('agent')['id']
        registry = self.service.sessions[sid].runtime.registry
        real_write = registry._tools['apply_patch']

        def lost_receipt(**args):
            real_write(**args)
            raise TimeoutError('Receipt lost after writing')

        registry._tools['apply_patch'] = lost_receipt
        self.backend.steps = [answer(None, call('apply_patch', {
            'changes':[{'path':'unknown.txt', 'operation':'create', 'content':'already written'}]}, 'uncertain'))]
        task = self.service.create_task(TaskRequest('Write once.', model='agent', session_id=sid))
        self.service.wait(task['id'])
        spec = self.pinned(sid)
        calls = len(self.backend.requests)
        self.service.suspend()
        self.policy = AsyncPolicy()
        with self.assertRaises(PersistenceError):
            self.open(async_policy_migration(spec))
        self.assertEqual((self.work/'unknown.txt').read_text(), 'already written')
        self.assertEqual(len(self.backend.requests), calls)

    def test_plan_schema_is_checked_at_configuration_boundary(self):
        for spec in ({}, {'version':1,'sessions':[]}, {'version':2,'sessions':[{}]},
                     {'version':1,'sessions':[{'session_id':'s','configuration_sha256':'wrong'}]}):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                configured_migration({'restore_async_policy_migration':spec})


if __name__ == '__main__':
    unittest.main()
