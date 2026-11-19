"""Real TLS/SSE and Core persistence checks for the Responses transport."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent.backends import Message, ToolCall
from agent.cloud_credentials import resolve_openai_key
from agent.local_http import LocalBackendError
from agent.policy import DataPolicy
from agent.worker_tiers import configure_workers
from localpilot_service.backend_contract import ServiceOpenAIResponsesBackend
from localpilot_service.deployment import build
from localpilot_service.route_backends import build_backend
from localpilot_service.sdk import Client
from tests.test_local_http_backend import sse
from tests.test_openai_cloud_backend import OpenAICloudFixture


def response_payload(*, text=None, call=False, status='completed'):
    output = [{'type': 'reasoning', 'id': 'rs_fixture', 'summary': [],
               'encrypted_content': 'synthetic-encrypted-reasoning'}]
    if text is not None:
        output.append({'type': 'message', 'id': 'msg_fixture', 'status': 'completed',
                       'role': 'assistant', 'content': [{'type': 'output_text', 'text': text,
                                                       'annotations': []}]})
    if call:
        output.append({'type': 'function_call', 'id': 'fc_fixture', 'status': 'completed',
                       'call_id': 'call_fixture', 'name': 'read_file',
                       'arguments': '{"path":"fact.txt"}'})
    return {'id': 'resp_fixture', 'object': 'response', 'model': 'mock-local', 'status': status,
            'error': None, 'output': output,
            'incomplete_details': {'reason': 'max_output_tokens'} if status == 'incomplete' else None,
            'usage': {'input_tokens': 16, 'output_tokens': 9, 'total_tokens': 25,
                      'input_tokens_details': {'cached_tokens': 4},
                      'output_tokens_details': {'reasoning_tokens': 6}}}


class OpenAIResponsesConfigurationTests(unittest.TestCase):
    def test_configured_worker_keeps_missing_credentials_and_local_only_boundaries(self):
        mapping = {'LIGHT': 'openai:gpt-6.1-sol', 'STRONG': 'openai:gpt-6.2-sol'}
        with patch.dict(os.environ, {}, clear=True):
            backends, availability = configure_workers(mapping)
        self.assertEqual(backends, {'LIGHT': None, 'STRONG': None})
        self.assertEqual(availability['STRONG']['reason'], 'missing_api_credentials')
        with self.assertRaises(PermissionError):
            configure_workers(mapping, data_policy=DataPolicy(local_only=True))

    def test_gpt55_default_efforts_match_alias_and_dated_snapshot(self):
        for model in ('gpt-5.5', 'gpt-5.5-2026-04-23'):
            with self.subTest(model=model):
                backend = ServiceOpenAIResponsesBackend(model=model, api_key='synthetic-only')
                self.assertEqual(backend.capabilities.supported_thinking_efforts,
                                 ('none', 'low', 'medium', 'high', 'xhigh'))
                for effort in ('none', 'medium', 'xhigh'):
                    payload = backend._payload([Message('user', 'synthetic')], thinking=effort)
                    self.assertEqual(payload['reasoning'], {'effort': effort})
                with self.assertRaisesRegex(ValueError, 'does not declare this reasoning effort'):
                    backend._payload([Message('user', 'synthetic')], thinking='max')

    def test_luna_defaults_and_explicit_host_efforts_are_unchanged(self):
        luna = ServiceOpenAIResponsesBackend(model='gpt-6-luna', api_key='synthetic-only')
        self.assertEqual(luna.capabilities.supported_thinking_efforts,
                         ('none', 'low', 'medium', 'high', 'xhigh', 'max'))
        self.assertEqual(luna._payload([], thinking='max')['reasoning'], {'effort': 'max'})
        host = ServiceOpenAIResponsesBackend(model='gpt-5.5', api_key='synthetic-only',
                                            reasoning_efforts=('medium',))
        self.assertEqual(host.capabilities.supported_thinking_efforts, ('medium',))
        self.assertEqual(host._payload([], thinking='medium')['reasoning'], {'effort': 'medium'})
        with self.assertRaisesRegex(ValueError, 'does not declare this reasoning effort'):
            host._payload([], thinking='none')

    def test_gpt55_default_inference_does_not_match_other_suffixes(self):
        for model in ('gpt-5.5-pro', 'gpt-5.5-custom'):
            with self.subTest(model=model):
                backend = ServiceOpenAIResponsesBackend(model=model, api_key='synthetic-only')
                self.assertEqual(backend.capabilities.supported_thinking_efforts,
                                 ('low', 'medium', 'high', 'xhigh', 'max'))

    def test_private_key_file_precedes_default_environment_and_identity_has_no_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'provider.key'
            path.write_text('fixture-key-file\n')
            path.chmod(0o600)
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-environment-key'}):
                backend = build_backend({'kind': 'openai', 'protocol': 'responses',
                    'model': 'gpt-6-luna', 'key_file': str(path)}, DataPolicy())
            self.assertIsInstance(backend, ServiceOpenAIResponsesBackend)
            self.assertEqual(backend._api_key, 'fixture-key-file')
            self.assertEqual(resolve_openai_key(key_file=path), 'fixture-key-file')
            self.assertIn('medium', backend.capabilities.supported_thinking_efforts)
            self.assertEqual(backend.service_contract['protocol'], 'openai_responses_v1')
            self.assertNotIn('fixture-key-file', json.dumps(backend.profile.snapshot()))
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'unsafe_credential_file'):
                resolve_openai_key(key_file=path)

    def test_explicit_protocol_and_generation_parameters_are_validated_once_at_adapter(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key'}):
            for changes in ({'protocol': 'unrecognized'}, {'generation_parameters': []},
                            {'protocol': 'responses', 'generation_parameters': {'seed': 1}}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    build_backend({'kind': 'openai', 'model': 'gpt-6-luna', **changes}, DataPolicy())
            backend = build_backend({'kind': 'openai', 'protocol': 'responses',
                'model': 'gpt-6-luna', 'generation_parameters': {'temperature': 0}}, DataPolicy())
        with self.assertRaisesRegex(ValueError, 'reasoning effort none'):
            backend._payload([Message('user', 'hi')], thinking='medium')
        self.assertEqual(backend._payload([Message('user', 'hi')], thinking='none')['temperature'], 0)


class OpenAIResponsesTransportTests(OpenAICloudFixture):
    def backend(self, **options):
        return super().backend(protocol='responses', **options)

    def test_explicit_cli_worker_models_use_responses_and_preserve_output_budget(self):
        workers, availability = configure_workers({
            'LIGHT': 'openai:gpt-6.1-sol', 'STRONG': 'openai:gpt-6.2-sol'})
        for tier, model in (('LIGHT', 'gpt-6.1-sol'), ('STRONG', 'gpt-6.2-sol')):
            with self.subTest(tier=tier):
                backend = workers[tier]
                self.assertEqual(backend.base_url, 'https://api.openai.com/v1')
                backend.base_url = self.model.base_url
                self.model.add(response_payload(text='WORKER-OK'))
                result = backend.request([Message('user', 'public worker fixture')],
                                         thinking='medium', max_tokens=512)
                self.assertEqual(result.message.content, 'WORKER-OK')
                self.assertEqual(self.model.headers[-1][0], '/v1/responses')
                payload = self.model.requests[-1]
                self.assertEqual(payload['model'], model)
                self.assertEqual(payload['reasoning'], {'effort': 'medium'})
                self.assertEqual(payload['max_output_tokens'], 512)
                self.assertFalse(payload['store'])
                self.assertFalse(availability[tier]['verified_api_access'])

    def test_tool_result_and_encrypted_reasoning_replay_use_responses_wire_format(self):
        backend = self.backend()
        schema = {'type': 'function', 'function': {'name': 'read_file',
            'description': 'Read the selected file.', 'parameters': {'type': 'object',
            'properties': {'path': {'type': 'string'}, 'offset': {'type': 'integer'}},
            'required': ['path']}}}
        self.model.add(response_payload(call=True))
        history = [Message('user', 'Read fact.txt')]
        first = backend.request(history, tools=[schema], thinking='medium', max_tokens=512)
        history.extend([first.message, Message('tool', 'PUBLIC-FIXTURE', tool_call_id='call_fixture')])
        self.model.add(response_payload(text='PUBLIC-FIXTURE'))
        final = backend.request(history, tools=[schema], thinking='medium', max_tokens=512)
        self.assertEqual(first.message.tool_calls[0].name, 'read_file')
        self.assertEqual(final.message.content, 'PUBLIC-FIXTURE')
        self.assertEqual(final.usage['prompt_tokens'], 16)
        self.assertEqual(final.usage['prompt_cache_hit_tokens'], 4)
        self.assertEqual(final.usage['completion_tokens_details']['reasoning_tokens'], 6)
        for payload in self.model.requests:
            self.assertNotIn('messages', payload)
            self.assertNotIn('max_completion_tokens', payload)
            self.assertFalse(payload['store'])
            self.assertEqual(payload['max_output_tokens'], 512)
            self.assertEqual(payload['reasoning'], {'effort': 'medium'})
            self.assertFalse(payload['tools'][0]['strict'])
            self.assertEqual(payload['tools'][0]['parameters']['required'], ['path'])
        replay = self.model.requests[-1]['input']
        self.assertEqual(replay[1]['encrypted_content'], 'synthetic-encrypted-reasoning')
        self.assertEqual(replay[2]['type'], 'function_call')
        self.assertEqual(replay[3], {'type': 'function_call_output', 'call_id': 'call_fixture',
                                    'output': 'PUBLIC-FIXTURE'})
        self.assertEqual(self.model.headers[0][0], '/v1/responses')

    def test_redacted_or_other_model_message_does_not_replay_original_reasoning(self):
        backend = self.backend()
        self.model.add(response_payload(text='private synthetic text'))
        message = backend.request([Message('user', 'hi')]).message
        copied = Message.from_dict(message.to_dict(include_reasoning=True))
        self.assertIn('encrypted_content', json.dumps(backend._payload([copied])))
        copied.content = '[withheld]'
        self.assertNotIn('encrypted_content', json.dumps(backend._payload([copied])))
        message.native_replay['model'] = 'different-model'
        self.assertNotIn('encrypted_content', json.dumps(backend._payload([message])))

    def test_reasoning_removal_diagnostics_are_distinct_from_cache_usage(self):
        payload = response_payload(text='DONE')
        payload['input_transformations'] = [{'id': 'rs_previous', 'type': 'reasoning',
            'action': 'removed', 'reason': 'prefix_mismatch'}]
        payload['prompt_cache_diagnostics'] = {'type': 'cache_miss', 'reason': 'input_changed',
            'cache_missed_tokens': 12, 'comparison_reusable_tokens': 16}
        self.model.add(payload)
        backend = self.backend()
        response = backend.request([Message('user', 'Continue')])
        self.assertEqual(response.usage['prompt_cache_hit_tokens'], 4)
        self.assertEqual(response.diagnostics, {'response_id': 'resp_fixture',
            'input_transformations': payload['input_transformations'],
            'prompt_cache_diagnostics': payload['prompt_cache_diagnostics']})
        self.assertNotIn('input_transformations', json.dumps(backend._payload([response.message])))

    def test_stream_preserves_reported_empty_diagnostics_without_inventing_missing_fields(self):
        payload = response_payload(text='DONE')
        payload['input_transformations'] = []
        payload['usage'] = None
        self.model.add(sse({'type': 'response.completed', 'response': payload}),
                       content_type='text/event-stream')
        backend = self.backend()
        response = list(backend.stream([Message('user', 'Continue')]))[-1].response
        self.assertIsNone(response.usage)
        self.assertEqual(response.diagnostics, {'response_id': 'resp_fixture', 'input_transformations': []})
        self.model.add(response_payload(text='NEXT'))
        next_response = backend.request([Message('user', 'Next')])
        self.assertNotIn('input_transformations', next_response.diagnostics)
        self.assertNotIn('prompt_cache_diagnostics', next_response.diagnostics)

    def test_malformed_provider_diagnostics_are_rejected_at_transport_boundary(self):
        for field, value in (('id', []), ('input_transformations', {}),
                             ('prompt_cache_diagnostics', [])):
            with self.subTest(field=field):
                payload = response_payload(text='DONE')
                payload[field] = value
                self.model.add(payload)
                with self.assertRaisesRegex(LocalBackendError, 'Malformed OpenAI Responses result'):
                    self.backend().request([Message('user', 'Continue')])

    def test_stream_has_terminal_usage_and_incomplete_calls_are_not_success(self):
        self.model.add(sse({'type': 'response.created', 'response': {'id': 'resp_fixture'}},
            {'type': 'response.output_text.delta', 'delta': 'DONE'},
            {'type': 'response.completed', 'response': response_payload(text='DONE')}),
            content_type='text/event-stream')
        chunks = list(self.backend().stream([Message('user', 'hi')], max_tokens=512))
        self.assertEqual(chunks[0].text, 'DONE')
        self.assertEqual(chunks[-1].response.finish_reason, 'stop')
        self.assertEqual(chunks[-1].response.usage['total_tokens'], 25)
        self.model.add(response_payload(call=True, status='incomplete'))
        reply = self.backend().request([Message('user', 'hi')], max_tokens=512)
        self.assertEqual(reply.finish_reason, 'length')

    def test_interrupted_stream_preserves_text_without_replay_or_executable_calls(self):
        self.model.add(sse({'type': 'response.created', 'response': {'id': 'resp_fixture'}},
            {'type': 'response.output_text.delta', 'delta': 'partial'},
            {'type': 'response.output_item.added', 'item': {'type': 'function_call'}}),
            content_type='text/event-stream')
        with self.assertRaises(LocalBackendError) as failed:
            list(self.backend().stream([Message('user', 'hi')]))
        self.assertFalse(failed.exception.retryable)
        self.assertEqual(failed.exception.response.message.content, 'partial')
        self.assertEqual(failed.exception.response.message.tool_calls, [])
        self.assertEqual(failed.exception.response.finish_reason, 'stream_interrupted')

    def test_core_task_reads_real_file_and_restores_without_replaying(self):
        self._core_file_restore('legacy')

    def test_v5_core_request_prefix_and_diagnostics_survive_real_file_task_and_restore(self):
        self._core_file_restore('v5')

    def _core_file_restore(self, engine):
        self.model.add(response_payload(call=True))
        final_payload = response_payload(text='PUBLIC-FIXTURE-FACT')
        final_payload['input_transformations'] = []
        self.model.add(final_payload)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'fact.txt').write_text('PUBLIC-FIXTURE-FACT')
            config = {'schema_version': 1, 'port': 0, 'data_dir': str(root / 'data'),
                'clients': [{'subject': 'fixture', 'token_env': 'LP_OPENAI_CLIENT'}],
                'routes': {'localpilot': {'workspace': str(workspace), 'permissions': 'approve-mutations', 'engine': engine,
                    'capabilities': {'read': True, 'write': False, 'execute': False, 'read_only': True},
                    'backend': {'kind': 'openai', 'protocol': 'responses', 'model': 'mock-local',
                                'base_url': self.model.base_url, 'capabilities': {'streaming': False}},
                    'cloud_egress': 'CLOUD_ALLOWED', 'budgets': {'max_output_tokens': 512}}}}
            path = root / 'service.json'
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            servers = []
            try:
                for index in range(2):
                    server = build(path)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    servers.append((server, thread))
                    thread.start()
                    client = Client(f'http://127.0.0.1:{server.server_port}', token='o' * 32)
                    task = client.submit('Read fact.txt', idempotency_key='responses-fixture')
                    if index == 0:
                        task_id = task['id']
                        server.service.wait(task_id)
                        final = client.status(task_id)
                        self.assertEqual(final['status'], 'completed', final.get('error'))
                        self.assertEqual(final['tools'][0]['payload']['result'], 'PUBLIC-FIXTURE-FACT')
                        calls = final['result']['model_calls']
                        self.assertEqual(calls[0]['provider_diagnostics'], {'response_id': 'resp_fixture'})
                        self.assertEqual(calls[-1]['provider_diagnostics'],
                                         {'response_id': 'resp_fixture', 'input_transformations': []})
                        if engine == 'v5':
                            first_request, second_request = self.model.requests
                            self.assertEqual(second_request['input'][:len(first_request['input'])],
                                             first_request['input'])
                            self.assertEqual(first_request['tools'], second_request['tools'])
                        server.service.suspend()
                        server.shutdown()
                        thread.join(2)
                    else:
                        self.assertEqual(task['id'], task_id)
                        self.assertEqual(len(self.model.requests), 2)
                        self.assertEqual(client.status(task_id)['result']['model_calls'], calls)
            finally:
                for server, thread in reversed(servers):
                    if thread.is_alive():
                        server.shutdown()
                    thread.join(2)
                    if not server.service.closed:
                        server.service.shutdown()
                    server.server_close()
                    server.access.close()


if __name__ == '__main__':
    unittest.main()
