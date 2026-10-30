"""Fault controls over real Gateway/SQLite; scripted providers are explicit."""
import json
from pathlib import Path
import tempfile
import unittest

from agent.async_runtime import AsyncPolicy
from agent.backends import ToolCall, Message
from agent.backends import ModelInfo
from agent.finalization import FinalizationPolicy
from agent.local_http import LocalBackendError, LocalHTTPBackend
from agent.persistence import recovery_class
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.schemas import TOOL_SCHEMAS
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import StabilizationControls
from agent.tool_protocol import ToolArgumentsError, validate_arguments
from localpilot_api.service import TaskService, TaskRequest, APIError
from tests.test_runtime_api import Backend, answer, call
from tests.test_local_http_backend import MockServer, sse


def write(args=None, identity='write'):
    return answer(None, call('apply_patch',args or {'changes':[{'path':'proof.txt','operation':'create','content':'proof'}]},identity))


class ToolProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'workspace';self.root.mkdir()
        self.backend=Backend(answer('done'));self.services=[];self.points=[];self.events=[]
        self.mode='full-permission';self.async_policy=None;self.finalization=None;self.extension=None
    def tearDown(self):
        for s in self.services:
            if s.store.connection:
                s.store.close() if s.store.failed else s.suspend()
        self.temp.cleanup()
    def factory(self, cb):
        registry=create_default_registry(self.root,permission_mode=self.mode)
        if self.extension:self.extension(registry)
        return AgentSession(registry,backend=self.backend,local_backend=self.backend,policy='cloud-only',streaming=False,
            async_policy=self.async_policy,finalization_policy=self.finalization,
            event_callback=lambda e:(self.events.append(e.to_dict()),cb(e)),
            stabilization=StabilizationControls(stagnation_limit=0),retry_policy=RetryPolicy(max_attempts=1),
            budgets=SessionBudgets(max_steps=24,max_tool_calls=32,max_token_units=8000000,
                max_worker_steps=8,max_worker_tool_calls=12,max_worker_token_units=1000000))
    def service(self):
        s=TaskService({'localpilot':self.factory},persistence=self.root.parent/'runtime.db',async_policy=self.async_policy)
        s.store.fault_hook=lambda stage,point:self.points.append((stage,point))
        self.services.append(s);return s
    def task(self,s):return s.wait(s.create_task(TaskRequest('create proof.txt and verify it'))['id'])
    def reject_then_repair(self, bad):
        self.backend=Backend(write(bad,'invalid'),write(identity='fresh'),answer('proof.txt created'))
        s=self.service();t=self.task(s)
        self.assertEqual(t['status'],'completed')
        r=t['tools'][0];self.assertEqual(r['side_effect_status'],'not_completed')
        self.assertEqual(r['payload']['result']['stage'],'not_dispatched')
        self.assertTrue(r['payload']['result']['repair_allowed'])
        self.assertEqual(sum(p=='tool_intent' and st=='after_commit' for st,p in self.points),1)
        self.assertEqual(t['tools'][1]['repaired_proposals'],[r['receipt_id']])
        self.assertEqual((self.root/'proof.txt').read_text(),'proof')
        self.assertEqual(recovery_class(s.sessions[t['session_id']].runtime),'SAFE_TO_RESUME')
    def test_missing_operation_is_not_dispatched_and_repaired(self):
        self.reject_then_repair({'changes':[{'path':'proof.txt','content':'proof'}]})
    def test_top_level_operation_feedback_binds_fresh_proposal(self):
        self.reject_then_repair({'operation':'create','changes':[{'path':'proof.txt','content':'proof'}]})
    def test_wrong_type_never_reaches_gateway(self):
        self.backend=Backend(write({'changes':'bad'}),answer('failed'))
        s=self.service();t=self.task(s)
        self.assertFalse((self.root/'proof.txt').exists())
        self.assertFalse(any(p=='tool_intent' for st,p in self.points))
        self.assertIn('expected array',t['tools'][0]['payload']['error']['message'])
    def test_invalid_json_is_class_a(self):
        self.backend=Backend(answer(None,ToolCall('bad','apply_patch','{bad json')),write(identity='new'),answer('proof.txt'))
        s=self.service();t=self.task(s)
        self.assertEqual(t['tools'][0]['payload']['error']['type'],'invalid_json_arguments')
        self.assertEqual(t['tools'][0]['side_effect_status'],'not_completed')
        self.assertEqual(sum(p=='tool_intent' and st=='after_commit' for st,p in self.points),1)
    def test_unknown_tool_is_not_dispatched(self):
        self.backend=Backend(answer(None,call('invented',{},'unknown')),answer('unavailable'))
        s=self.service();t=self.task(s)
        self.assertEqual(t['tools'][0]['payload']['error']['type'],'unknown_tool')
        self.assertEqual(t['tools'][0]['payload']['result']['stage'],'not_dispatched')
        self.assertFalse(any(p=='tool_intent' for st,p in self.points))
    def test_boolean_is_not_integer(self):
        with self.assertRaises(ToolArgumentsError):validate_arguments('execute',{'argv':['ls'],'output_limit':True},TOOL_SCHEMAS)
    def test_operation_dependent_fields(self):
        for change in [{'path':'x','operation':'create'}, {'path':'x','operation':'update','old_text':''},
                       {'path':'x','operation':'delete'}, {'path':'x','operation':'delete','content':'bad','expected_sha256':'x'}]:
            with self.subTest(change=change),self.assertRaises(ToolArgumentsError):
                validate_arguments('apply_patch',{'changes':[change]},TOOL_SCHEMAS)
    def test_approval_happens_only_after_valid_parameters(self):
        self.mode='approve-mutations';self.backend=Backend(write({'changes':[{'path':'proof.txt','content':'proof'}]},'bad'),write(identity='new'),answer('proof.txt'))
        s=self.service();t=self.task(s);self.assertEqual(t['status'],'requires_approval')
        self.assertFalse((self.root/'proof.txt').exists());self.assertEqual(len(t['tools']),1)
        s.act(t['id'],'approve',t['required_action']['id']);t=s.wait(t['id'])
        self.assertEqual(t['status'],'completed');self.assertEqual(len([r for r in t['tools'] if r['payload']['ok']]),1)
    def test_duplicate_batch_ids_reject_all_before_effects(self):
        c=write().message.tool_calls[0];self.backend=Backend(answer(None,c,c),answer('bad'))
        s=self.service();t=self.task(s);self.assertNotEqual(t['status'],'completed')
        self.assertFalse((self.root/'proof.txt').exists());self.assertFalse(any(p=='tool_intent' for st,p in self.points))
    def test_same_id_returns_original_receipt_without_replay(self):
        self.backend=Backend(write(),write(),answer('proof.txt'))
        s=self.service();t=self.task(s)
        self.assertTrue(t['tools'][1]['receipt_reused'])
        self.assertEqual(sum(p=='tool_intent' and st=='after_commit' for st,p in self.points),1)
    def test_repair_loop_is_bounded_and_persists(self):
        bad={'changes':[{'path':'proof.txt','content':'proof'}]}
        self.backend=Backend(*[write(bad,str(i)) for i in range(8)],answer('wrong'))
        s=self.service();t=self.task(s);self.assertEqual(t['status'],'incomplete')
        self.assertEqual(len(t['tools']),4);self.assertFalse(t['tools'][-1]['payload']['result']['repair_allowed'])
        s.suspend();s=self.service();saved=s.task_snapshot(t['id'])
        self.assertEqual(saved['tools'],t['tools']);self.assertFalse((self.root/'proof.txt').exists())
    def test_dispatched_unknown_is_never_argument_repair(self):
        def extension(registry):
            def effect(**kwargs):
                (self.root/'effect.txt').write_text('applied');raise ToolArgumentsError(['late schema error'])
            registry._tools['apply_patch']=effect
        self.extension=extension;self.backend=Backend(write(),answer('unknown'))
        s=self.service();t=self.task(s);self.assertEqual(t['status'],'requires_human')
        self.assertEqual(t['tools'][0]['side_effect_status'],'unknown')
        s.suspend();s=self.service();t=s.task_snapshot(t['id'])
        self.assertEqual(t['recovery']['class'],'UNKNOWN_BLOCKED')
        with self.assertRaises(APIError):s.act(t['id'],'continue',t['required_action']['id'])
        self.assertEqual((self.root/'effect.txt').read_text(),'applied')
    def test_schema_repair_does_not_settle_different_content(self):
        self.backend=Backend(write({'changes':[{'path':'proof.txt','content':'different'}]},'bad'),write(identity='new'),answer('proof.txt'))
        s=self.service();t=self.task(s);self.assertEqual(t['tools'][1].get('repaired_proposals',[]),[])
    def test_gateway_denial_is_preserved(self):
        from agent.permissions import PermissionMode
        self.mode='approve-mutations';self.backend=Backend(write(),answer('denied'))
        s=self.service();t=self.task(s);s.act(t['id'],'reject',t['required_action']['id']);t=s.wait(t['id'])
        self.assertEqual(t['tools'][0]['payload']['error']['type'],'user_rejected')
        self.assertFalse((self.root/'proof.txt').exists())
    def test_length_tool_response_is_not_executed(self):
        truncated=write();truncated.finish_reason='length';self.backend=Backend(truncated,answer('fake'))
        self.finalization=FinalizationPolicy();s=self.service();t=self.task(s)
        self.assertNotEqual(t['status'],'completed');self.assertFalse((self.root/'proof.txt').exists())
        self.assertEqual(len(self.backend.requests),1)

    def children(self, different=False):
        class Children(Backend):
            is_local=True
            model_info=ModelInfo('script-35B','35B',65536)
            def health_check(self):return True
            def request(inner,messages,**kw):
                state=next((json.loads(m.content.split('\n',1)[1]) for m in messages if (m.content or '').startswith('Host working state')),None)
                task=state['original_task'] if state else next(m.content for m in messages if m.role=='user')
                count=len([m for m in messages if m.role=='tool'])
                inner.requests.append({'task':task})
                if task.startswith('CHILD'):
                    index=task[-1];path='child'+index+'.txt'
                    if count==0 and index=='0':return answer(None,call('apply_patch',{'changes':[{'path':path,'content':'wrong' if different else 'proof'}]},'invalid'))
                    if count==(1 if index=='0' else 0):return answer(None,call('apply_patch',{'changes':[{'path':path,'operation':'create','content':'proof'}]},'fresh'))
                    return answer(path+' written')
                if count==0:return answer(None,*[call('delegate',{'task':'CHILD '+str(i),'backend_preference':'local','mode':'async','read_only':False},'delegate'+str(i)) for i in range(2)])
                if count==2:return answer(None,call('wait_children',{},'wait'))
                return answer('child0.txt child1.txt')
        self.backend=Children();self.async_policy=AsyncPolicy(max_running_per_session=2,max_model_requests=2)
        base_factory=self.factory
        def factory(cb):
            runtime=base_factory(cb);runtime.routing_policy=__import__('agent.routing',fromlist=['RoutingPolicy']).RoutingPolicy.LOCAL_ONLY
            runtime.primary='local'
            return runtime
        self.factory=factory
        s=self.service();t=self.task(s)
        return t
    def test_child_repair_settles_only_compatible_proposal(self):
        t=self.children();self.assertEqual(t['status'],'completed')
        self.assertEqual([r['obligation_status'] for r in t['subagents']],['resolved','resolved'])
        self.assertEqual(sum(not r['payload']['ok'] for r in t['tools']),1)
    def test_child_changed_content_preserves_original_obligation(self):
        t=self.children(different=True);self.assertNotEqual(t['status'],'completed')
        self.assertEqual(t['subagents'][0]['obligation_status'],'unresolved')


class StreamProtocolTests(unittest.TestCase):
    def setUp(self):
        self.server=MockServer();self.local=LocalHTTPBackend(base_url=self.server.base_url,model='mock-local',size_class='35B')
    def tearDown(self):self.server.close()
    def fragment(self,arguments):
        return {'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'p','function':{'name':'apply_patch','arguments':arguments}}]}}]}
    def test_truncated_arguments_keep_raw_fragment_without_replay(self):
        body=sse(self.fragment('{"changes":[')).replace(b'data: [DONE]\n\n',b'')
        self.server.add(body,content_type='text/event-stream')
        with self.assertRaises(LocalBackendError) as caught:list(self.local.stream([Message('user','test')]))
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.response.message.tool_calls[0].arguments,'{"changes":[')
    def test_malformed_json_after_fragments_keeps_evidence(self):
        body=sse(self.fragment('{')).replace(b'data: [DONE]\n\n',b'data: {bad}\n\n')
        self.server.add(body,content_type='text/event-stream')
        with self.assertRaises(LocalBackendError) as caught:list(self.local.stream([Message('user','test')]))
        self.assertEqual(caught.exception.response.message.tool_calls[0].arguments,'{')
    def test_stream_arguments_byte_budget(self):
        self.server.add(sse(self.fragment('x'*1000)),content_type='text/event-stream')
        with self.assertRaises(LocalBackendError) as caught:list(self.local.stream([Message('user','test')],max_tokens=2))
        self.assertFalse(caught.exception.retryable);self.assertIsNotNone(caught.exception.response)
    def test_length_keeps_call_and_finish_reason(self):
        event=self.fragment('{"changes":[');event['choices'][0]['finish_reason']='length'
        self.server.add(sse(event),content_type='text/event-stream')
        response=list(self.local.stream([Message('user','test')]))[-1].response
        self.assertEqual(response.finish_reason,'length');self.assertEqual(len(response.message.tool_calls),1)
    def test_complete_json_without_done_never_dispatches_mutation(self):
        event=self.fragment(json.dumps({'changes':[{'path':'proof.txt','operation':'create','content':'proof'}]}))
        event['choices'][0]['finish_reason']='tool_calls'
        self.server.add(sse(event).replace(b'data: [DONE]\n\n',b''),content_type='text/event-stream')
        with tempfile.TemporaryDirectory() as d:
            session=AgentSession(create_default_registry(d,permission_mode='full-permission'),backend=self.local,
                policy='local-only',streaming=True,retry_policy=RetryPolicy(max_attempts=1))
            result=session.run_turn('create proof.txt')
            self.assertEqual(result.status,'error');self.assertFalse((Path(d)/'proof.txt').exists())
            self.assertFalse(session.tool_history);self.assertEqual(len(self.server.requests),1)
