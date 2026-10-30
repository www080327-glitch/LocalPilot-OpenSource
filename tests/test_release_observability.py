"""Provider-returned cache accounting and host startup checks; no real models."""
import unittest
from agent.local_http import LocalHTTPBackend,LocalBackendError

class CacheUsageTests(unittest.TestCase):
    def test_standard_provider_cache_details_are_preserved_for_runtime_usage(self):
        raw={'prompt_tokens':100,'completion_tokens':4,'prompt_tokens_details':{'cached_tokens':64}}
        usage=LocalHTTPBackend._usage({'usage':raw})
        self.assertEqual(usage['prompt_cache_hit_tokens'],64)
        self.assertEqual(usage['prompt_cache_miss_tokens'],36)
        self.assertNotIn('prompt_cache_hit_tokens',raw)
        self.assertIsNone(LocalHTTPBackend._usage({'usage':None}))
        self.assertNotIn('prompt_cache_hit_tokens',LocalHTTPBackend._usage({'usage':{'prompt_tokens':100}}))
    def test_untrusted_impossible_or_conflicting_cache_counts_fail_closed(self):
        for value in [True,-1,101,'64']:
            with self.assertRaises(LocalBackendError):LocalHTTPBackend._usage({'usage':{'prompt_tokens':100,'prompt_tokens_details':{'cached_tokens':value}}})
        with self.assertRaises(LocalBackendError):LocalHTTPBackend._usage({'usage':{'prompt_tokens':100,'prompt_tokens_details':{'cached_tokens':64},'prompt_cache_hit_tokens':63}})


class StartupValidationTests(unittest.TestCase):
    def test_unsupported_host_thinking_fails_before_accepting_tasks_without_inference(self):
        import tempfile,json,os
        from pathlib import Path
        from unittest.mock import patch
        from localpilot_service.deployment import build
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);workspace=root/'workspace';workspace.mkdir()
            config={'schema_version':1,'port':0,'data_dir':str(root/'data'),'clients':[{'subject':'fixture','token_env':'LP_STARTUP_FIXTURE'}],'routes':{'localpilot':{'workspace':str(workspace),'backend':{'kind':'local-openai','model':'not-loaded','base_url':'http://127.0.0.1:9/v1'},'thinking':'none','cloud_egress':'LOCAL_ONLY'}}}
            path=root/'service.json';path.write_text(json.dumps(config));path.chmod(0o600)
            with patch.dict(os.environ,LP_STARTUP_FIXTURE='f'*32),patch('agent.local_http.LocalHTTPBackend._open',side_effect=AssertionError('must not perform inference')):
                with self.assertRaisesRegex(ValueError,'Invalid route configuration'):build(path)

class PreTurnFailureAccountingTests(unittest.TestCase):
    def test_rejected_new_turn_never_inherits_previous_usage_or_verification(self):
        import tempfile,hashlib
        from pathlib import Path
        from agent.registry import create_default_registry
        from agent.session import AgentSession
        from agent.retry import RetryPolicy
        from localpilot_api.service import TaskService,TaskRequest
        from localpilot_service.verification import configured_verifier
        from tests.test_runtime_api import Backend,answer
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);ws=root/'workspace';ws.mkdir();(ws/'fixture.txt').write_text('MARKER')
            verifier=configured_verifier(ws,{'id':'before-turn','files':{'fixture.txt':hashlib.sha256(b'MARKER').hexdigest()},'required_text':'MARKER'})
            backend=Backend(answer('MARKER'))
            factory=lambda cb:AgentSession(create_default_registry(ws),backend=backend,policy='cloud-only',event_callback=cb,retry_policy=RetryPolicy(max_attempts=1),verification_callback=verifier)
            service=TaskService({'localpilot':factory},persistence=root/'runtime.db')
            try:
                first=service.wait(service.create_task(TaskRequest(input='first'))['id'])
                self.assertEqual(first['result']['verification_status'],'passed')
                bad=service.wait(service.create_task(TaskRequest(input='x'*5000,session_id=first['session_id']))['id'])
                self.assertEqual(bad['status'],'failed')
                self.assertEqual(bad['result']['model_calls'],[])
                self.assertEqual(bad['result']['verification_status'],'not_run')
                self.assertEqual(service.task_snapshot(first['id'])['result'],first['result'])
                self.assertEqual(len(backend.requests),1)
            finally:service.shutdown()

class ModelInterpreterIsolationTests(unittest.TestCase):
    def test_vendor_model_does_not_inherit_core_python_or_provider_secrets(self):
        from localpilot_service.cached_omlx import model_environment
        env=model_environment({'PATH':'/bin','HOME':'/user','PYTHONPATH':'/core/python314/site-packages','PYTHONHOME':'/core/python314','VIRTUAL_ENV':'/core','OMLX_API_KEY':'local-model-fixture','DEEPSEEK_API_KEY':'provider-fixture'})
        self.assertNotIn('PYTHONPATH',env);self.assertNotIn('PYTHONHOME',env);self.assertNotIn('VIRTUAL_ENV',env)
        self.assertNotIn('DEEPSEEK_API_KEY',env);self.assertEqual(env['OMLX_API_KEY'],'local-model-fixture')
        self.assertEqual(env['HF_HUB_OFFLINE'],'1')
