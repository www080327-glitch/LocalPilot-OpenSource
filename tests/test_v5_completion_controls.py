"""SCRIPTED_CONTROL: resource UNKNOWN fences and durable thinking isolation."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import patch
from agent.backends import BackendCapabilities
from agent.registry import ToolRegistry,create_default_registry
from agent.session import AgentSession
from agent.policy import DataPolicy
from agent.engine_v5 import EngineV5Policy
from localpilot_api.service import TaskService,TaskRequest,APIError
from localpilot_service.model_resources import ModelResources
from localpilot_service.security import Principal
from tests.test_runtime_api import Backend,answer,call

class CompletionControls(unittest.TestCase):
    def test_client_instructions_do_not_mutate_the_v5_stable_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);backend=Backend(answer('first'),answer('second'))
            def factory(callback):return AgentSession(ToolRegistry(root),cloud_backend=backend,policy='cloud-only',data_policy=DataPolicy(local_only=False),engine_policy=EngineV5Policy(),event_callback=callback)
            service=TaskService({'cloud':factory})
            try:
                a=service.create_task(TaskRequest('one',model='cloud',instructions='FIRST CLIENT GUIDANCE'))
                self.assertEqual(service.wait(a['id'])['status'],'completed')
                session=service._session(a['session_id']);prefix=session.runtime.base_prompt
                b=service.create_task(TaskRequest('two',model='cloud',session_id=a['session_id'],instructions='SECOND CLIENT GUIDANCE'))
                self.assertEqual(service.wait(b['id'])['status'],'completed')
                self.assertEqual(session.runtime.base_prompt,prefix)
                guidance=[m for m in backend.requests[-1]['messages'] if m.content and 'CLIENT GUIDANCE' in m.content]
                self.assertTrue(guidance);self.assertTrue(all(m.role=='user' for m in guidance))
            finally:service.shutdown()
    def test_pause_preserves_unexecuted_proposal_across_core_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);workspace=root/'workspace';workspace.mkdir();(workspace/'input.txt').write_text('fixture')
            entered=threading.Event();release=threading.Event()
            def step(messages):
                if any(m.role=='tool' for m in messages):return answer('fixture')
                entered.set();release.wait(3)
                return answer(None,call('read_file',{'path':'input.txt'},'read-once'))
            def factory(callback):
                return AgentSession(create_default_registry(workspace),cloud_backend=Backend(step,step),policy='cloud-only',data_policy=DataPolicy(local_only=False),event_callback=callback)
            service=TaskService({'cloud':factory},persistence=root/'state.sqlite3')
            task=service.create_task(TaskRequest('Read input.txt',model='cloud',idempotency_key='pause'))
            self.assertTrue(entered.wait(2));service.pause(task['id']);release.set()
            paused=service.wait(task['id']);self.assertEqual(paused['status'],'requires_human');self.assertEqual(paused['tools'],[])
            old=paused['required_action']['id'];service.suspend()
            restored=TaskService({'cloud':factory},persistence=root/'state.sqlite3')
            try:
                current=restored.task_snapshot(task['id'])
                with self.assertRaises(APIError):restored.act(task['id'],'continue',old)
                restored.act(task['id'],'continue',current['required_action']['id'])
                done=restored.wait(task['id']);self.assertEqual(done['status'],'completed');self.assertEqual(len(done['tools']),1)
                self.assertFalse(done['tools'][0]['receipt_reused'])
            finally:restored.shutdown()

    def test_resource_unknown_is_persistent_and_never_replayed(self):
        class Provider:
            model='small';loaded=False;calls=0
            def inspect_service(self):return {'active_requests':0,'models':[{'id':'small','loaded':self.loaded,'size_bytes':1000000,'trust_remote_code':False}]}
            @contextmanager
            def _open(self,path,body):
                self.calls+=1;self.loaded=True
                raise TimeoutError('effect unknown')
                yield
        with tempfile.TemporaryDirectory() as folder:
            provider=Provider();ordinary=Principal('user','u'*32,routes={'small':'small'})
            operator=Principal('resource','r'*32,operator=True,scopes=frozenset({'read','resource_control'}),approval_for=('user',),routes={})
            server=SimpleNamespace(access=SimpleNamespace(principals={'user':ordinary}),model_backends={'small':provider})
            manager=ModelResources(server,Path(folder)/'operations.json')
            body={'client_subject':'user','model':'small','operation':'load','confirmed':True,'max_memory_bytes':3*1024**3}
            with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=16*1024**3)),patch('psutil.disk_usage',return_value=SimpleNamespace(free=8*1024**3)):
                first=manager.operate(operator,body,'one')
                self.assertEqual(first['status'],'UNKNOWN')
                restored=ModelResources(server,Path(folder)/'operations.json')
                self.assertEqual(restored.operate(operator,body,'one')['status'],'UNKNOWN')
                self.assertEqual(provider.calls,1)
                with self.assertRaises(APIError):restored.operate(ordinary,body,'other')
                with self.assertRaises(APIError):restored.operate(operator,{**body,'operation':'unload'},'one')

    def test_session_thinking_isolated_changed_and_restored_without_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);workspace=root/'workspace';workspace.mkdir()
            def factory(callback):
                backend=Backend(answer('fixture'),answer('fixture'),answer('fixture'))
                backend.is_local=False
                backend.capabilities=BackendCapabilities(supports_tool_calling=True,supported_thinking_efforts=('none','low','high'),supports_reasoning_effort=True)
                return AgentSession(ToolRegistry(workspace),cloud_backend=backend,policy='cloud-only',data_policy=DataPolicy(local_only=False),event_callback=callback)
            service=TaskService({'cloud':factory},persistence=root/'state.sqlite3')
            a=service.create_task(TaskRequest('fixture',model='cloud',reasoning_effort='high',idempotency_key='a'));service.wait(a['id'])
            b=service.create_task(TaskRequest('fixture',model='cloud',reasoning_effort='none',idempotency_key='b'));service.wait(b['id'])
            c=service.create_task(TaskRequest('next',model='cloud',session_id=a['session_id'],reasoning_effort='low',idempotency_key='c'));service.wait(c['id'])
            self.assertEqual(service._session(a['session_id']).runtime.thinking_mode,'low')
            self.assertEqual(service._session(b['session_id']).runtime.thinking_mode,'none')
            service.suspend()
            restored=TaskService({'cloud':factory},persistence=root/'state.sqlite3')
            try:
                self.assertEqual(restored._session(a['session_id']).runtime.thinking_mode,'low')
                self.assertEqual(restored._session(b['session_id']).runtime.thinking_mode,'none')
            finally:restored.shutdown()
