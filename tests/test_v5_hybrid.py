"""Provider-neutral V5 route/egress controls; scripted local models only."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent.engine_v5 import EngineV5Policy
from agent.hybrid import CloudEgressPolicy,HybridPolicy
from agent.persistence import snapshot_runtime,restore_runtime
from agent.registry import create_default_registry
from agent.session import AgentSession,SessionBudgets
from localpilot_service.backend_contract import ServiceDeepSeekNativeBackend
from tests import test_hybrid_runtime as cases


class V5HybridControls(unittest.TestCase):
    def scenario(self,name):
        case=cases.HybridRuntimeTests(name)
        def v5(*args,**kwargs):return AgentSession(*args,engine_policy=EngineV5Policy(),**kwargs)
        with patch.object(cases,'AgentSession',v5):
            case.setUp()
            try:getattr(case,name)()
            finally:case.tearDown()
    def test_local_parent_cloud_child_approval(self):self.scenario('test_local_parent_cloud_child_needs_host_not_model_approval')
    def test_cloud_parent_local_child_route(self):self.scenario('test_cloud_parent_local_child_fixed_route')
    def test_local_only_boundary(self):self.scenario('test_local_only_policy_cannot_be_relaxed_by_catalog')
    def test_private_reasoning_and_bodies_remain_withheld(self):self.scenario('test_default_egress_withholds_file_stdout_private_reasoning_and_arguments')
    def test_approval_scope_and_epoch(self):self.scenario('test_exact_cloud_egress_approval_and_restart_epoch')
    def test_switch_preserves_receipts(self):self.scenario('test_switch_preserves_receipt_call_ids_and_recomputes_target_context')
    def test_unknown_quarantine_prevents_failover(self):self.scenario('test_unknown_mutation_is_quarantined_and_cannot_failover')
    def test_parent_cannot_replay_child_effect(self):self.scenario('test_child_patch_cannot_be_replayed_by_parent_with_new_id_or_json_order')


class NativeProvenanceControls(unittest.TestCase):
    def test_native_signature_requires_persisted_same_model_and_scope_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'facts.txt').write_text('PUBLIC')
            def make():
                backends={k:ServiceDeepSeekNativeBackend(api_key='synthetic',model=m) for k,m in [('flash','deepseek-flash'),('pro','deepseek-v4-pro')]}
                session=AgentSession(create_default_registry(root),cloud_backend=backends['flash'],policy='cloud-only',thinking='high',streaming=False,
                    engine_policy=EngineV5Policy(),budgets=SessionBudgets(max_steps=8,max_token_units=600000),
                    hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',('facts.txt',))),hybrid_backends=backends,hybrid_primary='flash')
                return session
            session=make();restored=make();count=0
            def wire(backend,payload):
                nonlocal count
                count+=1
                blocks=[{'type':'thinking','thinking':'PUBLIC-REASONING','signature':'provider-signature'}]
                blocks += ([{'type':'tool_use','id':'read-public','name':'read_file','input':{'path':'facts.txt'}}] if count==1 else [{'type':'text','text':'PUBLIC'}])
                return io.BytesIO(json.dumps({'model':'deepseek-flash','content':blocks,'stop_reason':'tool_use' if count==1 else 'end_turn',
                    'usage':{'input_tokens':10,'cache_creation_input_tokens':0,'cache_read_input_tokens':0,'output_tokens':5}}).encode())
            try:
                with patch.object(ServiceDeepSeekNativeBackend,'_open',wire):session.run_turn('Read facts.txt')
                original=next(m for m in session.messages if m.tool_calls)
                view=session.hybrid.project_messages([original])[0]
                self.assertEqual(session.current_backend._assistant(view)[0]['signature'],'provider-signature')
                restore_runtime(restored,snapshot_runtime(session))
                restored_view=restored.hybrid.project_messages([original])[0]
                self.assertEqual(restored_view.native_replay,original.native_replay)
                self.assertIsNone(restored.hybrid.project_messages([original],backend_id='pro')[0].native_replay)
                tampered=deepcopy(original);tampered.reasoning_content='LOCAL-PRIVATE-CANARY'
                self.assertIsNone(restored.hybrid.project_messages([tampered])[0].native_replay)
                self.assertIsNone(restored.hybrid.project_messages([tampered])[0].reasoning_content)
            finally:session.close();restored.close()
