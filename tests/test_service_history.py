"""Durable capacity reclamation uses real AgentSession, SQLite and file receipts."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from agent.persistence import PersistenceError, SQLiteRuntimeStore
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession
from localpilot_api.service import APIError, TaskRequest, TaskService
from tests.test_runtime_api import Backend, answer, call


class ServiceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.path = self.root / 'runtime.db'
        self.backend = Backend(*(answer(str(i)) for i in range(30)))
        self.services = []
        self.factory_calls = 0
        self.mode = 'full-permission'

    def tearDown(self):
        for service in self.services:
            if service.store and service.store.connection:
                if service.store.failed:
                    service.store.close()
                else:
                    service.shutdown()
        self.temp.cleanup()

    def factory(self, callback):
        self.factory_calls += 1
        return AgentSession(create_default_registry(self.workspace, permission_mode=self.mode),
                            backend=self.backend, policy='cloud-only', streaming=False,
                            event_callback=callback, retry_policy=RetryPolicy(max_attempts=1))

    def service(self, **kwargs):
        service = TaskService({'localpilot': self.factory}, persistence=self.path, **kwargs)
        self.services.append(service)
        return service

    def task(self, service, request, **kwargs):
        return service.wait(service.create_task(request, **kwargs)['id'])

    def test_repeated_turns_retain_receipts_keys_and_events_with_bounded_live_tasks(self):
        self.backend = Backend(answer(None, call('apply_patch', {'changes': [
            {'path': 'receipt.txt', 'operation': 'create', 'content': 'once'}]}, 'write')),
            *(answer(str(i)) for i in range(16)))
        service = self.service(max_tasks=2, max_sessions=1)
        original = TaskRequest('write once', idempotency_key='first')
        first = self.task(service, original, owner_subject='alice')
        first_events = service.events(first['id'], wait_seconds=0)[0]
        for i in range(12):
            task = self.task(service, TaskRequest(str(i), session_id=first['session_id'], idempotency_key=str(i)))
            self.assertEqual(task['status'], 'completed')
            self.assertLessEqual(len(service.tasks), 2)
        self.assertNotIn(first['id'], service.tasks)
        self.assertEqual(service.task_snapshot(first['id']), first)
        self.assertEqual(service.events(first['id'], wait_seconds=0)[0], first_events)
        service.suspend()
        service = self.service(max_tasks=2, max_sessions=1)
        calls = len(self.backend.requests)
        self.assertEqual(service.create_task(original, owner_subject='alice'), first)
        with self.assertRaises(APIError) as changed:
            service.create_task(TaskRequest('different', idempotency_key='first'), owner_subject='alice')
        self.assertEqual(changed.exception.code, 'idempotency_conflict')
        with self.assertRaises(APIError) as other:
            service.create_task(original, owner_subject='bob')
        self.assertEqual(other.exception.code, 'task_not_found')
        self.assertEqual(service.cancel(first['id']), first)
        self.assertEqual(service.children(first['id']), first['subagents'])
        self.assertEqual((self.workspace / 'receipt.txt').read_text(), 'once')
        self.assertEqual(len(self.backend.requests), calls)
        self.assertLessEqual(len(service.tasks), 2)

    def test_closed_sessions_archive_without_recreating_runtimes_for_old_reads(self):
        service = self.service(max_sessions=2, max_tasks=2)
        saved = []
        for i in range(8):
            request = TaskRequest(str(i), idempotency_key=str(i))
            result = self.task(service, request, owner_subject='alice')
            view = service.close_session(result['session_id'])
            saved.append((request, result, view))
            self.assertLessEqual(len(service.sessions), 2)
            self.assertLessEqual(len(service.tasks), 2)
        service.suspend()
        service = self.service(max_sessions=2, max_tasks=2)
        factories = self.factory_calls
        for request, result, view in saved:
            self.assertEqual(service.task_snapshot(result['id']), result)
            self.assertEqual(service.session_snapshot(result['session_id']), view)
            self.assertEqual(service.close_session(result['session_id']), view)
            self.assertEqual(service.create_task(request, owner_subject='alice')['id'], result['id'])
        self.assertEqual(self.factory_calls, factories)
        self.assertIsNone(service._session(saved[0][1]['session_id']).runtime)
        self.assertEqual(service.session_scope(service._session(saved[0][1]['session_id']))['workspace'], str(self.workspace))

    def test_pending_approval_still_counts_and_is_not_archived(self):
        self.mode = 'approve-mutations'
        self.backend = Backend(answer(None, call('apply_patch', {'changes': [
            {'path': 'pending.txt', 'operation': 'create', 'content': 'later'}]}, 'pending')))
        service = self.service(max_tasks=1, max_sessions=1)
        pending = self.task(service, TaskRequest('pending', idempotency_key='pending'))
        self.assertEqual(pending['status'], 'requires_approval')
        with self.assertRaises(APIError) as full:
            service.create_task(TaskRequest('new', idempotency_key='new'))
        self.assertEqual(full.exception.code, 'capacity_exceeded')
        self.assertEqual(service.task_snapshot(pending['id']), pending)
        self.assertEqual(service.store.connection.execute('SELECT count(*) FROM archived_tasks').fetchone()[0], 0)
        self.assertFalse((self.workspace / 'pending.txt').exists())

    def test_unknown_effect_is_not_archived_to_make_room(self):
        self.backend = Backend(answer(None, call('apply_patch', {'changes': [
            {'path': 'unknown.txt', 'operation': 'create', 'content': 'real effect'}]}, 'unknown')))
        service = self.service(max_tasks=1)
        sid = service.create_session()['id']
        registry = service.sessions[sid].runtime.registry
        apply_patch = registry._tools['apply_patch']
        def lost_receipt(**kwargs):
            apply_patch(**kwargs)
            raise TimeoutError('receipt lost after real mutation')
        registry._tools['apply_patch'] = lost_receipt
        unknown = self.task(service, TaskRequest('unknown', session_id=sid, idempotency_key='unknown'))
        self.assertEqual(unknown['status'], 'requires_human')
        with self.assertRaises(APIError):
            service.create_task(TaskRequest('new'))
        self.assertIn(unknown['id'], service.tasks)
        self.assertEqual(service.store.connection.execute('SELECT count(*) FROM archived_tasks').fetchone()[0], 0)
        self.assertEqual((self.workspace / 'unknown.txt').read_text(), 'real effect')

    def test_archive_failure_fences_without_losing_original_receipt(self):
        service = self.service(max_tasks=1)
        first = self.task(service, TaskRequest('first', idempotency_key='first'))
        def fail(stage, point):
            if stage == 'before_commit' and point == 'task_archived':
                raise OSError('injected disk failure')
        service.store.fault_hook = fail
        with self.assertRaises(PersistenceError):
            service.create_task(TaskRequest('second', session_id=first['session_id']))
        self.assertIn(first['id'], service.tasks)
        self.assertEqual(len(self.backend.requests), 1)
        service.store.close()
        service = self.service(max_tasks=1)
        self.assertEqual(service.task_snapshot(first['id']), first)
        second = self.task(service, TaskRequest('second', session_id=first['session_id']))
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(service.task_snapshot(first['id']), first)

    def test_schema1_migration_keeps_verified_private_nonoverwriting_backup(self):
        self.backend = Backend(answer(None, call('apply_patch', {'changes': [
            {'path': 'migration.txt', 'operation': 'create', 'content': 'preserved'}]}, 'migration')),
            answer('saved'))
        service = self.service(max_tasks=1)
        first = self.task(service, TaskRequest('first', idempotency_key='first'))
        service.suspend()
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TABLE archived_tasks')
            db.execute('DROP TABLE archived_sessions')
            db.execute('DROP TABLE runtime_segments')
            db.execute('PRAGMA user_version=1')
            prior = db.execute('SELECT * FROM checkpoints').fetchall()
        service = self.service(max_tasks=1)
        backup = service.store.migration_backup
        self.assertIsNotNone(backup)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT * FROM checkpoints').fetchall(), prior)
        self.assertEqual(service.store.connection.execute('PRAGMA user_version').fetchone()[0], SQLiteRuntimeStore.VERSION)
        self.assertEqual(service.create_task(TaskRequest('first', idempotency_key='first')), first)
        self.assertEqual((self.workspace / 'migration.txt').read_text(), 'preserved')
        service.suspend()
        again = self.service(max_tasks=1)
        self.assertIsNone(again.store.migration_backup)
        self.assertEqual(list(self.root.glob('runtime.db.schema1-backup-*.sqlite3')), [backup])

    def test_archived_corruption_fences_before_replay(self):
        service = self.service(max_tasks=1)
        first = self.task(service, TaskRequest('first', idempotency_key='first'))
        self.task(service, TaskRequest('second', session_id=first['session_id']))
        service.store.connection.execute("UPDATE archived_tasks SET payload='{}'")
        with self.assertRaises(PersistenceError):
            service.create_task(TaskRequest('first', idempotency_key='first'))
        self.assertTrue(service.store.failed)
        self.assertEqual(len(self.backend.requests), 2)


if __name__ == '__main__':
    unittest.main()
