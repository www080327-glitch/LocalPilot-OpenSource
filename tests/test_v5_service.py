"""Actual public API/Gateway/SQLite with scripted Messages wire bytes."""
import io
import json
import unittest
from unittest.mock import patch
from agent.backends import Message
from agent.engine_v5 import EngineV5Policy
from agent.registry import create_default_registry
from agent.session import AgentSession
from agent.retry import RetryPolicy
from localpilot_service.backend_contract import ServiceDeepSeekNativeBackend
from tests import test_agent_service as cases


class ScriptedNative(ServiceDeepSeekNativeBackend):
    def __init__(self,script):
        self.script=script;super().__init__(api_key='scripted-never-transmitted')
    def _open(self,payload):
        messages=[]
        for m in payload['messages']:
            texts=[b.get('text','') for b in m['content'] if b['type']=='text']
            messages.extend(Message(m['role'],text) for text in texts)
        reply=self.script.request(messages,tools=payload.get('tools'),max_tokens=payload['max_tokens'])
        blocks=[]
        if reply.message.content:blocks.append({'type':'text','text':reply.message.content})
        blocks.extend({'type':'tool_use','id':c.id,'name':c.name,'input':json.loads(c.arguments)} for c in reply.message.tool_calls)
        events=[{'type':'message_start','message':{'model':'deepseek-flash','usage':{'input_tokens':7,'cache_creation_input_tokens':0,'cache_read_input_tokens':0}}}]
        for i,b in enumerate(blocks):events.extend([{'type':'content_block_start','index':i,'content_block':b},{'type':'content_block_stop','index':i}])
        events.extend([{'type':'message_delta','delta':{'stop_reason':'tool_use' if reply.message.tool_calls else 'end_turn'},'usage':{'output_tokens':3}},{'type':'message_stop'}])
        return io.BytesIO(''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode())


def factory(case,callback):
    return AgentSession(create_default_registry(case.workspace,permission_mode='approve-mutations'),backend=ScriptedNative(case.backend),
        policy='cloud-only',event_callback=callback,verification_callback=case.verifier,
        engine_policy=EngineV5Policy(),retry_policy=RetryPolicy(max_attempts=1))


class V5ServiceScenarios(unittest.TestCase):
    def scenario(self,name):
        case=cases.AgentServiceTests(name)
        with patch.object(cases.AgentServiceTests,'factory',factory):
            case.setUp()
            try:getattr(case,name)()
            finally:case.tearDown()
    def test_approval_restart_receipts(self):self.scenario('test_approval_server_control_only_current_ticket')
    def test_unknown_restart_quarantine(self):self.scenario('test_unknown_mutation_is_quarantined_after_restart')
    def test_cancel_waiting_approval(self):self.scenario('test_cancel_waiting_approval_does_not_execute')
    def test_durable_idempotent_submit(self):self.scenario('test_restart_ownership_request_id_and_durable_idempotency')
    def test_multiturn_sse_and_facade(self):self.scenario('test_multi_turn_sse_and_openai_protocol')
    def test_failed_or_unknown_verification(self):self.scenario('test_unknown_or_failed_host_verification_never_becomes_completed')
