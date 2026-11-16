"""OpenAI Responses transport with stateless, source-bound reasoning replay."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import re
from urllib.request import build_opener

from .backends import BackendChunk, BackendResponse, Message, ToolCall
from .cloud_credentials import resolve_openai_key
from .deepseek import DeepSeekBackend
from .local_http import LocalBackendError, LocalHTTPBackend, _NoRedirect


class OpenAIResponsesBackend(LocalHTTPBackend):
    is_local = False
    provider = 'openai'
    service_reasoning_replay = True

    def __init__(self, *, base_url='https://api.openai.com/v1', api_key=None,
                 key_file=None, **options):
        if not isinstance(base_url, str) or not base_url.startswith('https://'):
            raise ValueError('OpenAI requires HTTPS')
        if options.get('chat_template_kwargs'):
            raise ValueError('OpenAI does not accept local chat template overrides')
        options.update(allow_remote=True, service_location='remote')
        if options.get('supports_reasoning') is None:
            options['supports_reasoning'] = True
        if options['supports_reasoning'] and not options.get('reasoning_efforts'):
            efforts = ('low', 'medium', 'high', 'xhigh', 'max')
            if re.fullmatch(r'gpt-5\.5(?:-\d{4}-\d{2}-\d{2})?', options['model']):
                efforts = ('none', 'low', 'medium', 'high', 'xhigh')
            elif options['model'].startswith(('gpt-6-luna', 'gpt-6-sol', 'gpt-6.1-terra')):
                efforts = ('none',) + efforts
            options['reasoning_efforts'] = efforts
        super().__init__(base_url=base_url,
                         api_key=resolve_openai_key(api_key, key_file=key_file), **options)
        self._opener = build_opener(_NoRedirect())
        self.capabilities = replace(self.capabilities, supports_parallel_tool_calls=True)

    def _payload(self, messages, tools=None, max_tokens=None, stream=False, thinking=None):
        history = [message if isinstance(message, Message) else Message.from_dict(message)
                   for message in messages]
        payload = {'model': self.model, 'input': [], 'store': False, 'stream': stream}
        for message in history:
            payload['input'].extend(self._input_items(message))
        if tools is not None and self.capabilities.supports_tool_calling:
            # Preserve optional parameters in the product's canonical tool schema.
            payload['tools'] = [{'type': 'function', **deepcopy(tool['function']), 'strict': False}
                                for tool in tools]
        if max_tokens is not None:
            if type(max_tokens) is not int or max_tokens < 1:
                raise ValueError('max_tokens must be a positive integer')
            payload['max_output_tokens'] = max_tokens
        if thinking is not None:
            payload['reasoning'] = {'effort': self.thinking_mapping(thinking)['provider_value']}
        return payload

    def _input_items(self, message):
        if message.role == 'tool':
            return [{'type': 'function_call_output', 'call_id': message.tool_call_id,
                     'output': message.content or ''}]
        replay = message.native_replay
        if (message.role == 'assistant' and replay and replay.get('kind') == 'openai_responses_v1'
                and replay.get('model') == self.model and replay.get('base_url') == self.base_url
                and replay.get('sha256') == _message_hash(message)):
            return deepcopy(replay['items'])
        items = []
        if message.content is not None:
            content = message.content
            if isinstance(content, list):
                if not self.capabilities.supports_vision:
                    raise LocalBackendError('Provider vision capability is not explicitly enabled', retryable=False)
                content = [_input_content(part) for part in content]
            items.append({'role': message.role, 'content': content})
        items.extend({'type': 'function_call', 'call_id': call.id, 'name': call.name,
                      'arguments': call.arguments} for call in message.tool_calls)
        return items

    def _response(self, data):
        try:
            if not isinstance(data, dict) or not isinstance(data.get('output'), list):
                raise ValueError('missing output items')
            status = data['status']
            if status not in {'completed', 'incomplete'} or data.get('error'):
                raise ValueError('provider did not complete a response')
            text, summaries, calls, items = [], [], [], []
            for raw in data['output']:
                item = deepcopy(raw)
                kind = item['type']
                if kind == 'message':
                    if item['role'] != 'assistant':
                        raise ValueError('non-assistant output')
                    for part in item['content']:
                        if part['type'] == 'output_text':
                            text.append(part['text'])
                        elif part['type'] == 'refusal':
                            text.append(part['refusal'])
                        else:
                            raise ValueError('unsupported message content')
                elif kind == 'function_call':
                    calls.append(ToolCall(item['call_id'], item['name'], item['arguments']))
                elif kind == 'reasoning':
                    summaries.extend(part['text'] for part in item.get('summary', []))
                else:
                    raise ValueError('unsupported response output')
                # Usage, annotations and provider-only progress fields are not inputs.
                if kind == 'message':
                    item = {key: item[key] for key in ('type', 'role', 'content', 'phase') if key in item}
                    item['content'] = [{key: part[key] for key in ('type', 'text', 'refusal') if key in part}
                                       for part in item['content']]
                elif kind == 'function_call':
                    item = {key: item[key] for key in ('type', 'call_id', 'name', 'arguments')}
                else:
                    item = {key: item[key] for key in ('type', 'id', 'summary', 'encrypted_content') if key in item}
                items.append(item)
            message = Message('assistant', ''.join(text) or None, calls,
                              reasoning_content=''.join(summaries) or None)
            self._validate_message(message)
            reason = ('tool_calls' if calls else 'stop') if status == 'completed' else (
                'length' if (data.get('incomplete_details') or {}).get('reason') == 'max_output_tokens'
                else 'content_filter')
            message.native_replay = {'kind': 'openai_responses_v1', 'model': self.model,
                                     'base_url': self.base_url, 'sha256': _message_hash(message), 'items': items}
            return BackendResponse(message, _usage(data.get('usage')), data.get('model'), reason)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise LocalBackendError('Malformed OpenAI Responses result', retryable=False) from error

    def request(self, messages, tools=None, thinking=None, max_tokens=None):
        with self._open('/responses', self._payload(messages, tools, max_tokens, thinking=thinking)) as response:
            try:
                data = json.loads(response.read().decode('utf-8'))
            except (ValueError, UnicodeError) as error:
                raise LocalBackendError('Malformed OpenAI Responses JSON', retryable=False) from error
        return self._response(data)

    def stream(self, messages, tools=None, thinking=None, max_tokens=None):
        text, summaries = [], []
        started = False
        try:
            with self._open('/responses', self._payload(messages, tools, max_tokens, stream=True, thinking=thinking)) as response:
                for raw in DeepSeekBackend._events(response):
                    event = json.loads(raw)
                    kind = event['type']
                    started = True
                    if kind in {'response.completed', 'response.incomplete'}:
                        yield BackendChunk('response', response=self._response(event['response']))
                        return
                    if kind in {'error', 'response.failed'}:
                        raise LocalBackendError('OpenAI Responses stream failed', retryable=False)
                    if kind in {'response.output_text.delta', 'response.refusal.delta',
                                'response.reasoning_summary_text.delta'}:
                        delta = event['delta']
                        if not isinstance(delta, str):
                            raise ValueError('non-text delta')
                        reasoning = kind == 'response.reasoning_summary_text.delta'
                        (summaries if reasoning else text).append(delta)
                        yield BackendChunk('reasoning' if reasoning else 'text', delta)
        except Exception as error:
            if not started and isinstance(error, LocalBackendError):
                raise
            raise LocalBackendError('OpenAI Responses stream interrupted; no replay', retryable=False,
                                    response=_partial(text, summaries)) from error
        raise LocalBackendError('OpenAI Responses stream ended without a terminal response',
                                retryable=not started, response=_partial(text, summaries))


def _message_hash(message):
    value = message.to_dict(include_reasoning=True)
    value.pop('native_replay', None)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def _input_content(part):
    if part['type'] == 'text':
        return {'type': 'input_text', 'text': part['text']}
    if part['type'] == 'image_url':
        image = part['image_url']
        return {'type': 'input_image', 'image_url': image['url'],
                **({'detail': image['detail']} if 'detail' in image else {})}
    raise ValueError('Unsupported OpenAI input content')


def _usage(raw):
    if raw is None:
        return None
    normalized = {'prompt_tokens': raw.get('input_tokens'), 'completion_tokens': raw.get('output_tokens'),
                  'total_tokens': raw.get('total_tokens'), 'provider_usage': deepcopy(raw)}
    if raw.get('input_tokens_details') is not None:
        normalized['prompt_tokens_details'] = raw['input_tokens_details']
    if raw.get('output_tokens_details') is not None:
        normalized['completion_tokens_details'] = raw['output_tokens_details']
    return LocalHTTPBackend._usage({'usage': normalized})


def _partial(text, summaries):
    return BackendResponse(Message('assistant', ''.join(text) or None,
                                   reasoning_content=''.join(summaries) or None),
                           finish_reason='stream_interrupted')
