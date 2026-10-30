import io
import json
from pathlib import Path
import tempfile
import unittest
from agent.omlx import OMLXBackend
from agent.backends import Message
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_api.service import TaskService, TaskRequest
from tests.test_runtime_api import answer

class ThinkingToggleTests(unittest.TestCase):
    def backend(self):
        return OMLXBackend(base_url='http://127.0.0.1:1234/v1',model='qwen',chat_template_kwargs={'enable_thinking':False})
    def test_toggle_changes_real_provider_parameter_not_fake_effort(self):
        backend=self.backend();backend.configure_thinking_toggle(False)
        for effort,enabled in [('none',False),('high',True)]:
            payload=backend._payload([Message('user','test')],[],20,thinking=effort)
            self.assertIs(payload['chat_template_kwargs']['enable_thinking'],enabled)
            self.assertNotIn('reasoning_effort',payload)
    def test_existing_backend_keeps_old_default_until_host_session_opts_in(self):
        backend=self.backend()
        self.assertEqual(backend.capabilities.supported_thinking_efforts,())
        self.assertFalse(backend._payload([Message('user','test')],[],20)['chat_template_kwargs']['enable_thinking'])
    def test_readonly_discovery_uses_provider_declaration_and_route_override(self):
        backend=self.backend();backend._thinking_cache.clear()
        paths=[]
        class Opener:
            def open(self,request,timeout):
                paths.append(request.full_url)
                return io.BytesIO(json.dumps({'models':[{'id':'qwen','thinking_default':True}]}).encode())
        backend._opener=Opener()
        observed=backend.thinking_toggle_observation()
        self.assertTrue(observed['supported'])
        self.assertFalse(observed['default'])
        self.assertEqual(paths,['http://127.0.0.1:1234/v1/models/status'])
    def test_unsupported_binary_value_is_rejected(self):
        backend=self.backend();backend.configure_thinking_toggle(False)
        with self.assertRaises(ValueError):backend._payload([Message('user','test')],[],20,thinking='medium')
    def test_session_thinking_survives_restart_and_maps_on_off(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);workspace=root/"workspace";workspace.mkdir();captured=[]
            class ScriptedOMLX(OMLXBackend):
                def health_check(self):return True
                def request(self,messages,tools=None,thinking=None,max_tokens=None):
                    captured.append(self._payload(messages,tools,max_tokens,thinking=thinking))
                    return answer('done')
            def factory(callback):
                backend=ScriptedOMLX(base_url='http://127.0.0.1:1234/v1',model='qwen',chat_template_kwargs={'enable_thinking':False})
                return AgentSession(create_default_registry(workspace),backend=backend,policy='local-only',streaming=False,event_callback=callback)
            service=TaskService({'local':factory},persistence=root/'runtime.db')
            options={'permission_mode':'full','agent_profile':'standard','scope_revision':3,'thinking_toggle':{'model':'qwen','default':False}}
            session=service.create_session('local',desktop_options=options)
            first=service.create_task(TaskRequest('on',model='local',session_id=session['id'],reasoning_effort='high'))
            service.wait(first['id']);service.suspend()
            service=TaskService({'local':factory},persistence=root/'runtime.db')
            try:
                second=service.create_task(TaskRequest('off',model='local',session_id=session['id'],reasoning_effort='none'))
                service.wait(second['id'])
                self.assertEqual([p['chat_template_kwargs']['enable_thinking'] for p in captured],[True,False])
            finally:service.shutdown()

if __name__=='__main__':unittest.main()
