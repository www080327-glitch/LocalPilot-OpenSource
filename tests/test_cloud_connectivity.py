"""Offline credential and transport fault controls, never real provider evidence."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from agent.cloud_credentials import CloudCredentialError, resolve_deepseek_key
from agent.deepseek import DeepSeekBackend, DeepSeekAPIError, DeepSeekStreamError
from agent.backends import Message
from agent.retry import RetryPolicy, call_with_retry
from agent.worker_tiers import configure_workers
from tests.test_runtime_backends import FakeResponse, sse


class CloudConnectivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'key'
        self.path.write_text('fixture-secret\n'); self.path.chmod(0o600)
        self.env = patch.dict(os.environ, {}, clear=True); self.env.start(); self.addCleanup(self.env.stop)

    def test_missing_is_distinct_from_path_error(self):
        for path, category in [(None, 'missing_credentials'), (str(self.path)+'-missing', 'configuration_path_error')]:
            with self.assertRaises(CloudCredentialError) as e: resolve_deepseek_key(key_file=path)
            self.assertEqual(e.exception.category, category)
            self.assertNotIn('fixture-secret', str(e.exception))

    def test_owner_only_explicit_file_and_environment_reference(self):
        self.assertEqual(resolve_deepseek_key(key_file=self.path), 'fixture-secret')
        os.environ['DEEPSEEK_API_KEY_FILE'] = str(self.path)
        self.assertEqual(DeepSeekBackend().api_key, 'fixture-secret')
        self.assertNotIn('DEEPSEEK_API_KEY', os.environ)

    def test_explicit_and_environment_precedence(self):
        os.environ.update(DEEPSEEK_API_KEY='env-fixture', DEEPSEEK_API_KEY_FILE='/invalid')
        self.assertEqual(resolve_deepseek_key('explicit-fixture', key_file='/invalid'), 'explicit-fixture')
        self.assertEqual(resolve_deepseek_key(key_file=self.path), 'fixture-secret')
        self.assertEqual(resolve_deepseek_key(), 'env-fixture')

    def test_no_implicit_dotenv_or_cwd_discovery(self):
        with patch('os.open') as op:
            with self.assertRaises(CloudCredentialError): resolve_deepseek_key()
        op.assert_not_called()

    def test_rejects_group_world_readable(self):
        for mode in [0o640, 0o604, 0o644]:
            self.path.chmod(mode)
            with self.assertRaises(CloudCredentialError) as e: resolve_deepseek_key(key_file=self.path)
            self.assertEqual(e.exception.category, 'unsafe_credential_file')

    def test_rejects_symlink_and_nonregular(self):
        link = self.path.with_name('link'); link.symlink_to(self.path)
        fifo = self.path.with_name('fifo'); os.mkfifo(fifo, 0o600)
        for path in [link, fifo, self.path.parent]:
            with self.assertRaises(CloudCredentialError): resolve_deepseek_key(key_file=path)

    def test_rejects_wrong_owner(self):
        original = os.fstat
        def wrong_owner(fd):
            values = list(original(fd)); values[4] += 1
            return os.stat_result(values)
        with patch('os.fstat', side_effect=wrong_owner):
            with self.assertRaises(CloudCredentialError): resolve_deepseek_key(key_file=self.path)

    def test_format_rejection_never_echoes_secret(self):
        for value in ['', 'fixture-secret\nextra', 'fixture-secret\r\n', 'fixture-secret '*500, 'é']:
            self.path.write_text(value)
            with self.assertRaises(CloudCredentialError) as e: resolve_deepseek_key(key_file=self.path)
            self.assertNotIn('fixture-secret', str(e.exception))

    def test_invalid_worker_configuration_is_not_missing_auth(self):
        os.environ['DEEPSEEK_API_KEY_FILE'] = '/invalid'
        with self.assertRaises(CloudCredentialError) as e:
            configure_workers({'LIGHT':'deepseek:deepseek-flash','STRONG':'deepseek:deepseek-flash'})
        self.assertEqual(e.exception.category, 'configuration_path_error')

    def test_missing_workers_remain_unavailable(self):
        workers, state = configure_workers({'LIGHT':'deepseek:deepseek-flash','STRONG':'deepseek:deepseek-flash'})
        self.assertTrue(all(v is None for v in workers.values()))
        self.assertTrue(all(v['reason']=='missing_api_credentials' for v in state.values()))

    def test_query_fragment_userinfo_endpoints_rejected(self):
        for url in ['https://api.deepseek.com?token=fixture-secret','https://api.deepseek.com#fragment','https://fixture-secret@api.deepseek.com']:
            with self.assertRaises(ValueError): DeepSeekBackend(api_key='fixture-secret',base_url=url)

    def test_http_error_retains_status_without_body_leak(self):
        backend = DeepSeekBackend(api_key='fixture-secret')
        for status in [400,401,402,422,429,500,503]:
            error=HTTPError(backend.base_url,status,'failure',{},io.BytesIO(b'fixture-secret and encoded f%69xture-secret'))
            with patch('agent.deepseek.urlopen',side_effect=error):
                with self.assertRaises(DeepSeekAPIError) as e: backend.request([Message('user','fixture')])
            self.assertEqual(e.exception.status_code,status)
            self.assertNotIn('secret',str(e.exception))

    def test_network_error_does_not_echo_proxy_or_auth(self):
        with patch('agent.deepseek.urlopen',side_effect=URLError('fixture-secret')):
            with self.assertRaises(DeepSeekAPIError) as e: DeepSeekBackend(api_key='fixture-secret').request([])
        self.assertIsNone(e.exception.status_code)
        self.assertNotIn('secret',str(e.exception))

    def test_tools_only_interrupted_transport_is_not_retried(self):
        class Broken(FakeResponse):
            def __iter__(self):
                yield from super().__iter__()
                raise TimeoutError('controlled read failure')
        body=sse({'model':'fixture-cloud','choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'apply_patch','arguments':'{"changes":'}}]}}]},done=False)
        backend=DeepSeekBackend(api_key='fixture-secret')
        with patch('agent.deepseek.urlopen',return_value=Broken(body)) as op:
            with self.assertRaises(DeepSeekStreamError) as e:
                call_with_retry(lambda:list(backend.stream([])),RetryPolicy(max_attempts=3),sleep=lambda _:None)
        self.assertEqual(op.call_count,1)
        self.assertFalse(e.exception.retryable)
        self.assertEqual(e.exception.response.finish_reason,'stream_interrupted')
        self.assertEqual(e.exception.response.message.tool_calls[0].arguments,'{"changes":')

    def test_transport_timeout_remains_retryable_without_secret_context(self):
        from agent.retry import is_transient_error
        for underlying, expected in [(TimeoutError('fixture-secret'), True), (URLError('certificate fixture-secret'),False)]:
            with patch('agent.deepseek.urlopen',side_effect=URLError(underlying)):
                with self.assertRaises(DeepSeekAPIError) as e: DeepSeekBackend(api_key='fixture-secret').request([])
            self.assertEqual(is_transient_error(e.exception),expected)
            self.assertNotIn('fixture-secret',str(e.exception))

    def test_tools_only_partial_cannot_dispatch_or_failover_in_runtime(self):
        from agent.session import AgentSession,SessionBudgets
        from agent.registry import create_default_registry
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        from tests.test_hybrid_runtime import Local,answer
        class Broken(FakeResponse):
            def __iter__(self):
                yield from super().__iter__();raise TimeoutError('controlled disconnect')
        args=json.dumps({'changes':[{'operation':'create','path':'must-not-exist.txt','content':'unsafe partial'}]})
        body=sse({'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'apply_patch','arguments':args}}]}}]},done=False)
        cloud=DeepSeekBackend(api_key='fixture-secret');local=Local(answer('must not be called'))
        r=AgentSession(create_default_registry(self.path.parent,permission_mode='full-permission'),
            cloud_backend=cloud,local_backend=local,streaming=True,policy='balanced',
            retry_policy=RetryPolicy(max_attempts=3),budgets=SessionBudgets(max_token_units=600000),
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED'),automatic_failover=True),
            hybrid_primary='cloud',hybrid_backends={'cloud':cloud,'local':local})
        with patch('agent.deepseek.urlopen',return_value=Broken(body)) as op: result=r.run_turn('fixture')
        self.assertNotEqual(result.status,'completed')
        self.assertEqual(op.call_count,1)
        self.assertFalse(local.requests)
        self.assertFalse((self.path.parent/'must-not-exist.txt').exists())
        self.assertFalse(any(x['name']=='apply_patch' for x in r.tool_history))

    def test_http_reason_and_body_cannot_leak_through_traceback(self):
        import traceback
        backend=DeepSeekBackend(api_key='fixture-secret')
        error=HTTPError(backend.base_url,401,'proxy echoed fixture-secret',{},io.BytesIO(b'fixture-secret'))
        with patch('agent.deepseek.urlopen',side_effect=error):
            try:
                backend.request([])
            except DeepSeekAPIError as e:
                rendered=''.join(traceback.format_exception(e))
        self.assertNotIn('fixture-secret',rendered)
        self.assertIn('HTTP 401',rendered)
