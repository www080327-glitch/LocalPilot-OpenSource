"""V4.1 controls: execution evidence and delivery are independent contracts."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import threading
import io

from agent.finalization import FinalizationPolicy, ledger_projection
from agent.persistence import snapshot_runtime, restore_runtime, configuration
from agent.registry import create_default_registry
from agent.permissions import ToolRiskMetadata
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import HostVerification, StabilizationControls, snapshot_units
from localpilot_api.service import TaskService, TaskRequest, APIError
from tests.test_runtime_api import Backend, answer, call


def length(text='partial'):
    r = answer(text); r.finish_reason = 'length'; return r


class FinalizationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name); self.workspace = self.root/'workspace'; self.workspace.mkdir()
        self.backend = Backend(answer('done'))
        self.policy = FinalizationPolicy()
        self.budgets = SessionBudgets(max_steps=12, max_token_units=1048576, max_output_tokens=1024)
        self.services = []

    def tearDown(self):
        for s in self.services:
            if s.store.connection: s.shutdown()
        self.temp.cleanup()

    def check(self, root, evidence):
        path = root/'one.txt'
        ok = path.exists() and path.read_text() == 'proof'
        return HostVerification('passed' if ok else 'failed', 'exact fixture one.txt',
            {'one.txt': hashlib.sha256(path.read_bytes()).hexdigest()} if path.exists() else {}, ok, ok, ok)

    def factory(self, cb=None, *, trusted=True):
        return AgentSession(create_default_registry(self.workspace, permission_mode='full-permission'),
            backend=self.backend, policy='cloud-only', streaming=False, event_callback=cb,
            budgets=self.budgets, retry_policy=RetryPolicy(max_attempts=1),
            stabilization=StabilizationControls(stagnation_limit=0), finalization_policy=self.policy,
            completion_check=self.check if trusted else None,
            verification_callback=(lambda root, result: self.check(root, result)) if trusted else None)

    def service(self):
        s = TaskService({'localpilot': self.factory}, persistence=self.root/'runtime.db'); self.services.append(s); return s

    def create_response(self):
        return answer(None, call('apply_patch', {'changes':[{'operation':'create','path':'one.txt','content':'proof'}]}, 'write'))

    def test_natural_length_recovers_same_turn_with_no_tools_or_replay(self):
        self.backend = Backend(self.create_response(), length(), answer('one.txt has proof; host check separate'))
        s = self.factory(); result = s.run_turn('Create one.txt with proof then deliver.')
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.completion['execution'], 'completed')
        self.assertEqual(result.completion['delivery'], 'delivered')
        self.assertEqual(result.completion['attempts'], 2)
        self.assertEqual([h['kind'] for h in result.completion['history']], ['length','delivered'])
        self.assertIsNone(self.backend.requests[-1]['tools'])
        self.assertEqual(len(s.tool_history), 1)
        self.assertEqual(s.turn_id, 1)
        self.assertIn('length', [c.finish_reason for c in result.model_calls])
        self.assertEqual(result.verification_status, 'passed')

    def test_terminal_delivery_failure_retains_verified_execution_and_original_failure(self):
        self.backend = Backend(self.create_response(), length(), TimeoutError('final timeout'))
        result = self.factory().run_turn('Create one.txt then deliver')
        self.assertEqual(result.status, 'error')
        self.assertEqual(result.completion['execution'], 'completed')
        self.assertEqual(result.completion['delivery'], 'failed')
        self.assertEqual(result.verification_status, 'not_run')
        self.assertEqual([h['kind'] for h in result.completion['history']], ['length','TimeoutError'])
        self.assertEqual(result.completion['attempts'], 2)
        self.assertEqual(len(self.backend.requests), 3)

    def test_no_host_checker_does_not_claim_execution_or_engineering_success(self):
        self.backend = Backend(self.create_response(), length(), answer('summary'))
        result = self.factory(trusted=False).run_turn('Create one.txt then deliver')
        self.assertEqual(result.completion['execution'], 'settled')
        self.assertEqual(result.completion['delivery'], 'delivered')
        self.assertEqual(result.deliverable_status, 'incomplete')
        self.assertEqual(result.verification_status, 'not_run')
        self.assertNotEqual(result.engineering_status, 'passed')

    def test_unknown_observation_never_becomes_completed(self):
        self.backend = Backend(self.create_response(), answer('Claimed success'))
        s = self.factory()
        # This fixture represents a host-declared read-only observation. Unknown
        # permission metadata is independently covered by the product safety tests.
        s.registry.register('uncertain', lambda workspace_root: {'status':'unknown'}, metadata=ToolRiskMetadata(read_only=True,mutating=False), schema={'type':'function','function':{'name':'uncertain','parameters':{'type':'object','properties':{}}}})
        self.backend.steps.insert(1, answer(None, call('uncertain', {}, 'unknown')))
        result = s.run_turn('Create and verify one.txt')
        self.assertEqual(result.status, 'incomplete')
        self.assertEqual(result.completion['execution'], 'unknown_blocked')
        self.assertEqual(result.completion['obligations']['unknown_receipts'], 1)
        self.assertNotEqual(result.verification_status, 'passed')

    def test_active_goal_obligation_survives_compaction_and_refuses_false_final(self):
        self.backend = Backend(answer(None, call('manage_goal', {'action':'create','description':'unfinished verification'}, 'goal')),
            self.create_response(), length(), answer('Claimed success'))
        s = self.factory(); result = s.run_turn('Create and verify fixture')
        self.assertEqual(result.completion['obligations']['unfinished_goals'], 1)
        self.assertEqual(result.completion['execution'], 'incomplete')
        self.assertEqual(result.status, 'incomplete')
        self.assertIn('unfinished_goals', self.backend.requests[-1]['messages'][-1].content)

    def test_checkpoint_rebuild_preserves_all_receipts_beyond_working_eviction(self):
        self.backend = Backend(self.create_response(), length(), answer('summary'))
        s = self.factory(); s.run_turn('fixture')
        for i in range(80):
            s._record_call(call('read_file', {'path':'one.txt'}, f'read-{i}'), {'ok':True,'result':f'fact-{i}'})
        s._prepare_delivery()  # Rebuild projection after constructing this ledger fixture.
        projection = ledger_projection(s)
        restored = self.factory(); restore_runtime(restored, snapshot_runtime(s))
        self.assertEqual(ledger_projection(restored), projection)
        self.assertEqual(projection['receipt_count'], 81)
        self.assertEqual(len(restored.working.evidence), 32)
        self.assertEqual(len(projection['stages']), 5)
        self.assertEqual(snapshot_units(restored._working_snapshot()) <= 8192, True)

    def test_repeat_finalize_returns_original_snapshot_after_new_session_turn(self):
        self.backend = Backend(self.create_response(), length(), answer('summary'), answer('another turn'))
        service = self.service(); task = service.wait(service.create_task(TaskRequest('fixture'))['id'])
        self.assertEqual(task['status'], 'completed')
        before = len(self.backend.requests)
        self.assertEqual(service.finalize(task['id']), task)
        self.assertEqual(service.finalize(task['id']), task)
        service.wait(service.create_task(TaskRequest('next', session_id=task['session_id']))['id'])
        self.assertEqual(service.finalize(task['id']), task)
        self.assertEqual(len(self.backend.requests), before+1)

    def test_recovery_never_ignores_client_output_cap_or_step_budget(self):
        self.budgets = replace(self.budgets, max_output_tokens=16, max_steps=3)
        self.backend = Backend(self.create_response(), length(''), length(''))
        result = self.factory().run_turn('fixture')
        self.assertEqual(result.status, 'error')
        self.assertEqual(result.completion['execution'], 'completed')
        self.assertEqual(result.completion['delivery'], 'failed')
        self.assertTrue(all(r['max_tokens'] <= 16 for r in self.backend.requests))
        self.assertLessEqual(result.runtime_metrics['model_attempts'], 3)

    def test_stale_execution_attestation_cannot_survive_final_delivery(self):
        def alter(messages):
            (self.workspace/'one.txt').write_text('changed')
            return answer('summary')
        self.backend = Backend(self.create_response(), length(), alter)
        result = self.factory().run_turn('fixture')
        self.assertEqual(result.status, 'incomplete')
        self.assertEqual(result.completion['execution'], 'incomplete')
        self.assertNotEqual(result.engineering_status, 'passed')

    def test_adapter_incomplete_tools_cannot_trigger_execution_recovery(self):
        incomplete = self.create_response(); incomplete.finish_reason = 'length'
        self.backend = Backend(incomplete, answer('should not run'))
        result = self.factory().run_turn('fixture')
        self.assertEqual(result.status, 'error')
        self.assertFalse((self.workspace/'one.txt').exists())
        self.assertEqual(len(self.backend.requests), 1)

    def test_final_only_tools_are_rejected_without_mutation(self):
        self.backend = Backend(self.create_response(), length(),
            answer(None, call('apply_patch', {'changes':[{'path':'extra.txt','operation':'create','content':'bad'}]}, 'extra')))
        result = self.factory().run_turn('fixture')
        self.assertEqual(result.status, 'incomplete')
        self.assertFalse((self.workspace/'extra.txt').exists())

    def test_default_policy_preserves_single_attempt_failure(self):
        self.policy = None
        self.backend = Backend(self.create_response(), length(), answer('never'))
        result = self.factory().run_turn('fixture')
        self.assertEqual(result.status, 'error')
        self.assertIsNone(result.completion)
        self.assertEqual(len(self.backend.requests), 2)

    def test_child_approval_checkpoint_merge_then_parent_delivery_recovery(self):
        child = Backend(self.create_response(), answer(None, call('read_file', {'path':'one.txt'}, 'child-read')), answer('child evidence'))
        self.backend = Backend(answer(None, call('delegate',{'task':'Create one.txt with proof then read it',
            'read_only':False,'backend_preference':'cloud','tier':'LIGHT'}, 'delegate')), length(), answer('parent summary'))
        self.budgets = replace(self.budgets,max_worker_steps=4,max_worker_token_units=262144)
        def factory(cb):
            s = self.factory(cb); s.permission_mode = 'approve-mutations'; s.registry.gateway.mode = s.permission_mode
            s.cloud_worker_backends['LIGHT'] = child; return s
        service = TaskService({'localpilot':factory},persistence=self.root/'child.db'); self.services.append(service)
        t = service.wait(service.create_task(TaskRequest('delegate fixture'))['id'])
        service.act(t['id'],'approve',t['required_action']['id']); t = service.wait(t['id'])
        self.assertEqual(t['status'],'requires_approval')
        service.suspend()
        service = TaskService({'localpilot':factory},persistence=self.root/'child.db'); self.services.append(service)
        t = service.task_snapshot(t['id']); service.act(t['id'],'approve',t['required_action']['id']); t = service.wait(t['id'])
        self.assertEqual(t['status'],'completed')
        self.assertEqual(t['completion']['execution'],'completed')
        worker_receipts = [r for r in t['tools'] if r.get('worker_id')]
        self.assertEqual(len(worker_receipts),2)
        self.assertEqual(len({r['receipt_id'] for r in worker_receipts}),2)
        self.assertEqual(len(t['subagents']),1)
        self.assertEqual(t['completion']['obligations']['unfinished_workers'],0)

    def test_http_finalize_is_host_only_and_idempotent(self):
        from localpilot_api.server import APIServer
        from localpilot_api.client import Client
        self.backend = Backend(self.create_response(), length(), answer('summary'))
        s = self.service(); server = APIServer(('127.0.0.1',0),s,api_key='fixture',control_token='host')
        thread = threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        client = Client(url,api_key='fixture',control_token='host')
        try:
            t = s.wait(s.create_task(TaskRequest('fixture'))['id']); endpoint=f"/localpilot/v1/tasks/{t['id']}/finalize"
            with self.assertRaises(Exception): client.request(endpoint,{})
            before=len(self.backend.requests)
            self.assertEqual(client.request(endpoint,{},control=True),t)
            self.assertEqual(client.request(endpoint,{},control=True),t)
            self.assertEqual(len(self.backend.requests),before)
        finally:
            server.shutdown();server.server_close();thread.join(2)

    def test_concurrent_finalization_keeps_session_ledger_identity(self):
        barrier = threading.Barrier(2)
        backends = []
        def factory(cb):
            def fail(messages):
                barrier.wait(3); return length()
            b=Backend(answer(None,call('read_file',{'path':'seed.txt'},'read')),fail,answer('read-only summary'))
            backends.append(b)
            return AgentSession(create_default_registry(self.workspace),backend=b,policy='cloud-only',streaming=False,
                event_callback=cb,budgets=self.budgets,finalization_policy=self.policy,retry_policy=RetryPolicy(max_attempts=1))
        (self.workspace/'seed.txt').write_text('evidence')
        s=TaskService({'localpilot':factory},persistence=self.root/'concurrent.db');self.services.append(s)
        tasks=[s.create_task(TaskRequest('read-only fixture')) for _ in range(2)]
        finals=[s.wait(t['id']) for t in tasks]
        self.assertTrue(all(t['completion']['delivery']=='delivered' for t in finals))
        self.assertNotEqual(finals[0]['session_id'],finals[1]['session_id'])
        self.assertTrue(all(t['completion']['attempts']==2 and len(t['tools'])==1 for t in finals))
        self.assertTrue(all(len(b.requests)==3 and b.requests[-1]['tools'] is None for b in backends))

    def test_sanitized_provider_usage_fixture_retains_length_accounting_without_network(self):
        from agent.deepseek import DeepSeekBackend, DeepSeekAPIError
        archive = Path(__file__).resolve().parent/'fixtures/provider_length_usage.json'
        fixture=json.loads(archive.read_text())
        self.assertEqual(fixture['fixture_kind'],'sanitized_historical_usage_projection_with_synthetic_text')
        records=fixture['responses']
        backend = DeepSeekBackend(api_key='offline-placeholder')
        raw = [records[0],records[1]]
        requests=[]
        def open_fixture(payload):
            requests.append(payload); return io.BytesIO(json.dumps(raw.pop(0)).encode())
        backend._open = open_fixture
        direct_raw = records[0]
        backend._open = lambda payload: io.BytesIO(json.dumps(direct_raw).encode())
        with self.assertRaises(DeepSeekAPIError) as raised:
            backend.request([])
        self.assertEqual(raised.exception.response.finish_reason,'length')
        self.assertEqual(raised.exception.response.usage['completion_tokens'],1024)
        backend._open = open_fixture; self.backend=backend
        result=self.factory(trusted=False).run_turn('Summarize archived evidence conservatively')
        self.assertEqual(result.completion['history'][0]['provider_usage']['completion_tokens'],1024)
        self.assertEqual(result.model_calls[0].finish_reason,'length')
        self.assertEqual(result.model_calls[0].output_tokens,1024)
        self.assertIsNone(requests[-1].get('tools'))
        self.assertEqual(result.completion['delivery'],'delivered')

    def test_host_deadline_during_finalization_does_not_retry(self):
        started=threading.Event();release=threading.Event()
        def pending(messages):
            started.set();release.wait(3);return answer('too late')
        self.backend=Backend(self.create_response(),length(),pending,answer('must not retry'))
        service=self.service();t=service.create_task(TaskRequest('fixture'))
        self.assertTrue(started.wait(3));service.cancel(t['id'],'timed_out');release.set();t=service.wait(t['id'])
        self.assertEqual(t['status'],'timed_out')
        self.assertEqual(t['completion']['execution'],'completed')
        self.assertEqual(len(self.backend.requests),3)
        self.assertEqual((self.workspace/'one.txt').read_text(),'proof')

    def test_context_admission_failure_cannot_loop_without_consuming_attempts(self):
        from agent.backends import ModelInfo
        self.backend=Backend(answer('never requested'))
        self.backend.model_info=ModelInfo('scripted','scripted',100)
        result=self.factory(trusted=False).run_turn('Critical task that cannot fit this context')
        self.assertEqual(result.status,'error')
        self.assertEqual(len(self.backend.requests),0)
        self.assertEqual(len(result.completion['history']),1)
        self.assertEqual(result.completion['history'][0]['kind'],'ContextTooSmall')

    def test_permanent_api_failure_is_preserved_without_recovery_retry(self):
        from agent.deepseek import DeepSeekAPIError
        self.backend=Backend(self.create_response(),length(),DeepSeekAPIError('permanent auth failure',status_code=401),answer('never'))
        result=self.factory().run_turn('fixture')
        self.assertEqual(result.status,'error')
        self.assertEqual(len(self.backend.requests),3)
        self.assertEqual(result.completion['execution'],'completed')
        self.assertEqual(result.completion['history'][-1]['kind'],'DeepSeekAPIError')

    def test_native_causal_verification_obligation_is_not_hidden_by_host_readiness(self):
        # Ledger fixture only: no AX call, helper or device action.
        s=self.factory(); s.working.start('fixture'); s.turn_id=1
        s._completion={'execution':'running','delivery':'not_started','attempts':0,'history':[],'readiness':None}
        (self.workspace/'one.txt').write_text('proof')
        s._record_call(call('set_value',{'app':'com.fixture','postcondition':{'kind':'value_equals'},'value':'proof'},'native'),
            {'ok':True,'result':{'status':'ok','action_sent':True,'verified':False,'verification_attempted':True}})
        projection=ledger_projection(s)
        self.assertEqual(projection['obligations']['computer_obligations'],1)
        result=s._finish('Claimed completion')
        self.assertEqual(result.completion['execution'],'incomplete')
        self.assertNotEqual(result.status,'completed')
        self.assertNotEqual(result.verification_status,'passed')

    def test_checkpoint_delivery_projection_must_match_canonical_ledger(self):
        from agent.persistence import pack, unpack, PersistenceError
        self.backend=Backend(self.create_response(),length(),answer('summary'))
        s=self.factory();s.run_turn('fixture');saved=snapshot_runtime(s)
        delivery=unpack(saved['delivery']);delivery['view']['ledger_sha256']='wrong source identity'
        saved['delivery']=pack(delivery)
        with self.assertRaises(PersistenceError):restore_runtime(self.factory(),saved)

    def test_unversioned_read_remains_unknown_despite_matching_payload_and_host_gate(self):
        self.backend=Backend(self.create_response(),answer('Claimed success'))
        s=self.factory()
        # Same name with a host extension function lacks standard cache/version
        # qualification. Its matching content must not repair UNKNOWN evidence.
        s.registry._tools['read_file']=lambda workspace_root,path: (workspace_root/path).read_text()
        self.backend.steps.insert(1,answer(None,call('read_file',{'path':'one.txt'},'unversioned')))
        result=s.run_turn('Create and read exact fixture')
        self.assertEqual(result.status,'incomplete')
        self.assertEqual(result.completion['execution'],'unknown_blocked')
        self.assertEqual(result.completion['obligations']['unknown_receipts'],1)
        self.assertNotEqual(result.verification_status,'passed')

    def test_crashed_request_unknown_output_is_charged_once_on_restore(self):
        from agent.session import SessionState
        self.backend=Backend(length(),answer('summary'))
        s=self.factory(trusted=False);s.run_turn('fixture')
        s.state=SessionState.FINALIZING;s._durable_phase='model_inflight'
        s._completion.update(attempts=1,history=[],delivery='pending')
        s._request_output_tokens=128
        before=s._token_units;failures=s._failed_attempts
        restored=self.factory(trusted=False);restore_runtime(restored,snapshot_runtime(s))
        self.assertEqual(restored._token_units,before+128*16)
        self.assertEqual(restored._failed_attempts,failures+1)
        again=self.factory(trusted=False);restore_runtime(again,snapshot_runtime(restored))
        self.assertEqual(again._token_units,restored._token_units)
        self.assertEqual(again._durable_interrupted_models,1)

    def test_interrupted_child_output_remains_in_parent_accounting(self):
        from agent.persistence import unpack
        self.budgets=replace(self.budgets,max_worker_steps=4,max_worker_token_units=262144)
        (self.workspace/'one.txt').write_text('proof')
        child=Backend(answer(None,call('read_file',{'path':'one.txt'},'child-read')),answer('child evidence'))
        self.backend=Backend(answer(None,call('delegate',{'task':'Read one.txt and summarize','backend_preference':'cloud',
            'tier':'LIGHT','read_only':True},'delegate')),answer('parent summary'))
        root=self.factory(trusted=False);root.cloud_worker_backends['LIGHT']=child
        saved=[]
        def checkpoint(point):
            if point=='model_start' and root._children:
                worker=next(iter(root._children.values()))
                if worker._durable_phase=='model_inflight':saved.append(snapshot_runtime(root))
        root._persistence_hook=checkpoint
        self.assertEqual(root.run_turn('delegate fixture').status,'approval_required');root.approve()
        snap=saved[0];worker_id=next(iter(snap['children']))
        child_before=unpack(snap['children'][worker_id]['fields'])['_token_units']
        parent_before=unpack(snap['fields'])['_token_units']
        restored=self.factory(trusted=False);restored.cloud_worker_backends['LIGHT']=child;restore_runtime(restored,snap)
        allowance=snap['children'][worker_id]['budgets']['max_output_tokens']*16
        self.assertEqual(restored._children[worker_id]._token_units,child_before+allowance)
        restored._sync_children()
        self.assertEqual(restored._token_units,parent_before+child_before+allowance)
        counted=restored._token_units;restored._sync_children();self.assertEqual(restored._token_units,counted)


if __name__ == '__main__': unittest.main()
