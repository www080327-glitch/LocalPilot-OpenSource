"""V4 recovery controls; genuine process faults live in benchmarks.persistent_runtime."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from agent.persistence import SQLiteRuntimeStore, PersistenceError, snapshot_runtime
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_api.service import TaskService, TaskRequest, APIError
from tests.test_runtime_api import Backend, answer, call
from tests.test_v2_p0_reliability import create
from tests.test_computer_runtime import MemoryAX, APP
from computer.runtime import ComputerRuntime


class PersistentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'; self.workspace.mkdir()
        self.db = self.root / 'runtime.db'
        self.backend = Backend(answer('done'))
        self.mode = 'approve-mutations'
        self.plan = False
        self.computer = False
        self.services = []
        self.budgets = SessionBudgets(max_steps=16, max_worker_steps=6,
            max_worker_token_units=262144, max_token_units=1048576)

    def tearDown(self):
        for service in self.services:
            if service.store and service.store.connection:
                if service.store.failed:
                    service.store.close()
                else:
                    service.shutdown()
        self.temp.cleanup()

    def factory(self, callback):
        return AgentSession(create_default_registry(self.workspace, permission_mode=self.mode),
            backend=self.backend, policy='cloud-only', streaming=False,
            plan_mode=self.plan, event_callback=callback, budgets=self.budgets,
            computer_runtime=ComputerRuntime(MemoryAX(), allowed_apps=[APP]) if self.computer else None,
            retry_policy=RetryPolicy(max_attempts=1))

    def service(self, **kwargs):
        service = TaskService({'localpilot': self.factory}, persistence=self.db, **kwargs)
        self.services.append(service)
        return service

    def task(self, s, text='controlled task', **kwargs):
        return s.wait(s.create_task(TaskRequest(text, **kwargs))['id'])

    def restart(self, s):
        s.suspend()
        return self.service()

    def act(self, s, t, action='approve'):
        s.act(t['id'], action, t['required_action']['id'])
        return s.wait(t['id'])

    def test_approval_survives_restart_and_old_action_is_rejected(self):
        self.backend = Backend(create('one.txt'), answer('written'))
        s = self.service(); t = self.task(s); old_id = t['required_action']['id']
        s = self.restart(s); r = s.task_snapshot(t['id'])
        self.assertEqual(r['recovery']['class'], 'REQUIRES_APPROVAL')
        self.assertNotEqual(old_id, r['required_action']['id'])
        with self.assertRaises(APIError): s.act(t['id'], 'approve', old_id)
        r = self.act(s, r)
        self.assertEqual(r['status'], 'completed')
        self.assertEqual((self.workspace/'one.txt').read_text(), 'saved')
        self.assertEqual(len(r['tools']), 1)

    def test_plan_goal_working_evidence_survive_restart(self):
        self.plan = True
        self.backend = Backend(answer(None, call('manage_goal', {'action':'create','description':'durable goal'}, 'goal')),
            answer('Create one.txt then verify its content.'), create('one.txt'), answer('done'))
        s = self.service(); t = self.task(s)
        self.assertEqual(t['status'], 'requires_approval')
        runtime = s.sessions[t['session_id']].runtime
        before = snapshot_runtime(runtime)
        s = self.restart(s); runtime = s.sessions[t['session_id']].runtime
        self.assertEqual(runtime.active_plan['text'], 'Create one.txt then verify its content.')
        self.assertEqual(runtime.goals.list()[0].description, 'durable goal')
        self.assertEqual(snapshot_runtime(runtime)['working'], before['working'])
        t = self.act(s, s.task_snapshot(t['id']))
        self.assertEqual(t['status'], 'requires_approval')
        t = self.act(s, t); self.assertEqual(t['status'], 'completed')

    def test_terminal_snapshot_stable_and_new_turn_keeps_context(self):
        self.backend = Backend(answer('first'), answer('second'))
        s = self.service(); t = self.task(s, 'remember durable pear'); saved = s.task_snapshot(t['id'])
        s = self.restart(s); self.assertEqual(s.task_snapshot(t['id']), saved)
        t2 = self.task(s, 'continue', session_id=t['session_id'])
        self.assertEqual(t2['status'], 'completed')
        self.assertIn('remember durable pear', [m.content for m in self.backend.requests[-1]['messages']])
        self.assertEqual(s.task_snapshot(t['id']), saved)

    def test_changed_permission_or_workspace_is_refused(self):
        s = self.service(); self.task(s); s.suspend(); self.mode = 'full-permission'
        with self.assertRaises(PersistenceError): self.service()
        self.mode = 'approve-mutations'; self.workspace = self.root/'other'; self.workspace.mkdir()
        with self.assertRaises(PersistenceError): self.service()

    def test_corrupt_checkpoint_hash_and_missing_journal_are_refused(self):
        for mode in ('hash', 'journal'):
            with self.subTest(mode=mode):
                self.db = self.root/(mode+'.db')
                s = self.service(); self.task(s); s.suspend()
                db = sqlite3.connect(self.db)
                if mode == 'hash': db.execute("UPDATE checkpoints SET payload='{}'")
                else: db.execute('DELETE FROM journal')
                db.commit(); db.close()
                with self.assertRaises(PersistenceError): self.service()

    def test_unknown_and_unversioned_database_are_refused(self):
        for version in (0, 99):
            self.db = self.root/(str(version)+'.db')
            db = sqlite3.connect(self.db); db.execute('CREATE TABLE alien(x)')
            db.execute('PRAGMA user_version='+str(version)); db.close()
            with self.assertRaises(PersistenceError): self.service()

    def test_owner_lock_and_symlink_are_refused(self):
        s = self.service()
        with self.assertRaises(PersistenceError): self.service()
        s.suspend(); self.db = self.root/'link.db'; self.db.symlink_to(self.root/'runtime.db')
        with self.assertRaises(PersistenceError): self.service()

    def test_failed_intent_commit_prevents_tool_dispatch_and_fences_service(self):
        self.mode = 'full-permission'; self.backend = Backend(create('forbidden.txt'), answer('bad'))
        s = self.service()
        def fail(stage, point):
            if point == 'tool_intent': raise OSError('injected disk full')
        s.store.fault_hook = fail
        t = self.task(s)
        self.assertFalse((self.workspace/'forbidden.txt').exists())
        self.assertEqual(t['status'], 'requires_human')
        self.assertTrue(s.store.failed)
        with self.assertRaises(PersistenceError): s.create_session()
        s.store.close()
        s = self.service(); t = s.task_snapshot(t['id'])
        self.assertEqual(t['recovery']['class'], 'SAFE_TO_RESUME')
        t = self.act(s, t, 'continue'); self.assertEqual(t['status'], 'completed')
        self.assertTrue((self.workspace/'forbidden.txt').exists())

    def test_mutation_exception_is_unknown_and_never_completes(self):
        self.mode = 'full-permission'; self.backend = Backend(create('uncertain.txt'), answer('done'))
        s = self.service(); sid = s.create_session()['id']; registry = s.sessions[sid].runtime.registry
        original = registry._tools['apply_patch']
        def loss(**kwargs):
            original(**kwargs); raise TimeoutError('receipt lost')
        registry._tools['apply_patch'] = loss
        t = self.task(s, session_id=sid)
        self.assertTrue((self.workspace/'uncertain.txt').exists())
        self.assertEqual(t['status'], 'requires_human')
        self.assertEqual(t['tools'][0]['side_effect_status'], 'unknown')
        s = self.restart(s); t = s.task_snapshot(t['id'])
        self.assertEqual(t['recovery']['class'], 'UNKNOWN_BLOCKED')
        for action in ('continue', 'resume', 'approve'):
            with self.assertRaises(APIError): s.act(t['id'], action, t['required_action']['id'])
        s.cancel(t['id']); self.assertEqual(s.wait(t['id'])['status'], 'cancelled')

    def test_subagent_approval_parent_ledger_and_accounting_survive(self):
        delegate = call('delegate', {'task':'write child file', 'backend_preference':'cloud','read_only':False}, 'delegate')
        self.backend = Backend(answer(None, delegate), create('child.txt'), answer('child done'), answer('parent done'))
        s = self.service(); t = self.task(s)
        # First approval authorizes a mutating worker, second its actual patch.
        t = self.act(s, t)
        self.assertEqual(t['status'], 'requires_approval')
        s = self.restart(s); t = self.act(s, s.task_snapshot(t['id']))
        self.assertEqual(t['status'], 'completed')
        self.assertEqual(len([r for r in t['tools'] if r.get('worker_id')]), 1)
        self.assertEqual(len(t['subagents']), 1)
        self.assertEqual(t['result']['total_steps'], 4)

    def test_timeout_includes_downtime_and_retires_session(self):
        self.backend = Backend(create('late.txt'))
        s = self.service(); t = self.task(s, timeout_seconds=.2); s.suspend(); time.sleep(.22)
        s = self.service(); t = s.task_snapshot(t['id'])
        self.assertEqual(t['status'], 'timed_out')
        self.assertEqual(t['recovery']['class'], 'TERMINAL')
        self.assertTrue(s.sessions[t['session_id']].closed)
        self.assertFalse((self.workspace/'late.txt').exists())

    def test_restart_requires_fresh_computer_observation(self):
        self.computer = True
        self.backend = Backend(answer(None, call('inspect_tree', {'app': APP}, 'tree')), create('file.txt'))
        s = self.service(); t = self.task(s); s = self.restart(s); t = s.task_snapshot(t['id'])
        self.assertEqual(t['recovery']['class'], 'REQUIRES_REOBSERVATION')
        self.assertEqual(t['status'], 'requires_human')
        self.assertFalse(s.sessions[t['session_id']].runtime.computer.observations)
        with self.assertRaises(APIError): self.act(s, t, 'continue')

    def test_multiple_sessions_remain_separate(self):
        self.backend = Backend(answer('one'), answer('two'))
        s = self.service(); t1 = self.task(s); t2 = self.task(s); s = self.restart(s)
        self.assertNotEqual(t1['session_id'],t2['session_id'])
        self.assertEqual(s.task_snapshot(t1['id'])['result']['text'], 'one')
        self.assertEqual(s.task_snapshot(t2['id'])['result']['text'], 'two')

    def test_before_commit_failure_rolls_back_event_and_checkpoint_together(self):
        s = self.service(); self.task(s); previous = s.store.load()
        def fail(stage, point):
            if stage == 'before_commit': raise OSError('disk full')
        s.store.fault_hook = fail
        with self.assertRaises(PersistenceError): s._checkpoint(next(iter(s.sessions)), 'failure')
        s.store.close(); store = SQLiteRuntimeStore(self.db)
        self.assertEqual(store.load(), previous); store.close()

    def test_corrupt_sqlite_header_and_database_in_workspace_are_refused(self):
        self.db.write_bytes(b'broken SQLite header')
        with self.assertRaises(PersistenceError): self.service()
        self.db = self.workspace/'runtime.db'
        s=self.service()
        with self.assertRaises(PersistenceError): s.create_session()

    def test_cancel_and_shutdown_concurrent_drain_preserves_stop_intent(self):
        entered = threading.Event(); release = threading.Event()
        def blocked(messages):
            entered.set(); release.wait(3); return create('never.txt')
        self.mode = 'full-permission'; self.backend = Backend(blocked)
        s = self.service(); t = s.create_task(TaskRequest('cancel while model in flight'))
        self.assertTrue(entered.wait(2))
        stops=[]
        a=threading.Thread(target=lambda:stops.append(s.cancel(t['id'])))
        b=threading.Thread(target=lambda:stops.append(s.shutdown(timeout=3)))
        a.start(); b.start(); release.set(); a.join(4); b.join(4)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertEqual(s.task_snapshot(t['id'])['status'],'cancelled')
        self.assertFalse((self.workspace/'never.txt').exists())
        s=self.service();self.assertEqual(s.task_snapshot(t['id'])['status'],'cancelled')

    def test_real_sqlite_disk_full_prevents_model_or_tool_dispatch(self):
        s=self.service();sid=s.create_session()['id']
        s.store.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        current=s.store.connection.execute('PRAGMA page_count').fetchone()[0]
        s.store.connection.execute('PRAGMA max_page_count='+str(current))
        runtime=s.sessions[sid].runtime
        runtime.messages.append(__import__('agent.backends',fromlist=['Message']).Message('user','large'+('x'*200000)))
        with self.assertRaises(PersistenceError):s._checkpoint(sid,'disk-full')
        self.assertTrue(s.store.failed)
        self.assertFalse(self.backend.requests)
        self.assertIsInstance(s.store.connection.execute('PRAGMA integrity_check').fetchone()[0],str)

    def test_takeover_intent_commit_failure_prevents_control_side_effect(self):
        self.computer=True;self.backend=Backend(create('pending.txt'))
        s=self.service();t=self.task(s)
        runtime=s.sessions[t['session_id']].runtime
        def fail(stage,point):
            if point=='takeover_intent':raise OSError('injected failure')
        s.store.fault_hook=fail
        with self.assertRaises(PersistenceError):s.takeover(t['id'])
        self.assertFalse(runtime.computer.pause_requested.is_set())

    def test_observer_failure_does_not_replace_direct_durability_hook(self):
        self.mode='full-permission';self.backend=Backend(create('saved.txt'),answer('done'))
        s=self.service();sid=s.create_session()['id']
        runtime=s.sessions[sid].runtime
        runtime.events.callback=lambda event:(_ for _ in ()).throw(RuntimeError('renderer gone'))
        t=self.task(s,session_id=sid)
        self.assertEqual(t['status'],'completed');s=self.restart(s)
        self.assertEqual(s.task_snapshot(t['id'])['tools'][0]['name'],'apply_patch')
        self.assertEqual(len(s.sessions[sid].runtime.tool_history),1)

    def test_changed_file_invalidates_restored_approval_fingerprint(self):
        (self.workspace/'edit.txt').write_text('old')
        self.backend=Backend(answer(None,call('apply_patch',{'changes':[{'operation':'update','path':'edit.txt','old_text':'old','new_text':'new'}]},'edit')),answer('stopped'))
        s=self.service();t=self.task(s)
        self.assertEqual(t['status'],'requires_approval')
        s=self.restart(s);(self.workspace/'edit.txt').write_text('human')
        t=self.act(s,s.task_snapshot(t['id']))
        self.assertEqual((self.workspace/'edit.txt').read_text(),'human')
        self.assertFalse(t['tools'][0]['payload']['ok'])

    def test_http_stream_disconnect_detaches_and_completion_remains_durable(self):
        from localpilot_api.server import APIServer
        from tests.test_runtime_api import StreamBackend
        from urllib.request import Request,urlopen
        backend=StreamBackend()
        def factory(cb):return AgentSession(create_default_registry(self.workspace),backend=backend,
            policy='cloud-only',streaming=True,event_callback=cb,retry_policy=RetryPolicy(max_attempts=1))
        s=TaskService({'localpilot':factory},persistence=self.db);self.services.append(s)
        server=APIServer(('127.0.0.1',0),s,api_key='test',control_token='host')
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);thread.start()
        try:
            request=Request(f'http://127.0.0.1:{server.server_port}/v1/responses',
                data=json.dumps({'input':'durable streaming','stream':True}).encode(),
                headers={'Authorization':'Bearer test','Content-Type':'application/json'})
            stream=urlopen(request,timeout=4)
            for _ in range(100):
                if b'output_text.delta' in stream.readline():break
            self.assertTrue(backend.first.wait(2));stream.close();backend.release.set()
            tid=next(iter(s.tasks));t=s.wait(tid);self.assertEqual(t['status'],'completed')
            s.suspend();s=TaskService({'localpilot':factory},persistence=self.db);self.services.append(s)
            self.assertEqual(s.task_snapshot(tid)['result']['text'],'hello 世界')
        finally:backend.release.set();server.shutdown();server.server_close();thread.join(3)

    def test_same_model_name_changed_backend_endpoint_is_refused(self):
        self.backend.base_url='https://host-a.example/models'
        s=self.service();self.task(s);s.suspend()
        self.backend.base_url='https://host-b.example/models'
        with self.assertRaises(PersistenceError):self.service()

    def test_default_memory_mode_has_no_durable_hook_or_unknown_promotion(self):
        self.mode='full-permission';(self.workspace/'exists.txt').write_text('before')
        self.backend=Backend(create('exists.txt'),answer('failed write reported'))
        s=TaskService({'localpilot':self.factory})
        try:
            t=self.task(s)
            runtime=s.sessions[t['session_id']].runtime
            self.assertIsNone(runtime._persistence_hook)
            self.assertEqual(t['tools'][0]['side_effect_status'],'not_completed')
            self.assertEqual((self.workspace/'exists.txt').read_text(),'before')
        finally:s.shutdown()

    def test_failing_mutating_extension_receipt_cannot_certify_no_effect(self):
        from agent.permissions import ToolRiskMetadata
        schema={'type':'function','function':{'name':'fault_fixture','parameters':{'type':'object','properties':{},'additionalProperties':False}}}
        self.mode='full-permission';self.backend=Backend(answer(None,call('fault_fixture',{},'effect')),answer('done'))
        base=self.factory
        def factory(cb):
            runtime=base(cb)
            def effect(workspace_root):
                (workspace_root/'external-effect.txt').write_text('applied before failing return')
                return {'status':'nonzero_exit','returncode':7}
            runtime.registry.register('fault_fixture',effect,ToolRiskMetadata(external_side_effect=True),schema=schema)
            return runtime
        self.factory=factory
        s=self.service();t=self.task(s)
        self.assertEqual(t['status'],'requires_human')
        self.assertEqual(t['tools'][0]['side_effect_status'],'unknown')
        self.assertTrue((self.workspace/'external-effect.txt').exists())
        s=self.restart(s);t=s.task_snapshot(t['id'])
        self.assertEqual(t['recovery']['class'],'UNKNOWN_BLOCKED')
        with self.assertRaises(APIError):self.act(s,t,'continue')
