"""Cloud reasoning replay requires full-message, model and egress-scope evidence."""
from copy import deepcopy
from dataclasses import replace
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agent.backends import Message
from agent.hybrid import CloudEgressPolicy,HybridPolicy
from agent.persistence import snapshot_runtime,restore_runtime,PersistenceError
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_service.backend_contract import ServiceDeepSeekOptimizedBackend
from tests.test_runtime_backends import FakeResponse

class ReasoningReplayTests(unittest.TestCase):
 def make(self,root):
  backends={k:ServiceDeepSeekOptimizedBackend(api_key='fake',model=m) for k,m in [('flash','deepseek-flash'),('pro','deepseek-v4-pro')]}
  return AgentSession(create_default_registry(root,permission_mode='approve-mutations'),cloud_backend=backends['flash'],policy='cloud-only',
    streaming=False,thinking='high',hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',('facts.txt',))),hybrid_backends=backends,hybrid_primary='flash')
 def run_public(self,session):
  payloads=[]
  def wire(backend,payload):
   payloads.append(deepcopy(payload))
   first=len(payloads)==1
   message={'role':'assistant','content':None if first else 'PUBLIC-JADE','reasoning_content':'CLOUD-SYNTHETIC-REASONING' if first else 'CLOUD-FINAL-REASONING'}
   if first:message['tool_calls']=[{'id':'read-1','type':'function','function':{'name':'read_file','arguments':'{"path":"facts.txt"}'}}]
   body={'model':'deepseek-flash','usage':{'prompt_tokens':100,'completion_tokens':10},'choices':[{'message':message,'finish_reason':'tool_calls' if first else 'stop'}]}
   return FakeResponse(json.dumps(body).encode())
  with patch('agent.deepseek.DeepSeekBackend._open',wire):session.run_turn('Read public facts.txt')
  return payloads
 def test_actual_service_projection_replays_reasoning_in_tool_round(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'facts.txt').write_text('PUBLIC-JADE');s=self.make(root)
   try:
    payloads=self.run_public(s)
    assistant=next(m for m in payloads[1]['messages'] if m['role']=='assistant')
    self.assertEqual(assistant['reasoning_content'],'CLOUD-SYNTHETIC-REASONING')
    final = next(m for m in s.messages if m.content == 'PUBLIC-JADE' and m.role == 'assistant')
    self.assertEqual(s.hybrid.project_messages([final])[0].content,'PUBLIC-JADE')
   finally:s.close()
 def test_modified_local_reasoning_with_identical_visible_text_cannot_reuse_hash(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'facts.txt').write_text('PUBLIC-JADE');s=self.make(root)
   try:
    self.run_public(s);original=next(m for m in s.messages if m.reasoning_content)
    altered=deepcopy(original);altered.reasoning_content='LOCAL-PRIVATE-CANARY'
    self.assertIsNone(s.hybrid.project_messages([altered])[0].reasoning_content)
    self.assertIsNone(s.hybrid.project_messages([Message('assistant','PUBLIC-JADE',reasoning_content='UNKNOWN-CANARY')])[0].reasoning_content)
    self.assertEqual(original.reasoning_content,'CLOUD-SYNTHETIC-REASONING')
   finally:s.close()
 def test_model_and_egress_scope_changes_invalidate_replay(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'facts.txt').write_text('PUBLIC-JADE');s=self.make(root)
   try:
    self.run_public(s);m=next(m for m in s.messages if m.reasoning_content)
    self.assertIsNone(s.hybrid.project_messages([m],backend_id='pro')[0].reasoning_content)
    s.hybrid.policy=replace(s.hybrid.policy,egress=CloudEgressPolicy('CLOUD_ALLOWED',()))
    self.assertIsNone(s.hybrid.project_messages([m])[0].reasoning_content)
   finally:s.close()
 def test_persisted_provenance_restores_and_malformed_hashes_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'facts.txt').write_text('PUBLIC-JADE');s=self.make(root);other=self.make(root)
   try:
    self.run_public(s);snapshot=snapshot_runtime(s);restore_runtime(other,snapshot)
    m=next(m for m in other.messages if m.reasoning_content)
    self.assertEqual(other.hybrid.project_messages([m])[0].reasoning_content,'CLOUD-SYNTHETIC-REASONING')
    broken=deepcopy(snapshot);broken['hybrid']['state']['deepseek_reasoning_public']={'invalid':'bad'}
    with self.assertRaises(PersistenceError):restore_runtime(other,broken)
   finally:s.close();other.close()
