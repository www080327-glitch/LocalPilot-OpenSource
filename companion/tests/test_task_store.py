"""Real SQLite migration, indexed lookup and retained task identity."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from companion.memory.store import MemoryStore
from companion.memory.task_store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'memory.sqlite3'

    def legacy(self, records):
        original = json.dumps(records, ensure_ascii=False)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        with db:
            db.execute('CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('INSERT INTO state VALUES(?,?)', ('localpilot_tasks', original))
            db.execute('INSERT INTO state VALUES(?,?)', ('unrelated', '{"keep":true}'))
        return db, original

    def test_legacy_migration_preserves_records_and_private_rollback_backup(self):
        records = {
            'old-task': {'timestamp':11, 'endpoint':'http://first', 'submission_id':'old-idempotency',
                         'transport':{'subject':'owner', 'provider_kind':'cloud', 'scope':'grant'},
                         'request':{'user_request':'未完成事项原文 🌱', 'references':['a', 'b']},
                         'result':{'session_id':'old-session'}, 'last_status':{'status':'completed'},
                         'last_event_cursor':17, 'unknown_old_field':{'retain':[1, None, False]}},
            'missing-optionals': {'endpoint':'http://second'},
        }
        db, original = self.legacy(records)
        db.close()
        store = MemoryStore(self.path)
        backup = store.tasks.backup_path
        self.assertIsNotNone(backup)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(backup)) as old:
            self.assertEqual(old.execute('PRAGMA quick_check').fetchone()[0], 'ok')
            self.assertEqual(old.execute("SELECT value FROM state WHERE key='localpilot_tasks'").fetchone()[0], original)
            self.assertIsNone(old.execute("SELECT name FROM sqlite_master WHERE name='localpilot_tasks'").fetchone())
        self.assertEqual(store.tasks.count(), 2)
        for task_id, record in records.items():
            self.assertEqual(store.tasks.get(task_id), record)
        self.assertIsNone(store.get('localpilot_tasks'))
        self.assertEqual(store.get('unrelated'), {'keep':True})
        changed = deepcopy(records['old-task'])
        changed['last_event_cursor'] = 18
        store.tasks.put('old-task', changed)
        store.close()
        store = MemoryStore(self.path)
        try:
            self.assertIsNone(store.tasks.backup_path)
            self.assertEqual(store.tasks.get('old-task'), changed)
            self.assertEqual(store.tasks.get('missing-optionals'), records['missing-optionals'])
            self.assertEqual(len(list(self.path.parent.glob('*.task-rows-backup-*.sqlite3'))), 1)
        finally:
            store.close()

    def test_failed_migration_rolls_back_rows_schema_and_old_key(self):
        for denied in ('delete', 'commit'):
            with self.subTest(denied=denied):
                path = self.path
                db, original = self.legacy({'one':{'timestamp':1}, 'two':{'timestamp':2}})
                statements = []
                db.set_trace_callback(statements.append)
                def authorize(action, first, second, database, trigger):
                    if denied == 'delete' and action == sqlite3.SQLITE_DELETE and first == 'state':
                        return sqlite3.SQLITE_DENY
                    if denied == 'commit' and action == sqlite3.SQLITE_TRANSACTION and first == 'COMMIT':
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                db.set_authorizer(authorize)
                with self.assertRaises(sqlite3.DatabaseError):
                    TaskStore(db)
                db.set_authorizer(None)
                self.assertFalse(db.in_transaction)
                self.assertEqual(db.execute("SELECT value FROM state WHERE key='localpilot_tasks'").fetchone()[0], original)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='localpilot_tasks'").fetchone())
                self.assertIn('ROLLBACK', statements)
                db.close()
                store = MemoryStore(path)
                self.assertEqual(store.tasks.count(), 2)
                store.close()
                self.path = self.path.with_name('second.sqlite3')

    def test_invalid_legacy_timestamp_does_not_partially_import_or_remove_history(self):
        db, original = self.legacy({'valid':{'timestamp':1}, 'invalid':{'timestamp':'yesterday'}})
        try:
            with self.assertRaisesRegex(ValueError, 'timestamp'):
                TaskStore(db)
            self.assertEqual(db.execute("SELECT value FROM state WHERE key='localpilot_tasks'").fetchone()[0], original)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='localpilot_tasks'").fetchone())
            self.assertEqual(list(self.path.parent.glob('*.task-rows-backup-*.sqlite3')), [])
        finally:
            db.close()

    def test_row_updates_and_recovery_do_not_replace_other_or_richer_records(self):
        store = MemoryStore(self.path)
        try:
            store.tasks.put('first', {'timestamp':1, 'last_event_cursor':12, 'feedback':{'text':'retained'}})
            store.tasks.put('other', {'timestamp':2, 'request':{'text':'原文' * 1000}})
            old = store.db.execute("SELECT payload FROM localpilot_tasks WHERE task_id='other'").fetchone()[0]
            store.tasks.put_if_absent('first', {'timestamp':0, 'last_event_cursor':0})
            self.assertEqual(store.tasks.get('first')['last_event_cursor'], 12)
            first = store.tasks.get('first')
            first['last_event_cursor'] = 13
            store.tasks.put('first', first)
            self.assertEqual(store.tasks.get('first')['feedback'], {'text':'retained'})
            self.assertEqual(store.db.execute("SELECT payload FROM localpilot_tasks WHERE task_id='other'").fetchone()[0], old)
            self.assertEqual(store.tasks.count(), 2)
            self.assertIsNone(store.get('localpilot_tasks'))
        finally:
            store.close()

    def test_session_queries_preserve_endpoint_scope_and_inclusive_time_boundary(self):
        store = MemoryStore(self.path)
        try:
            records = {
                'one': {'endpoint':'current', 'timestamp':1, 'result':{'session_id':'session'}},
                'two': {'endpoint':'current', 'timestamp':2, 'last_status':{'session_id':'session'}},
                'later': {'endpoint':'current', 'timestamp':3, 'result':{'session_id':'session'}},
                'foreign': {'endpoint':'other', 'timestamp':1, 'result':{'session_id':'session'}},
                'unrelated': {'endpoint':'current', 'timestamp':1, 'result':{'session_id':'elsewhere'}},
            }
            for task_id, record in records.items():
                store.tasks.put(task_id, record)
            self.assertEqual(list(store.tasks.session_records('current', 'session', 2)), [records['one'], records['two']])
            self.assertEqual(len(list(store.tasks.session_records('current', 'session'))), 3)
            self.assertTrue(store.tasks.has_session('session'))
            self.assertFalse(store.tasks.has_session('absent'))
        finally:
            store.close()

    def test_startup_candidates_are_indexed_bounded_and_exclude_terminal_or_other_grants(self):
        store = MemoryStore(self.path)
        try:
            for i in range(20):
                record = {'timestamp':i, 'endpoint':'current', 'transport':{'scope':'consent'},
                          'last_status':{'status':'completed' if i >= 5 else 'running'}}
                store.tasks.put(str(i), record)
            store.tasks.put('foreign', {'timestamp':100, 'endpoint':'other', 'transport':{'scope':'consent'}})
            store.tasks.put('revoked', {'timestamp':101, 'endpoint':'current', 'transport':{'scope':'revoked'}})
            self.assertEqual([task_id for task_id, _ in store.tasks.resumable('current', 'consent')], ['4', '3'])
            record = store.tasks.get('4')
            record['last_status']['status'] = 'failed'
            store.tasks.put('4', record)
            self.assertEqual([task_id for task_id, _ in store.tasks.resumable('current', 'consent')], ['3', '2'])
            plan = store.db.execute("EXPLAIN QUERY PLAN SELECT payload FROM localpilot_tasks WHERE endpoint=? AND scope=? AND active=1 ORDER BY timestamp DESC,task_id DESC LIMIT 2", ('current', 'consent')).fetchall()
            self.assertTrue(any('task_history_active' in row[3] for row in plan))
            self.assertFalse(any('TEMP B-TREE' in row[3] for row in plan))
        finally:
            store.close()

    def test_clear_removes_task_rows_and_migration_backup_without_resurrection(self):
        db, _ = self.legacy({'old-task':{'timestamp':1, 'request':{'text':'erase me'}}})
        db.close()
        store = MemoryStore(self.path)
        backup = store.tasks.backup_path
        self.assertTrue(backup.exists())
        store.clear(state={'keep':True})
        self.assertEqual(store.tasks.count(), 0)
        self.assertFalse(backup.exists())
        store.close()
        store = MemoryStore(self.path)
        try:
            self.assertEqual(store.tasks.count(), 0)
            self.assertEqual(store.get('keep'), True)
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main()
