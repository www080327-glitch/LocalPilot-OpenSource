"""Privacy projection must not manufacture invalid historical tool schemas."""
import json
from pathlib import Path
import tempfile
import unittest
from agent.backends import Message,ToolCall
from agent.deepseek import DeepSeekBackend
from agent.registry import create_default_registry
from agent.session import AgentSession
from agent.hybrid import HybridPolicy,CloudEgressPolicy
from agent.tool_protocol import validate_arguments
from agent.async_runtime import AsyncPolicy


class HybridArgumentProjectionTests(unittest.TestCase):
    def test_root_directory_names_can_be_shared_without_file_bodies(self):
        with tempfile.TemporaryDirectory() as d:
            b = DeepSeekBackend(api_key='fixture')
            r = AgentSession(create_default_registry(d), cloud_backend=b,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', ('.',))),
                hybrid_primary='cloud', hybrid_backends={'cloud': b})
            messages = [Message('assistant', None, [ToolCall('d', 'list_directory', '{"path":"."}')]),
                Message('tool', json.dumps({'ok': True, 'result': ['marker.txt']}), tool_call_id='d'),
                Message('assistant', None, [ToolCall('f', 'read_file', '{"path":"secret.txt"}')]),
                Message('tool', json.dumps({'ok': True, 'result': 'PRIVATE_BODY'}), tool_call_id='f')]
            view = r.hybrid.project_messages(messages)
            self.assertEqual(json.loads(view[1].content)['result'], ['marker.txt'])
            self.assertTrue(json.loads(view[3].content)['body_withheld'])
            self.assertNotIn('PRIVATE_BODY', json.dumps([m.to_dict() for m in view]))

    def test_coordinator_references_remain_schema_valid_and_text_stays_withheld(self):
        with tempfile.TemporaryDirectory() as d:
            b=DeepSeekBackend(api_key='fixture')
            r=AgentSession(create_default_registry(d),cloud_backend=b,async_policy=AsyncPolicy(),
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),hybrid_primary='cloud',hybrid_backends={'cloud':b})
            calls=[ToolCall('s','child_status','{}'),ToolCall('w','wait_children','{}'),
                   ToolCall('d','delegate',json.dumps({'task':'PRIVATE_TASK_BODY','backend_preference':'cloud','backend_id':'cloud','read_only':False,'mode':'async','budget':{'steps':4,'tokens':10000}})),
                   ToolCall('m','request_model_switch',json.dumps({'target':'cloud','backend_id':'cloud','reason':'PRIVATE_REASON_BODY','task_complexity':'complex','scope':'session'}))]
            view=r.hybrid.project_messages([Message('assistant',None,calls)])
            encoded=json.dumps(view[0].to_dict())
            self.assertNotIn('PRIVATE_TASK_BODY',encoded);self.assertNotIn('PRIVATE_REASON_BODY',encoded)
            self.assertNotIn('withheld_arguments_sha256',encoded)
            self.assertEqual(json.loads(view[0].tool_calls[0].arguments),{})
            self.assertEqual(json.loads(view[0].tool_calls[1].arguments),{})
            for c in view[0].tool_calls:
                args=json.loads(c.arguments)
                # Base runtime schemas plus registered hybrid selector fields.
                from agent.runtime_tools import RUNTIME_SCHEMAS,ASYNC_SCHEMAS
                schemas=r._schemas()+RUNTIME_SCHEMAS+ASYNC_SCHEMAS
                validate_arguments(c.name,args,schemas)

    def test_metadata_keeps_reference_ids_but_never_grants_approval(self):
        with tempfile.TemporaryDirectory() as d:
            b=DeepSeekBackend(api_key='fixture')
            r=AgentSession(create_default_registry(d),cloud_backend=b,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('REQUIRES_APPROVAL')),hybrid_primary='cloud',hybrid_backends={'cloud':b})
            view=r.hybrid.project_messages([Message('assistant',None,[ToolCall('c','cancel_child','{"worker_id":"1.1"}')])])
            self.assertEqual(json.loads(view[0].tool_calls[0].arguments),{'worker_id':'1.1'})
            self.assertEqual(r.hybrid.state['grants'],[])

    def test_schema_feedback_survives_projection_without_private_body(self):
        with tempfile.TemporaryDirectory() as d:
            b=DeepSeekBackend(api_key='fixture')
            r=AgentSession(create_default_registry(d),cloud_backend=b,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),hybrid_primary='cloud',hybrid_backends={'cloud':b})
            messages=[Message('assistant',None,[ToolCall('c','child_status','{"bad_field":"PRIVATE_BAD_VALUE"}')]),
                Message('tool',json.dumps({'ok':False,'error':{'type':'schema_validation','fields':['$.bad_field: unexpected field'],'message':'PRIVATE_MESSAGE'},
                    'result':{'stage':'not_dispatched','action_sent':False,'action_may_have_applied':False,'repair_allowed':True,'repair_attempts_remaining':2}}),tool_call_id='c')]
            view=r.hybrid.project_messages(messages);reply=json.loads(view[-1].content)
            self.assertEqual(reply['error']['fields'],['$.bad_field: unexpected field'])
            self.assertIs(reply['validation']['action_sent'],False)
            self.assertNotIn('PRIVATE_BAD_VALUE',json.dumps([m.to_dict() for m in view]))
            self.assertNotIn('PRIVATE_MESSAGE',json.dumps([m.to_dict() for m in view]))

    def test_selected_file_identity_and_effect_metadata_are_available_without_bodies(self):
        with tempfile.TemporaryDirectory() as d:
            b=DeepSeekBackend(api_key='fixture')
            r=AgentSession(create_default_registry(d,file_operations=True),cloud_backend=b,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',('source.txt','target.txt'))),hybrid_primary='cloud',hybrid_backends={'cloud':b})
            before={'type':'file','device':1,'inode':2,'modified_ns':3,'size_bytes':4,'sha256':'a'*64,'content':'PRIVATE_BODY'}
            messages=[Message('assistant',None,[ToolCall('i','inspect_file','{"path":"source.txt"}')]),
                Message('tool',json.dumps({'ok':True,'result':{'path':'source.txt',**before}}),tool_call_id='i'),
                Message('assistant',None,[ToolCall('m','move_file',json.dumps({'source':'source.txt','destination':'target.txt','expected_sha256':'a'*64}))]),
                Message('tool',json.dumps({'ok':True,'result':{'status':'ok','operation':'move','source':'source.txt','destination':'target.txt','before':before,'after':before,'verification':'passed'}}),tool_call_id='m')]
            view=r.hybrid.project_messages(messages)
            self.assertEqual(json.loads(view[1].content)['result']['sha256'],'a'*64)
            self.assertEqual(json.loads(view[-1].content)['result']['destination'],'target.txt')
            self.assertNotIn('PRIVATE_BODY',json.dumps([m.to_dict() for m in view]))
            r.hybrid.policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',('source.txt',)))
            hidden=r.hybrid.project_messages(messages)
            self.assertNotIn('target.txt',hidden[-1].content)
