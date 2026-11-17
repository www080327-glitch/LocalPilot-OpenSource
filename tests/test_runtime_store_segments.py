"""Real SQLite migration, atomic segment writes and lifetime journal checks."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import tracemalloc
import unittest

from agent.persistence import PersistenceError, SQLiteRuntimeStore, digest, dumps, pack


class RuntimeStoreSegmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'runtime.sqlite3'
        self.payload = {'version': 1, 'session': {'id': 'session-one', 'history_generation': 0},
                        'runtime': {'messages': ['original question', 'original answer']}, 'tasks': []}

    def store(self, **options):
        store = SQLiteRuntimeStore(self.path, **options)
        self.addCleanup(store.close)
        return store

    def test_schema2_migration_preserves_archives_and_verified_private_backup(self):
        store = self.store()
        task = pack({'id': 'task-one', 'request_key_digest': 'original-key', 'output': ['original result']})
        store.save('session-one', self.payload, 'task_archived', archived_tasks=[task])
        store.close()
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TABLE runtime_segments')
            db.execute('PRAGMA user_version=2')
            checkpoints = db.execute('SELECT * FROM checkpoints').fetchall()
            journal = db.execute('SELECT * FROM journal').fetchall()
            tasks = db.execute('SELECT * FROM archived_tasks').fetchall()
        store = self.store()
        backup = store.migration_backup
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT * FROM checkpoints').fetchall(), checkpoints)
            self.assertEqual(db.execute('SELECT * FROM journal').fetchall(), journal)
            self.assertEqual(db.execute('SELECT * FROM archived_tasks').fetchall(), tasks)
        self.assertEqual(store.load(), [self.payload])
        self.assertEqual(store.archived_task_for_key('original-key'), task)
        self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0], 3)
        store.close()
        store = self.store()
        self.assertIsNone(store.migration_backup)
        self.assertEqual(list(self.path.parent.glob('runtime.sqlite3.schema2-backup-*.sqlite3')), [backup])

    def test_segment_and_checkpoint_commit_together_across_faults(self):
        for stage in ('before_commit', 'after_commit'):
            with self.subTest(stage=stage):
                self.path = Path(self.temp.name) / (stage + '.sqlite3')
                store = self.store()
                store.save('session-one', self.payload, 'initial')
                updated = deepcopy(self.payload)
                updated['session']['history_generation'] = 1
                updated['runtime']['messages'] = ['retained answer']
                segment = {'version': 1, 'generation': 0, 'last_turn': 2,
                           'runtime': deepcopy(self.payload['runtime'])}
                task = pack({'id': 'task-one', 'request_key_digest': 'original-key'})

                def fail(at, point):
                    if at == stage and point == 'history_rotated':
                        raise OSError('injected storage interruption')

                store.fault_hook = fail
                with self.assertRaises(PersistenceError):
                    store.save('session-one', updated, 'history_rotated',
                               archived_runtime=segment, archived_tasks=[task])
                self.assertTrue(store.failed)
                store.close()
                store = self.store()
                committed = stage == 'after_commit'
                self.assertEqual(store.load(), [updated if committed else self.payload])
                self.assertEqual(store.runtime_segment('session-one', 0), segment if committed else None)
                self.assertEqual(store.archived_task_for_key('original-key'), task if committed else None)

    def test_archived_segments_are_paged_and_checked_only_on_read(self):
        store = self.store()
        segments = []
        for generation in range(4):
            segment = {'version': 1, 'generation': generation, 'last_turn': generation + 1,
                       'runtime': {'messages': [f'exact original {generation}']}}
            store.save('session-one', self.payload, 'history_rotated', archived_runtime=segment)
            segments.append(segment)
        self.assertEqual(store.runtime_segments('session-one', limit=2), segments[:1:-1])
        self.assertEqual(store.runtime_segments('session-one', before=2), segments[1::-1])
        self.assertEqual(store.runtime_segments('other-session'), [])
        self.assertIsNone(store.runtime_segment('other-session', 0))
        store.connection.execute("UPDATE runtime_segments SET payload='{}' WHERE generation=0")
        self.assertEqual(store.load(), [self.payload])
        with self.assertRaises(PersistenceError):
            store.runtime_segment('session-one', 0)
        self.assertTrue(store.failed)

    def test_journal_gaps_extra_revisions_and_wrong_tip_are_rejected(self):
        mutations = {
            'gap': 'DELETE FROM journal WHERE revision=2',
            'shifted': 'UPDATE journal SET revision=0 WHERE revision=1',
            'future': 'UPDATE journal SET revision=4 WHERE revision=2',
            'fractional': 'UPDATE journal SET revision=1.5 WHERE revision=2',
            'wrong_tip': "UPDATE journal SET sha256='wrong' WHERE revision=3",
            'empty': 'DELETE FROM journal',
            'orphan': "INSERT INTO journal VALUES('orphan',1,'orphan','wrong',0)",
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                self.path = Path(self.temp.name) / (name + '.sqlite3')
                store = self.store()
                for _ in range(3):
                    store.save('session-one', self.payload, 'checkpoint')
                store.connection.execute(mutation)
                with self.assertRaises(PersistenceError):
                    store.load()

    def test_large_journal_restore_avoids_lifetime_python_allocation(self):
        store = self.store()
        store.save('session-one', self.payload, 'initial')
        checksum = digest(dumps(self.payload))
        revisions = 20000
        store.connection.execute('BEGIN IMMEDIATE')
        store.connection.executemany('INSERT INTO journal VALUES(?,?,?,?,?)',
            (('session-one', i, 'checkpoint', checksum, 0) for i in range(2, revisions + 1)))
        store.connection.execute('UPDATE checkpoints SET revision=?', (revisions,))
        store.connection.execute('COMMIT')
        tracemalloc.start()
        try:
            self.assertEqual(store.load(), [self.payload])
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # The prior fetchall/list(range) path used several MB for this journal.
        self.assertLess(peak, 512 * 1024)


if __name__ == '__main__':
    unittest.main()
