"""V4.3 genuine threaded overlap, Gateway, accounting and durable boundaries."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from agent.async_runtime import AsyncPolicy
from agent.backends import BackendCapabilities, ModelInfo
from agent.persistence import PersistenceError
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import StabilizationControls
from localpilot_api.service import TaskService, TaskRequest, APIError
from tests.test_runtime_api import Backend, answer, call


class Worker:
    is_local = True
    is_loopback = True
    capabilities = BackendCapabilities(supports_tool_calling=True)
    model_info = ModelInfo('async-scripted', '35B', 131072)
    def __init__(self, delay=.06, fail=None):
        self.delay, self.fail = delay, fail
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.timeline = []
    def health_check(self): return True
    def request(self, messages, **kw):
        task = next(m.content for m in messages if m.role == 'user')
        with self.lock:
            self.active += 1; self.peak = max(self.peak, self.active)
            self.timeline.append((task,'start',time.monotonic()))
        try:
            time.sleep(self.delay)
            if task == self.fail: raise TimeoutError('controlled child timeout')
            if any(m.role == 'tool' for m in messages): return answer('Child verified '+task)
            return answer(None,call('apply_patch',{'changes':[{'operation':'create','path':task+'.txt','content':task}]},'write'))
        finally:
            with self.lock:
                self.timeline.append((task,'end',time.monotonic())); self.active -= 1


def delegates(n):
    return answer(None,*(call('delegate',{'task':f'child{i}','backend_preference':'local','read_only':False,
                                        'mode':'async'},f'spawn{i}') for i in range(n)))


class AsyncRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.workspace = self.root/'workspace'; self.workspace.mkdir()
        self.policy = AsyncPolicy(max_running_children=4,max_running_per_session=2,max_model_requests=4)
        self.worker = Worker(); self.parent = Backend(delegates(2),answer(None,call('wait_children',{},'join')),answer('Delivered children'))
        self.mode = 'full-permission'; self.services=[]
    def tearDown(self):
        for service in self.services:
            if service.store and service.store.failed: service.store.close()
            elif not service.closed: service.shutdown(timeout=10)
        self.temp.cleanup()
    def factory(self, cb):
        return AgentSession(create_default_registry(self.workspace,permission_mode=self.mode),
            cloud_backend=self.parent,local_backend=self.worker,policy='balanced',streaming=False,event_callback=cb,
            retry_policy=RetryPolicy(max_attempts=1),async_policy=self.policy,
            stabilization=StabilizationControls(False,False,'off',0),
            budgets=SessionBudgets(max_steps=100,max_tool_calls=100,max_token_units=10000000,
                max_subagents_per_turn=8,max_worker_steps=4,max_worker_token_units=262144))
    def service(self, persistent=True):
        service=TaskService({'localpilot':self.factory},async_policy=self.policy,
                            persistence=self.root/'runtime.db' if persistent else None)
        self.services.append(service);return service
    def run_task(self, s): return s.wait(s.create_task(TaskRequest('parent task'))['id'])
    def test_two_children_overlap_and_account_once(self):
        s=self.service();t=self.run_task(s)
        self.assertEqual(t['status'],'completed',t.get('error'))
        self.assertEqual(self.worker.peak,2)
        self.assertEqual(len([r for r in t['tools'] if r.get('worker_id')]),2)
        self.assertEqual(t['result']['total_steps'],7)
        runtime=s.sessions[t['session_id']].runtime
        before=runtime._attempts;runtime._sync_children();runtime._sync_children()
        self.assertEqual(runtime._attempts,before)
        self.assertTrue(all(r['collected'] for r in t['subagents']))
    def test_four_queue_limit_two(self):
        self.parent=Backend(delegates(4),answer(None,call('wait_children',{},'join')),answer('Delivered'))
        s=self.service();t=self.run_task(s)
        self.assertEqual(t['status'],'completed',t.get('error'))
        self.assertEqual(self.worker.peak,2)
        self.assertEqual(len(t['subagents']),4)
        intervals=[(r['timeline'][0]['at'],r['timeline'][-1]['at']) for r in t['subagents']]
        self.assertLess(intervals[0][0],intervals[1][1])
        self.assertGreaterEqual(intervals[2][0],min(x[1] for x in intervals[:2]))
    def test_child_failure_does_not_cancel_sibling_or_complete_parent(self):
        self.worker.fail='child0';s=self.service();t=self.run_task(s)
        self.assertEqual(t['status'],'incomplete')
        self.assertTrue((self.workspace/'child1.txt').exists())
        self.assertEqual({r['status'] for r in t['subagents']},{'error','completed'})
    def test_unknown_child_does_not_report_completed_even_without_finalization(self):
        s=self.service();sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        original=runtime._run_async_child
        def inject(worker_id,operation):
            if worker_id.endswith('.1'):
                child=runtime._children[worker_id];function=child.registry._tools['apply_patch']
                def unknown(**args):
                    value=function(**args)
                    return {'status':'unknown','changes':value.get('changes',[])}
                child.registry._tools['apply_patch']=unknown
            return original(worker_id,operation)
        runtime._run_async_child=inject
        t=s.wait(s.create_task(TaskRequest('parent task',session_id=sid))['id'])
        self.assertNotEqual(t['status'],'completed')
        self.assertEqual(t['subagents'][0]['status'],'incomplete')
        self.assertEqual(t['subagents'][1]['status'],'completed')
        self.assertTrue((self.workspace/'child0.txt').exists())
        self.assertTrue((self.workspace/'child1.txt').exists())
        self.assertTrue(any(r['side_effect_status']=='unknown' for r in t['tools']))
    def test_direct_unknown_mutation_refuses_completed_in_async_memory(self):
        self.parent=Backend(answer(None,call('apply_patch',{'changes':[{'path':'effect.txt','operation':'create','content':'proof'}]},'effect')),
                            answer('UNKNOWN; cannot confirm completion'))
        s=self.service(persistent=False);sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        function=runtime.registry._tools['apply_patch']
        def unknown(**args):
            function(**args);return {'status':'unknown'}
        runtime.registry._tools['apply_patch']=unknown
        t=s.wait(s.create_task(TaskRequest('direct mutation',session_id=sid))['id'])
        self.assertNotEqual(t['status'],'completed')
        self.assertEqual(t['tools'][0]['side_effect_status'],'unknown')
        self.assertTrue((self.workspace/'effect.txt').exists())
    def test_denied_child_does_not_report_completed_with_unfinished_calls(self):
        s=self.service();sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        runtime.registry.gateway.capabilities=replace(runtime.registry.gateway.capabilities,write=False)
        t=s.wait(s.create_task(TaskRequest('parent task',session_id=sid))['id'])
        self.assertNotEqual(t['status'],'completed')
        self.assertEqual([c['status'] for c in t['subagents']],['incomplete','incomplete'])
        self.assertTrue(all(c['obligation_status']=='unresolved' for c in t['subagents']))
        self.assertFalse(list(self.workspace.glob('*.txt')))
    def test_approval_restart_uses_original_child_identity(self):
        self.mode='approve-mutations';s=self.service();t=self.run_task(s)
        self.assertEqual(t['status'],'requires_approval')
        old=t['required_action']['id'];s.suspend();s=self.service();t=s.task_snapshot(t['id'])
        self.assertEqual(t['recovery']['class'],'REQUIRES_APPROVAL')
        with self.assertRaises(APIError):s.act(t['id'],'approve',old)
        for _ in range(2):
            s.act(t['id'],'approve',t['required_action']['id']);t=s.wait(t['id'])
        self.assertEqual(t['status'],'completed',t.get('error'))
        self.assertEqual(len([r for r in t['tools'] if r.get('worker_id')]),2)
    def test_cancel_parent_drains_and_keeps_receipts(self):
        self.worker.delay=.15;s=self.service();t=s.create_task(TaskRequest('parent task'))
        time.sleep(.05);s.cancel(t['id']);t=s.wait(t['id'])
        self.assertEqual(t['status'],'cancelled');self.assertEqual(self.worker.active,0)
        self.assertTrue(s.shutdown(timeout=2)['quiescent'])
    def test_unknown_child_effect_blocks_parent_and_restart(self):
        s=self.service();sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        original=runtime._run_async_child
        def inject(w,op):
            child=runtime._children[w];fn=child.registry._tools['apply_patch']
            def loss(**args):fn(**args);raise TimeoutError('lost mutation receipt')
            child.registry._tools['apply_patch']=loss
            original(w,op)
        runtime._run_async_child=inject
        t=s.wait(s.create_task(TaskRequest('parent task',session_id=sid))['id'])
        self.assertEqual(t['status'],'requires_human')
        self.assertEqual(t['recovery']['class'],'UNKNOWN_BLOCKED')
        count=len(list(self.workspace.glob('*.txt')));s.suspend();s=self.service();t=s.task_snapshot(t['id'])
        with self.assertRaises(APIError):s.act(t['id'],'continue',t['required_action']['id'])
        self.assertEqual(len(list(self.workspace.glob('*.txt'))),count)
    def test_disabled_async_rejected_and_default_schemas_unchanged(self):
        runtime=AgentSession(create_default_registry(self.workspace),backend=self.parent)
        self.assertFalse(any(x['function']['name']=='wait_children' for x in runtime._schemas()))
        with self.assertRaises(ValueError):runtime._delegate(call('delegate',{},'spawn'),{'task':'test','backend_preference':'local','mode':'async'})
    def test_policy_drift_refuses_recovery(self):
        s=self.service();self.run_task(s);s.suspend()
        self.policy=replace(self.policy,max_model_requests=1)
        with self.assertRaises(PersistenceError):self.service()

    def test_checkpoint_encoding_preserves_tool_type_tags_and_legacy_maps(self):
        from agent.persistence import pack, unpack
        value={'$call':{'id':'untrusted'},'nested':[{'$map':[]},{'$json':{'$tuple':[1]}}]}
        packed=pack(value);value['nested'].append('changed')
        restored=unpack(packed)
        self.assertEqual(len(restored['nested']),2)
        self.assertEqual(restored['$call'],{'id':'untrusted'})
        self.assertEqual(unpack({'$map':[['legacy',3]]}),{'legacy':3})

    def test_model_queue_limit_one(self):
        self.policy=replace(self.policy,max_model_requests=1)
        t=self.run_task(self.service())
        self.assertEqual(t['status'],'completed')
        self.assertEqual(self.worker.peak,1)

    def test_cancel_one_running_child_keeps_sibling_and_blocks_completion(self):
        self.worker.delay=.15;s=self.service();t=s.create_task(TaskRequest('parent task'))
        deadline=time.time()+3
        while not s.children(t['id']) and time.time()<deadline:time.sleep(.01)
        s.cancel_child(t['id'],'1.1');t=s.wait(t['id'])
        self.assertEqual(t['status'],'incomplete')
        self.assertTrue((self.workspace/'child1.txt').exists())
        self.assertFalse((self.workspace/'child0.txt').exists())
        self.assertEqual({r['status'] for r in t['subagents']},{'cancelled','completed'})
        with self.assertRaises(APIError):s.cancel_child(t['id'],'1.2')

    def test_owned_child_id_cannot_control_other_task(self):
        self.worker.delay=.15;s=self.service();t=s.create_task(TaskRequest('parent task'))
        with self.assertRaises(APIError):s.cancel_child(t['id'],'other-session/1.1')
        self.assertEqual(s.wait(t['id'])['status'],'completed')

    def test_scheduler_fair_round_robin_and_ram_admission(self):
        from agent.async_runtime import AsyncScheduler
        condition=threading.Condition(threading.RLock())
        policy=replace(self.policy,max_running_children=4,ram_budget_mib=64,child_reservation_mib=64)
        scheduler=AsyncScheduler(policy,condition);order=[];started=threading.Event();release=threading.Event()
        class Parent:
            def __init__(self,key):self._scheduler_owner=key;self.subagents=[{'id':str(i),'status':'queued'} for i in range(4)]
            def _run_async_child(self,w,op):
                order.append((self._scheduler_owner,w))
                if len(order)==1:started.set();release.wait(2)
        a,b=Parent('a'),Parent('b')
        scheduler.submit(a,'0','start');self.assertTrue(started.wait(2))
        for i in (1,2,3):scheduler.submit(a,str(i),'start')
        scheduler.submit(b,'0','start');release.set()
        with condition:self.assertTrue(condition.wait_for(lambda:not scheduler.queue and not any(scheduler.running.values()),3))
        scheduler.close();self.assertEqual(len(scheduler.threads),1)
        self.assertEqual(order[1],('b','0'))

    def test_completed_child_wins_cancel_before_parent_collection(self):
        s=self.service();t=self.run_task(s);runtime=s.sessions[t['session_id']].runtime
        record=runtime.subagents[0];record['status']='running'
        runtime.cancel_child(record['id'])
        self.assertNotIn('cancel_requested',record)
        record['status']='completed'

    def test_child_runtime_exception_keeps_sibling_running(self):
        s=self.service();sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        original=runtime._run_async_child
        def run(w,op):
            child=runtime._children[w]
            if w=='1.1':
                def fault(point):
                    if point=='model_start':raise RuntimeError('child runtime fault')
                child._persistence_hook=fault
            original(w,op)
        runtime._run_async_child=run
        t=s.wait(s.create_task(TaskRequest('parent task',session_id=sid))['id'])
        self.assertEqual(t['status'],'incomplete')
        self.assertTrue((self.workspace/'child1.txt').exists())
        self.assertEqual({r['status'] for r in t['subagents']},{'error','completed'})

    def test_shutdown_waits_for_scheduler_bookkeeping_after_parent_yield(self):
        s=self.service();sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        original=runtime._run_async_child
        def delayed(w,op):original(w,op);time.sleep(.2)
        runtime._run_async_child=delayed
        t=s.wait(s.create_task(TaskRequest('parent task',session_id=sid))['id'])
        self.assertEqual(t['status'],'completed')
        result=s.shutdown(timeout=3)
        self.assertTrue(result['quiescent'])
        self.assertFalse(any(s.scheduler.running.values()))

    def test_safety_judge_uses_shared_model_admission(self):
        class JudgeWorker(Worker):
            def request(inner,messages,**kwargs):
                if 'Classify risk only.' in messages[0].content:
                    with inner.lock:inner.active+=1;inner.peak=max(inner.peak,inner.active)
                    time.sleep(.06)
                    with inner.lock:inner.active-=1
                    return answer(json.dumps({'risk_level':'LOW','reason':'known isolated fixture','potential_impact':'one file','recommended_action':'allow'}))
                return super().request(messages,**kwargs)
        self.worker=JudgeWorker();self.mode='local-judge-permissive'
        self.policy=replace(self.policy,max_model_requests=1)
        t=self.run_task(self.service())
        self.assertEqual(t['status'],'completed',t.get('error'))
        self.assertEqual(self.worker.peak,1)
        self.assertEqual(sum(r['judge_calls'] for r in t['subagents']),2)
        self.assertTrue(all(r['judge_provider_usage']=='UNKNOWN' for r in t['subagents']))

    def test_complete_buffered_usage_survives_cancel_before_acceptance(self):
        session=self.factory(None)
        class StopBackend(Backend):
            def request(inner,*args,**kw):
                r=super().request(*args,**kw);session.request_cancel();return r
        session.cloud_backend=StopBackend(answer('provider complete'))
        result=session.run_turn('parent cancelled at response boundary')
        self.assertEqual(result.status,'cancelled')
        self.assertEqual(len(result.model_calls),1)
        self.assertEqual(result.model_calls[0].input_tokens,7)
        session.close()

    def test_complete_stream_usage_survives_cancel_before_acceptance(self):
        from agent.backends import BackendChunk
        session=self.factory(None);session.streaming=True
        class StopStream(Backend):
            capabilities=BackendCapabilities(supports_tool_calling=True,supports_streaming=True)
            def stream(inner,*args,**kwargs):
                session.request_cancel()
                yield BackendChunk('response',response=answer('complete stream'))
        session.cloud_backend=StopStream()
        result=session.run_turn('parent cancelled at complete stream boundary')
        self.assertEqual(result.status,'cancelled')
        self.assertEqual(len(result.model_calls),1)
        self.assertEqual(result.model_calls[0].output_tokens,3)
        session.close()

    def test_live_unknown_mutation_is_not_dispatched_again_under_new_id(self):
        s=self.service();sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        before=runtime._run_async_child;invocations=[]
        def inject(w,op):
            child=runtime._children[w]
            if w=='1.1':
                fn=child.registry._tools['apply_patch']
                def unknown(**args):
                    invocations.append(args);fn(**args);raise TimeoutError('effect receipt lost')
                child.registry._tools['apply_patch']=unknown
                child.local_backend=Backend(answer(None,call('apply_patch',{'changes':[{'operation':'create','path':'uncertain.txt','content':'proof'}]},'a')),
                    answer(None,call('apply_patch',{'changes':[{'operation':'create','path':'uncertain.txt','content':'proof'}]},'b')),answer('failed'))
                child.local_backend.is_local=True;child._eligible=lambda:True
            before(w,op)
        runtime._run_async_child=inject
        t=s.wait(s.create_task(TaskRequest('parent task',session_id=sid))['id'])
        self.assertEqual(len(invocations),1)
        self.assertEqual(t['status'],'requires_human')
        self.assertTrue(any(r['payload'].get('error',{}).get('type')=='unknown_effect_quarantined' for r in t['tools']))
        self.assertTrue((self.workspace/'child1.txt').exists())

    def test_unchanged_child_sync_preserves_finalization_source_fence(self):
        from agent.finalization import FinalizationPolicy
        from agent.stabilization import HostVerification
        from agent.persistence import snapshot_runtime,restore_runtime
        factory=self.factory
        def qualified(cb):
            runtime=factory(cb);runtime.finalization_policy=FinalizationPolicy()
            runtime.completion_check=lambda root,p:HostVerification('passed','known fixture',{},True,True,True)
            return runtime
        self.factory=qualified
        s=self.service();t=self.run_task(s);self.assertEqual(t['status'],'completed')
        runtime=s.sessions[t['session_id']].runtime
        self.assertIsNotNone(runtime._delivery_view)
        runtime._sync_children();self.assertIsNotNone(runtime._delivery_view)
        data=snapshot_runtime(runtime)
        data['history'][0]['payload']['unexpected']='tampered'
        with self.assertRaises(PersistenceError):restore_runtime(qualified(None),data)

    def test_semantic_unknown_mutation_blocks_completion_without_sqlite(self):
        s=self.service(persistent=False);sid=s.create_session()['id'];runtime=s.sessions[sid].runtime
        original=runtime._run_async_child
        def run(w,op):
            if w=='1.1':
                child=runtime._children[w];fn=child.registry._tools['apply_patch']
                def uncertain(**args):return {**fn(**args),'status':'UNKNOWN'}
                child.registry._tools['apply_patch']=uncertain
            original(w,op)
        runtime._run_async_child=run
        t=s.wait(s.create_task(TaskRequest('parent task',session_id=sid))['id'])
        self.assertEqual(t['status'],'incomplete')
        self.assertTrue(any(r['side_effect_status']=='unknown' for r in t['tools']))
        self.assertTrue((self.workspace/'child1.txt').exists())

    def test_mixed_sync_async_delegate_respects_shared_model_queue(self):
        self.policy=replace(self.policy,max_model_requests=1)
        self.parent=Backend(answer(None,call('delegate',{'task':'child0','backend_preference':'local','read_only':False,'mode':'async'},'a'),
            call('delegate',{'task':'child1','backend_preference':'local','read_only':False,'mode':'sync'},'b')),answer('Delivered'))
        t=self.run_task(self.service())
        self.assertEqual(t['status'],'completed',t.get('error'))
        self.assertEqual(self.worker.peak,1)
        self.assertEqual(len(list(self.workspace.glob('*.txt'))),2)
