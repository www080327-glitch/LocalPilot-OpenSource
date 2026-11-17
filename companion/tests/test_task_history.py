"""Bounded task presentation over retained SQLite records and real HTTP lookup."""
from copy import deepcopy
import json
import unittest

from companion.tests import test_v044_service as contract


class TaskHistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = contract.ServiceContractTests('test_native_submit_result_not_claimed_verified')
        self.fixture.setUp()
        self.app = self.fixture.host()

    def tearDown(self):
        self.fixture.doCleanups()
        self.fixture.tearDown()

    def completed_task(self):
        prepared = self.app.prepare_escalation(contract.request('Synthetic retained task'), mode='execution')
        view = self.app.command({'command':'submit_escalation', 'approved':True,
                                 'expected_digest':prepared['review_digest'], 'defer_monitor':True})
        self.fixture.service.wait(view['task_id'])
        return self.app.command({'command':'task_status', 'task_id':view['task_id']})

    def test_large_saved_history_does_not_break_snapshot_or_old_task_lookup(self):
        first = self.completed_task()
        task_id = first['task_id']
        seed = self.app.store.tasks.get(task_id)
        seed['timestamp'] = 1
        records = {task_id:seed}
        for index in range(1000):
            item = deepcopy(seed)
            item['timestamp'] = index + 2
            item['request']['user_request'] = '历史问题详细背景。' * 350
            records[f'historical-{index:05}'] = item
        for saved_id, record in records.items():
            self.app.store.tasks.put(saved_id, record)
        original = self.app.store.db.execute("SELECT task_id,payload FROM localpilot_tasks ORDER BY task_id").fetchall()
        self.assertGreater(sum(len(row['payload'].encode()) for row in original), 2_097_152)
        snapshot = self.app.command({'command':'ui_snapshot'})
        self.assertLess(len(json.dumps(snapshot, ensure_ascii=False).encode()), 2_097_152,
                        'CompanionClient rejects responses larger than 2 MiB')
        page = snapshot['escalation']
        self.assertEqual(len(page['tasks']), 30)
        self.assertEqual(page['total'], 1001)
        self.assertIsNotNone(page['next_before'])
        self.assertEqual(snapshot['runtime']['escalation_tasks'], page['tasks'])
        self.assertEqual(snapshot['runtime']['escalation_task_count'], page['total'])
        self.assertNotIn(task_id, page['tasks'])
        self.assertTrue(all('request' not in row for row in page['tasks'].values()))
        self.assertEqual(original, self.app.store.db.execute("SELECT task_id,payload FROM localpilot_tasks ORDER BY task_id").fetchall())
        oldest = self.app.command({'command':'task_status', 'task_id':task_id})
        self.assertEqual(oldest['task_id'], task_id)
        self.assertEqual(oldest['session_id'], first['session_id'])
        self.assertEqual(oldest['status'], 'completed')
        self.assertEqual(self.app.store.tasks.count(), 1001)
        self.assertEqual(len(self.fixture.backend.requests), 1)

    def test_cursor_pages_preserve_tied_timestamps_and_all_saved_ids(self):
        records = {f'task-{index:03}':{'timestamp':100, 'phase':'submitted',
            'transport':{'provider_kind':'cloud', 'mode':'reasoning'},
            'result':{'task_id':f'task-{index:03}', 'session_id':f'session-{index:03}', 'status':'completed'}}
            for index in range(73)}
        for task_id, record in records.items():
            self.app.store.tasks.put(task_id, record)
        seen, cursor = [], None
        while True:
            page = self.app.command({'command':'escalation_status', 'limit':17, 'before':cursor})
            snapshot = self.app.command({'command':'ui_snapshot', 'task_limit':17, 'task_before':cursor})
            self.assertEqual(snapshot['escalation'], page)
            self.assertEqual(snapshot['runtime']['escalation_tasks'], page['tasks'])
            self.assertEqual(page['total'], 73)
            self.assertLessEqual(len(page['tasks']), 17)
            for task_id, row in page['tasks'].items():
                self.assertEqual(row['task_id'], task_id)
                self.assertEqual(row['last_status']['session_id'], records[task_id]['result']['session_id'])
                self.assertEqual(row['transport']['provider_kind'], 'cloud')
            seen.extend(page['tasks'])
            cursor = page['next_before']
            if cursor is None:
                break
        self.assertEqual(seen, sorted(records, reverse=True))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual({task_id:self.app.store.tasks.get(task_id) for task_id in records}, records)

    def test_history_arguments_are_validated_at_command_entry(self):
        for limit in (0, 51, True, '30'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.app.command({'command':'escalation_status', 'limit':limit})
        for before in ({}, {'timestamp':float('nan'), 'id':'task'},
                       {'timestamp':1, 'id':''}, {'timestamp':True, 'id':'task'}, []):
            with self.subTest(before=before), self.assertRaises(ValueError):
                self.app.command({'command':'ui_snapshot', 'task_before':before})

    def test_status_and_cancel_persist_each_observation_once(self):
        view = self.completed_task()
        for command in ('task_status', 'task_cancel'):
            statements = []
            self.app.store.db.set_trace_callback(statements.append)
            result = self.app.command({'command':command, 'task_id':view['task_id'], 'approved':True})
            self.app.store.db.set_trace_callback(None)
            writes = [sql for sql in statements if sql.startswith("INSERT INTO localpilot_tasks")]
            self.assertEqual(len(writes), 1, command)
            self.assertEqual(result['task_id'], view['task_id'])
            self.assertEqual(self.app.store.tasks.get(view['task_id'])['last_status']['status'], result['status'])
        self.assertEqual(len(self.fixture.backend.requests), 1)


if __name__ == '__main__':
    unittest.main()
