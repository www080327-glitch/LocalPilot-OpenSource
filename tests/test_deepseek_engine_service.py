"""Service/Gateway/SQLite controls through the real optimized parser.

HTTP provider bytes are scripted. These controls do not measure model quality.
The established service scenarios retain their real receipts, approval tickets,
idempotency, loopback HTTP, and SQLite restart; only transport input is replaced.
"""
import json,unittest
from unittest.mock import patch
from agent.backends import Message
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession
from localpilot_service.backend_contract import ServiceDeepSeekOptimizedBackend
from tests import test_agent_service as service_cases
from tests.test_runtime_backends import FakeResponse,sse

class ScriptedWire(ServiceDeepSeekOptimizedBackend):
 def __init__(self,script):
  self.script=script
  super().__init__(api_key='scripted-key-never-transmitted')
 def _open(self,payload):
  reply=self.script.request([Message.from_dict(m) for m in payload['messages']],tools=payload.get('tools'),max_tokens=payload.get('max_tokens'))
  calls=[{**call.to_dict(),'index':i} for i,call in enumerate(reply.message.tool_calls)]
  data={'model':'scripted-provider','usage':reply.usage,'choices':[{'index':0,'delta':{
    'content':reply.message.content,'reasoning_content':reply.message.reasoning_content,**({'tool_calls':calls} if calls else {})},
    'finish_reason':'tool_calls' if calls else 'stop'}]}
  return FakeResponse(sse(data))

def factory(case,callback):
 return AgentSession(create_default_registry(case.workspace,permission_mode='approve-mutations'),backend=ScriptedWire(case.backend),
   policy='cloud-only',event_callback=callback,verification_callback=case.verifier,retry_policy=RetryPolicy(max_attempts=2,base_delay=0,jitter=0))

class OptimizedServiceScenarios(unittest.TestCase):
 def scenario(self,name):
  case=service_cases.AgentServiceTests(name)
  with patch.object(service_cases.AgentServiceTests,'factory',factory):
   case.setUp()
   try:getattr(case,name)()
   finally:case.tearDown()
 def test_approval_ticket_survives_sqlite_restart_without_mutation_replay(self):
  self.scenario('test_approval_server_control_only_current_ticket')
 def test_unknown_effect_stays_quarantined_after_sqlite_restart(self):
  self.scenario('test_unknown_mutation_is_quarantined_after_restart')
 def test_cancel_approval_never_executes(self):
  self.scenario('test_cancel_waiting_approval_does_not_execute')
 def test_durable_submit_is_idempotent_after_restart(self):
  self.scenario('test_restart_ownership_request_id_and_durable_idempotency')
 def test_multi_turn_sse_and_client_facade(self):
  self.scenario('test_multi_turn_sse_and_openai_protocol')
 def test_unknown_or_failed_verification_never_completes(self):
  self.scenario('test_unknown_or_failed_host_verification_never_becomes_completed')
