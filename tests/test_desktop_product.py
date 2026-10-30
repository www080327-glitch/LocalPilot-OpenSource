"""Real HTTP/SQLite/Gateway controls with a scripted model; not model E2E."""
import hashlib
from pathlib import Path
import unittest
from types import SimpleNamespace
from localpilot_api.service import APIError
from localpilot_service.desktop_sessions import MODES
from localpilot_service.attachments import ingest
from agent.safety import PermissionGateway,CapabilityPolicy
from agent.permissions import ToolRiskMetadata
from tests.test_agent_service import AgentServiceTests as Base

class DesktopProductTests(unittest.TestCase):
    setUp=Base.setUp;tearDown=Base.tearDown;factory=Base.factory;stop=Base.stop;denied=Base.denied;done=Base.done
    def start(self):
        BaseStart(self)
        self.server.catalog={'localpilot':{'deployment_status':'ready','capabilities':['tool_calling'],'cloud_egress':'LOCAL_ONLY'}}
    def session(self,mode='ask',profile='standard'):
        return self.operator.request('/localpilot/v1/desktop-sessions',{'client_subject':'codex','model':'localpilot','source':'balanced','options':{'permission_mode':mode,'agent_profile':profile}},key='desktop-'+mode+'-'+profile)
    def test_four_modes_persist_and_minimal_is_a_real_agent(self):
        for mode in MODES:
            s=self.session(mode,'minimal');runtime=self.service.sessions[s['id']].runtime
            self.assertEqual(runtime.permission_mode,MODES[mode]);self.assertTrue(runtime.runtime_tools)
            self.assertEqual(runtime.prompt_profile,'minimal_agent_v2')
        task=self.done(self.codex.submit('hi',session_id=s['id'],idempotency_key='minimal-agent'))
        self.assertEqual(task['desktop_options']['agent_profile'],'minimal')
        self.stop();self.service.suspend();self.start()
        restored=self.codex.status(task['id']);self.assertEqual(restored['desktop_options']['permission_mode'],'full')
        self.assertEqual(self.service.sessions[s['id']].runtime.prompt_profile,'minimal_agent_v2')
    def switch(self,s,profile,previous='standard',client=None):
        return (client or self.operator).request('/localpilot/v1/desktop-sessions/'+s['id']+'/profile',{'client_subject':'codex','agent_profile':profile,'expected_profile':previous})

    def test_profile_switch_retains_history_and_restores_without_new_session(self):
        s=self.session('safe');first=self.done(self.codex.submit('Remember the marker ORBIT.',session_id=s['id'],idempotency_key='profile-first'))
        runtime=self.service.sessions[s['id']].runtime
        history=[m.to_dict() for m in runtime.messages if m.role!='system'];tools=runtime.registry.schemas();gateway=runtime.registry.gateway
        self.switch(s,'minimal')
        self.assertEqual([m.to_dict() for m in runtime.messages if m.role!='system'],history)
        self.assertEqual(runtime.registry.schemas(),tools);self.assertIs(runtime.registry.gateway,gateway)
        self.assertEqual(runtime.permission_mode,MODES['safe'])
        self.assertEqual(self.codex.status(first['id'])['desktop_options']['agent_profile'],'standard')
        self.assertEqual(self.switch(s,'minimal')['id'],s['id'])
        self.denied(409,lambda:self.switch(s,'standard','standard'))
        self.stop();self.service.suspend();self.start()
        runtime=self.service.sessions[s['id']].runtime
        self.assertEqual(runtime.prompt_profile,'minimal_agent_v2')
        self.assertEqual([m.to_dict() for m in runtime.messages if m.role!='system'],history)
        second=self.done(self.codex.submit('Recall the marker.',session_id=s['id'],idempotency_key='profile-second'))
        self.assertEqual(second['session_id'],first['session_id'])
        self.assertEqual(second['desktop_options']['agent_profile'],'minimal')
        self.switch(s,'standard','minimal')
        self.assertEqual(self.codex.status(first['id'])['desktop_options']['agent_profile'],'standard')
        self.assertEqual(self.codex.status(second['id'])['desktop_options']['agent_profile'],'minimal')
        self.assertEqual(len(self.service.sessions),1)

    def test_profile_switch_cannot_bypass_operator_owner_or_active_approval(self):
        s=self.session()
        self.denied(403,lambda:self.switch(s,'minimal',client=self.codex))
        foreign=self.service.create_session(owner_subject='dsh',desktop_options={'permission_mode':'ask','agent_profile':'standard'})
        self.denied(403,lambda:self.switch(foreign,'minimal'))
        self.service.sessions[s['id']].active_task='blocked-approval'
        self.denied(409,lambda:self.switch(s,'minimal'))
        self.service.sessions[s['id']].active_task=None

    def test_desktop_authorization_is_idempotent_even_after_restart(self):
        first=self.session('safe');again=self.session('safe');self.assertEqual(first['id'],again['id'])
        self.stop();self.service.suspend();self.start()
        self.assertEqual(self.session('safe')['id'],first['id'])
        self.assertEqual(len(self.service.sessions),1)

    def test_only_operator_can_authorize_session_options(self):
        body={'client_subject':'codex','model':'localpilot','source':'balanced','options':{'permission_mode':'full','agent_profile':'standard'}}
        self.denied(403,lambda:self.codex.request('/localpilot/v1/desktop-sessions',body))
        self.denied(403,lambda:self.operator.request('/localpilot/v1/desktop-sessions',{**body,'client_subject':'dsh'}))
    def test_batch_ingestion_retains_identity_and_cannot_be_done_by_client(self):
        files=[]
        for i in range(30):
            p=self.root/f'input-{i}.txt';p.write_text(f'content {i}');files.append(str(p))
        body={'client_subject':'codex','model':'localpilot','paths':files}
        self.denied(403,lambda:self.codex.request('/localpilot/v1/attachments/import',body))
        result=self.operator.request('/localpilot/v1/attachments/import',body)
        self.assertEqual(len(result['files']),30);self.assertFalse(result['cloud_uploaded'])
        for i,f in enumerate(result['files']):
            self.assertEqual((self.workspace/f['workspace_path']).read_text(),f'content {i}')
            self.assertEqual(f['sha256'],hashlib.sha256(f'content {i}'.encode()).hexdigest())
        self.assertTrue((self.workspace/result['manifest']).is_file())
        canonical=self.root/'attachment-records'/(result['batch_id']+'.json')
        self.assertTrue(canonical.is_file())
        (self.workspace/result['manifest']).write_text('untrusted model modification')
        self.assertIn('explicit_native_file_selection',canonical.read_text())
    def test_sensitive_and_symlink_sources_are_rejected(self):
        p=self.root/'.env';p.write_text('private');link=self.root/'link';link.symlink_to(p)
        key=self.root/'private.key';key.write_text('private')
        for f in [p,link,key]:self.denied(403,lambda:self.operator.request('/localpilot/v1/attachments/import',{'client_subject':'codex','model':'localpilot','paths':[str(f)]}))
    def test_recommendation_does_not_fall_below_the_core_agent_context_gate(self):
        from recommender import recommend
        from localpilot_service.protocol import local_agent_constraints
        policy=local_agent_constraints()
        result=recommend(64,context_k=64,minimum_context_k=policy['minimum_context']//1024,excluded_size_classes=policy['excluded_size_classes'],profiles={})
        self.assertGreaterEqual(result['context_length'],policy['minimum_context'])
        self.assertNotIn(str(result['model']['parameters_b'])+'B',policy['excluded_size_classes'])
        small=recommend(10,context_k=64,minimum_context_k=64,excluded_size_classes=policy['excluded_size_classes'],profiles={})
        self.assertIsNone(small)

    def test_unknown_extension_obeys_explicit_full_permission(self):
        from agent.registry import ToolRegistry
        for mode in MODES.values():
            registry=ToolRegistry(self.workspace,permission_mode=mode)
            registry.register('unknown',lambda workspace_root:'should not run automatically')
            result=registry.call('unknown',{})
            if mode=='full-permission':self.assertEqual(result,'should not run automatically')
            else:self.assertEqual(result['status'],'approval_required')

    def test_local_only_network_floor_survives_full_permission(self):
        from agent.policy import DataPolicy
        gateway=PermissionGateway(self.workspace,mode='full-permission',data_policy=DataPolicy(local_only=True))
        with gateway.approving('fetch',True):
            decision=gateway.decide('fetch','low',['model says SAFE'],{},metadata=ToolRiskMetadata(read_only=True,mutating=False,network_access=True))
        self.assertEqual(decision['status'],'denied')

    def test_permission_matrix_and_hard_boundary(self):
        for mode,expected in [('approve-all',['approval_required']*3),('assist-low-risk',['allowed','approval_required','approval_required']),('assist-high-risk',['allowed','allowed','approval_required']),('full-permission',['allowed']*3)]:
            gateway=PermissionGateway(self.workspace,mode=mode,capabilities=CapabilityPolicy(execute=True))
            actual=[]
            for op,risk,meta in [('read_file','low',ToolRiskMetadata(read_only=True,mutating=False)),('apply_patch','medium',ToolRiskMetadata()),('execute','high',ToolRiskMetadata(requires_shell=True))]:
                actual.append(gateway.decide(op,risk,['test'],{},metadata=meta)['status'])
            self.assertEqual(actual,expected)
            self.assertEqual(gateway.decide('apply_patch','low',[],{},blocked=True)['status'],'denied')
            self.assertEqual(gateway.decide('read_file','low',[],{},metadata=ToolRiskMetadata(requires_host_approval=True))['status'],'allowed' if mode=='full-permission' else 'approval_required')

class DesktopV5ProfileTests(DesktopProductTests):
    def factory(self,callback):
        from agent.session import AgentSession
        from agent.registry import create_default_registry
        from agent.retry import RetryPolicy
        from agent.engine_v5 import EngineV5Policy
        return AgentSession(create_default_registry(self.workspace,permission_mode='approve-mutations'),backend=self.backend,policy='cloud-only',event_callback=callback,verification_callback=self.verifier,retry_policy=RetryPolicy(max_attempts=1),engine_policy=EngineV5Policy())

BaseStart=Base.start
del Base
