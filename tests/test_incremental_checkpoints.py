"""Real checkpoint transactions, canonical restoration and long worker receipts."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from agent.checkpoint_blocks import CheckpointBatch
from agent.engine_v5 import EngineV5Policy
from agent.persistence import PersistenceError, SQLiteRuntimeStore, snapshot_runtime, unpack
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskRequest, TaskService
from tests.test_runtime_api import Backend, answer, call


class IncrementalCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.services = []

    def tearDown(self):
        for service in self.services:
            store, service.store = service.store, None
            if store:
                store.close()
            if not service.closed:
                service.shutdown(timeout=3)
        self.temp.cleanup()

    def service(self, count=1, *, child=False, **options):
        for index in range(count):
            (self.workspace / f'fact-{index}.txt').write_text('Original fact ' + str(index) + '\n' + 'retained text ' * 200)
        reader = Backend(*(answer(None, call('read_file', {'path': f'fact-{index}.txt'}, f'read-{index}'))
                           for index in range(count)), answer('All facts read.'))
        parent = (Backend(answer(None, call('delegate', {'task': 'Read the fact files.',
            'backend_preference': 'cloud', 'tier': 'LIGHT'}, 'delegate')), answer('Child collected.')) if child else reader)
        def factory(callback):
            return AgentSession(create_default_registry(self.workspace, permission_mode='full-permission'),
                cloud_backend=parent, cloud_worker_backends={'LIGHT': reader} if child else {},
                policy='cloud-only', event_callback=callback, streaming=False,
                engine_policy=EngineV5Policy(max_completion_repairs=0), retry_policy=RetryPolicy(max_attempts=1),
                budgets=SessionBudgets(max_steps=count + 20, max_tool_calls=count + 20,
                    max_token_units=256000000, max_output_tokens=512,
                    max_worker_steps=count + 4, max_worker_tool_calls=count + 4,
                    max_worker_token_units=128000000, max_worker_output_tokens=512))
        service = TaskService({'localpilot': factory}, persistence=self.root / 'runtime.db', **options)
        self.services.append(service)
        return service

    @staticmethod
    def normalized(snapshot):
        result = deepcopy(snapshot)
        for name in ('fields', 'working', 'completed'):
            result[name] = unpack(result[name])
        result['children'] = {key: IncrementalCheckpointTests.normalized(value)
                              for key, value in result['children'].items()}
        return result

    def test_long_task_writes_only_new_receipts_and_restores_exact_canonical_state(self):
        service = self.service(40)
        samples = []
        checkpoint = service._checkpoint
        def capture(session_id, point, **kwargs):
            checkpoint(session_id, point, **kwargs)
            if point == 'tool_receipt':
                samples.append(dict(service.store.last_checkpoint_write))
        service._checkpoint = capture
        task = service.wait(service.create_task(TaskRequest('Read the fact files.'))['id'])
        self.assertEqual(task['status'], 'completed')
        self.assertEqual(len(task['tools']), 40)
        self.assertLessEqual(max(row['block_rows'] for row in samples), 8)
        self.assertLess(samples[-1]['serialized_bytes'], 100000)
        self.assertLess(samples[-1]['serialized_bytes'], samples[31]['serialized_bytes'] * 1.2)
        runtime = service.sessions[task['session_id']].runtime
        self.assertEqual(self.normalized(service.store.load()[0]['runtime']), self.normalized(snapshot_runtime(runtime)))
        self.assertEqual(unpack(service.store.load()[0]['tasks'][0]), unpack(service._task_payload(service._task(task['id']))))
        self.assertEqual(service.store.connection.execute('PRAGMA user_version').fetchone()[0], 4)

    def test_long_synchronous_child_does_not_reserialize_parent_receipt_copy(self):
        service = self.service(32, child=True)
        samples = []
        checkpoint = service._checkpoint
        def capture(session_id, point, **kwargs):
            checkpoint(session_id, point, **kwargs)
            runtime = service.sessions[session_id].runtime
            if point == 'tool_receipt' and runtime._children and runtime._children['1.1'].tool_history:
                samples.append(dict(service.store.last_checkpoint_write))
        service._checkpoint = capture
        task = service.wait(service.create_task(TaskRequest('Delegate the reads.'))['id'])
        self.assertEqual(task['status'], 'completed', task.get('error'))
        runtime = service.sessions[task['session_id']].runtime
        child = runtime._children['1.1']
        self.assertEqual(len(child.tool_history), 32)
        self.assertIs(runtime.subagents[0]['receipts'], child.tool_history)
        self.assertEqual(self.normalized(service.store.load()[0]['runtime']), self.normalized(snapshot_runtime(runtime)))
        self.assertLess(max(row['block_rows'] for row in samples[:32]), 16)
        self.assertLess(samples[31]['serialized_bytes'], samples[15]['serialized_bytes'] * 1.8)

    def test_retired_sessions_release_cached_sources_but_keep_exact_stored_history(self):
        service = self.service(max_sessions=1)
        ids = []
        for index in range(4):
            if index:
                service.sessions[ids[-1]].runtime.cloud_backend.steps.append(answer('Next task complete.'))
            task = service.wait(service.create_task(TaskRequest('Read a fact.'))['id'])
            self.assertEqual(task['status'], 'completed')
            ids.append(task['session_id'])
            service.close_session(task['session_id'])
            self.assertEqual(set(service.store._block_cache), {task['session_id']})
        self.assertEqual(len(service.store.load(include_archived=True)), 4)
        self.assertIsNotNone(service.store.archived_session(ids[0]))

    def test_structural_edits_and_tool_controlled_type_tags_survive_materialization(self):
        store = SQLiteRuntimeStore(self.root / 'edits.db')
        self.addCleanup(store.close)
        owner = SimpleNamespace(items=[{'$json': {'_block_checkpoint': {'leaves': []}}}, {'value': 'a'}, {'value': 'b'}])
        def save():
            batch = CheckpointBatch(store, 'one')
            payload = {'version': 1, 'session': {'id': 'one'}, 'runtime': {
                'messages': batch.sequence(owner, 'items', lambda value: value, ['messages'])}, 'tasks': []}
            store.save('one', payload, 'edit', blocks=batch)
            self.assertEqual(store.load()[0]['runtime']['messages'], list(owner.items))
        save()
        owner.items.append({'value': 'c'}); save()
        owner.items[1] = {'value': 'changed'}; save()
        owner.items[::-1] = list(reversed(owner.items)); save()
        del owner.items[:2]; save()
        owner.items = [{'value': 'replaced'}]; save()
        old_journal = store.connection.execute('SELECT * FROM journal').fetchall()
        before = store.load()
        result = store.materialize_legacy()
        self.assertTrue(result['materialized'])
        self.assertEqual(store.load(), before)
        self.assertEqual(store.connection.execute('SELECT * FROM journal ORDER BY revision').fetchall()[:-1], old_journal)
        self.assertEqual(store.connection.execute('SELECT point FROM journal ORDER BY revision DESC LIMIT 1').fetchone()[0], 'legacy_materialized')
        self.assertEqual(store.connection.execute('SELECT count(*) FROM checkpoint_blocks').fetchone()[0], 0)

    def test_block_commits_and_legacy_export_are_atomic_at_both_fault_boundaries(self):
        for operation in ('append', 'export'):
            for stage in ('before_commit', 'after_commit'):
                with self.subTest(operation=operation, stage=stage):
                    path = self.root / f'{operation}-{stage}.db'
                    owner = SimpleNamespace(items=['original'])
                    store = SQLiteRuntimeStore(path)
                    def save(point):
                        batch = CheckpointBatch(store, 'one')
                        payload = {'version': 1, 'session': {'id': 'one'}, 'runtime': {
                            'messages': batch.sequence(owner, 'items', lambda value: value, ['messages'])}, 'tasks': []}
                        store.save('one', payload, point, blocks=batch)
                    save('initial')
                    journal = store.connection.execute('SELECT * FROM journal').fetchall()
                    def fail(where, point):
                        if where == stage:
                            raise OSError('actual transaction fault')
                    store.fault_hook = fail
                    with self.assertRaises(PersistenceError):
                        if operation == 'append':
                            owner.items.append('new'); save('append')
                        else:
                            store.materialize_legacy()
                    store.close()
                    reopened = SQLiteRuntimeStore(path)
                    try:
                        expected = ['original', 'new'] if operation == 'append' and stage == 'after_commit' else ['original']
                        self.assertEqual(reopened.load()[0]['runtime']['messages'], expected)
                        version = reopened.connection.execute('PRAGMA user_version').fetchone()[0]
                        self.assertEqual(version, 3 if operation == 'export' and stage == 'after_commit' else 4)
                        self.assertEqual(reopened.connection.execute('SELECT * FROM journal WHERE revision=1').fetchall(), journal)
                    finally:
                        reopened.close()

    def test_export_streams_only_block_heads_and_never_rewrites_existing_full_history(self):
        store = SQLiteRuntimeStore(self.root / 'mixed.db')
        self.addCleanup(store.close)
        old = {'version': 1, 'session': {'id': 'old'}, 'runtime': {'messages': ['old original']}, 'tasks': []}
        store.save('old', old, 'old_complete')
        checkpoint = store.connection.execute("SELECT * FROM checkpoints WHERE session_id='old'").fetchone()
        journal = store.connection.execute("SELECT * FROM journal WHERE session_id='old'").fetchall()
        owner = SimpleNamespace(items=['current original'])
        batch = CheckpointBatch(store, 'new')
        store.save('new', {'version': 1, 'session': {'id': 'new'}, 'runtime': {
            'messages': batch.sequence(owner, 'items', lambda value: value, ['messages'])}, 'tasks': []}, 'new', blocks=batch)
        result = store.materialize_legacy()
        self.assertEqual(result['converted_sessions'], 1)
        self.assertEqual(store.connection.execute("SELECT * FROM checkpoints WHERE session_id='old'").fetchone(), checkpoint)
        self.assertEqual(store.connection.execute("SELECT * FROM journal WHERE session_id='old'").fetchall(), journal)
        self.assertFalse(store.materialize_legacy()['materialized'])

    def test_missing_corrupt_and_reordered_blocks_refuse_restore_and_export(self):
        for index, change in enumerate(('DELETE FROM checkpoint_blocks WHERE position=0',
                       "UPDATE checkpoint_blocks SET payload='false' WHERE position=0",
                       'UPDATE checkpoint_blocks SET position=position+10')):
            with self.subTest(change=change):
                path = self.root / f'{index}-corrupt.db'
                store = SQLiteRuntimeStore(path)
                owner = SimpleNamespace(items=['one', 'two'])
                batch = CheckpointBatch(store, 'one')
                store.save('one', {'version': 1, 'session': {'id': 'one'}, 'runtime': {
                    'messages': batch.sequence(owner, 'items', lambda value: value, ['messages'])}, 'tasks': []}, 'initial', blocks=batch)
                store.connection.execute(change)
                with self.assertRaises(PersistenceError):
                    store.materialize_legacy()
                self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 4)
                store.close()
