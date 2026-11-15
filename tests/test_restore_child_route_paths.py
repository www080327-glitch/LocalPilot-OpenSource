"""Rebase declared private paths after a real child and model switch in SQLite."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from agent.persistence import PersistenceError, SQLiteRuntimeStore, snapshot_runtime
from localpilot_api.service import TaskService
from localpilot_service.restore_migration import configured_migration
from tests import test_pa_model_switch as fixture_module
from tests.test_runtime_api import answer, call


class HistoricalChildPathTests(unittest.TestCase):
    def setUp(self):
        class Fixture(fixture_module.ModelSwitchTests):
            def factory(self, name, callback):
                runtime = super().factory(name, callback)
                private = getattr(self, 'private_root', self.root/'old-private')
                runtime._workspace_grants = SimpleNamespace(private_roots=(str(private),))
                return runtime

        self.fixture = Fixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.services = []
        self.addCleanup(self.close_services)
        self.fixture.backends['internal-a'].steps = [answer(None, call('delegate', {
            'task':'Create one marker', 'backend_preference':'local', 'read_only':False}, 'one-child')),
            answer(None, call('apply_patch', {'changes':[{'path':'marker.txt','operation':'create',
                                                         'content':'child wrote once'}]}, 'one-write')),
            answer('child completed'), answer(None, call('delegate', {
                'task':'Review the completed work', 'backend_preference':'local', 'read_only':True}, 'second-child')),
            answer('second child completed'), answer('parent completed')]
        self.sid = self.fixture.session()['id']
        task = self.fixture.submit(self.sid, 'Write one marker through a child.', 'one-task')
        self.assertEqual(task['status'],'completed')
        self.tid = task['id']
        self.fixture.switch(self.sid)
        self.before = snapshot_runtime(self.fixture.service.sessions[self.sid].runtime)
        self.payload = self.fixture.service.store.load()[0]
        self.calls = sum(len(backend.requests) for backend in self.fixture.backends.values())
        self.fixture.stop()
        self.fixture.service.suspend()
        self.fixture.private_root = self.fixture.root/'new-private'
        self.plan = {'restore_path_migration':{'version':1,'private_roots':[
            {'source':str(self.fixture.root/'old-private'),'destination':str(self.fixture.private_root)}]}}

    def close_services(self):
        for service in self.services:
            if not service.closed:
                service.suspend()

    def open(self, migration=None):
        routes = {name:lambda cb, n=name:self.fixture.factory(n,cb) for name in self.fixture.backends}
        service = TaskService(routes,persistence=self.fixture.root/'runtime.db',
                              async_policy=self.fixture.async_policy,configuration_migration=migration)
        self.services.append(service)
        return service

    def assert_unchanged_history(self, service):
        after = snapshot_runtime(service.sessions[self.sid].runtime)
        for key in ('messages','history','completed','children','subagents'):
            self.assertEqual(after[key],self.before[key],key)
        self.assertIn(self.tid,service.tasks)
        self.assertEqual((self.fixture.workspace/'marker.txt').read_text(),'child wrote once')
        self.assertEqual(sum(len(b.requests) for b in self.fixture.backends.values()),self.calls)

    def test_declared_paths_update_both_fingerprints_in_one_checkpoint_and_restart(self):
        service = self.open(configured_migration(self.plan))
        self.assert_unchanged_history(service)
        saved = service.store.load()[0]
        old = self.payload['session']['child_route_contexts']['1.1']['configuration_sha256']
        new = saved['session']['child_route_contexts']['1.1']['configuration_sha256']
        self.assertNotEqual(new,old)
        self.assertEqual(len(saved['session']['child_route_contexts']),2)
        self.assertEqual(saved['session']['child_route_contexts']['1.2']['configuration_sha256'],new)
        self.assertNotEqual(saved['configuration'],self.payload['configuration'])
        service.suspend()
        reopened = self.open()
        self.assert_unchanged_history(reopened)

    def test_undeclared_path_and_other_historical_contract_changes_still_refuse(self):
        with self.assertRaises(PersistenceError):
            self.open()
        backend = self.fixture.backends['internal-a']
        backend.model_info = replace(backend.model_info,effective_context=65536)
        with self.assertRaises(PersistenceError) as raised:
            self.open(configured_migration(self.plan))
        self.assertIn('Historical child route contract changed',str(raised.exception.__cause__))
        store = SQLiteRuntimeStore(self.fixture.root/'runtime.db')
        try:
            self.assertEqual(store.load()[0],self.payload)
        finally:
            store.close()
        self.assertEqual((self.fixture.workspace/'marker.txt').read_text(),'child wrote once')
        self.assertEqual(sum(len(b.requests) for b in self.fixture.backends.values()),self.calls)


if __name__ == '__main__':
    unittest.main()
