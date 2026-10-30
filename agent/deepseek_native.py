"""Public DeepSeek Messages provider; no tool execution or DSH client identity.

Serialization, source-bound replay and streaming lifecycle adapted from
DeepSeek Harness serialize.ts/replay.ts/translate.ts/sse.ts at
687f282e8625c6b8d11ff58211a90524be2e4317. Copyright (c) 2026 DeepSeek.
MIT license and attribution: third_party/deepseek-harness/.
"""
from copy import deepcopy
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .backends import BackendChunk, BackendResponse, Message, ToolCall
from .deepseek import DeepSeekBackend, DeepSeekAPIError, DeepSeekStreamError, urlopen
from .deepseek_optimized import DeepSeekOptimizedBackend


def _error(detail):
    return DeepSeekStreamError('DeepSeek Messages: ' + detail, retryable=False)


def _object(value):
    if not isinstance(value, dict):
        raise _error('expected JSON object')
    return value


def _string(value):
    if not isinstance(value, str):
        raise _error('expected string')
    return value


def _identity(message):
    body = message.to_dict(include_reasoning=True)
    body.pop('native_replay', None)
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def native_usage(raw):
    """Messages input excludes cached reads/writes. Preserve unknowns as None."""
    raw = _object(raw)
    for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
        if key in raw and (type(raw[key]) is not int or raw[key] < 0):
            raise _error('invalid usage counter')
    # Missing cache fields mean unknown, not a measured zero.
    uncached, hit, write = (raw.get(k) for k in
        ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
    complete = all(v is not None for v in (uncached, hit, write))
    return {'prompt_tokens': uncached + hit + write if complete else None,
            'completion_tokens': raw.get('output_tokens'),
            'prompt_cache_hit_tokens': hit,
            'prompt_cache_miss_tokens': uncached + write if complete else None,
            'provider_usage': deepcopy(raw), 'usage_protocol': 'deepseek_messages',
            'reasoning_tokens': None}


class DeepSeekNativeBackend(DeepSeekBackend):
    """Text/tool Messages protocol. Images, Files and server tools unsupported."""
    engine = 'deepseek_native'
    service_reasoning_replay = True
    service_receipt_refs = True

    def __init__(self, *args, base_url='https://api.deepseek.com/anthropic', **kwargs):
        super().__init__(*args, base_url=base_url, **kwargs)
        self.supports_in_history_system_prompt = False

    def _assistant(self, message):
        replay = message.native_replay
        if (isinstance(replay, dict) and replay.get('kind') == 'deepseek_messages_v1'
                and replay.get('model') == self.model and replay.get('sha256') == _identity(message)):
            try:
                blocks = []
                text_at = reasoning_at = call_at = 0
                for item in replay['blocks']:
                    kind = item['type']
                    if kind in {'text', 'thinking'}:
                        source = message.content or '' if kind == 'text' else message.reasoning_content or ''
                        start, end = item['start'], item['end']
                        if (type(start) is not int or type(end) is not int or start < 0 or
                                end < start or end > len(source) or start != (text_at if kind == 'text' else reasoning_at)):
                            raise ValueError('invalid replay range')
                        if kind == 'text':
                            blocks.append({'type': kind, 'text': source[start:end]}); text_at = end
                        else:
                            block = {'type': kind, 'thinking': source[start:end]}; reasoning_at = end
                            if 'signature' in item: block['signature'] = _string(item['signature'])
                            blocks.append(block)
                    elif kind == 'tool_use' and item['call'] == call_at:
                        call = message.tool_calls[call_at]; call_at += 1
                        blocks.append(self._tool_block(call))
                    else:
                        raise ValueError('invalid replay block')
                if (text_at != len(message.content or '') or reasoning_at != len(message.reasoning_content or '')
                        or call_at != len(message.tool_calls)):
                    raise ValueError('incomplete replay')
                return blocks
            except (KeyError, IndexError, TypeError, ValueError, DeepSeekStreamError):
                pass  # Never replay an unbound or malformed signature.
        blocks = []
        if message.reasoning_content:
            blocks.append({'type': 'thinking', 'thinking': message.reasoning_content})
        if message.content: blocks.append({'type': 'text', 'text': message.content})
        blocks.extend(self._tool_block(c) for c in message.tool_calls)
        return blocks

    @staticmethod
    def _tool_block(call):
        # Historical invalid proposals were rejected by Gateway. As upstream,
        # only their wire projection uses {}; canonical arguments stay intact.
        try: value = json.loads(call.arguments)
        except (ValueError, TypeError): value = None
        return {'type': 'tool_use', 'id': call.id, 'name': call.name,
                'input': value if isinstance(value, dict) else {}}

    def _payload(self, messages, tools=None, thinking=None, max_tokens=None, stream=False):
        history = [m if isinstance(m, Message) else Message.from_dict(m) for m in messages]
        DeepSeekOptimizedBackend._validate_history([m.to_dict() for m in history])
        effort = self.thinking_mapping(thinking)['provider_value'] or 'high'
        if type(max_tokens) is not int or max_tokens < 1:
            if max_tokens is not None: raise ValueError('max_tokens must be a positive integer')
            max_tokens = 8192
        wire, system = [], []
        for message in history:
            if message.role == 'system':
                system.append(message.content or ''); continue
            if message.role == 'assistant': blocks = self._assistant(message)
            elif message.role == 'tool':
                blocks = [{'type': 'tool_result', 'tool_use_id': message.tool_call_id,
                           'content': [{'type': 'text', 'text': message.content or ''}]}]
            elif message.role == 'user':
                blocks = [{'type': 'text', 'text': message.content or ''}]
            else: raise ValueError('Unsupported Messages role')
            if not blocks: continue
            role = 'user' if message.role == 'tool' else message.role
            if wire and wire[-1]['role'] == role: wire[-1]['content'].extend(blocks)
            else: wire.append({'role': role, 'content': blocks})
        # Results precede regular text within each merged user turn.
        for message in wire:
            if message['role'] == 'user':
                message['content'].sort(key=lambda b: b['type'] != 'tool_result')
        payload = {'model': self.model, 'messages': wire, 'max_tokens': max_tokens,
                   'stream': stream, 'thinking': {'type': 'disabled' if effort == 'none' else 'enabled'}}
        if system: payload['system'] = '\n\n'.join(system)
        if effort != 'none': payload['output_config'] = {'effort': effort}
        if tools is not None:
            payload['tools'] = [{'name': t['function']['name'], 'description': t['function'].get('description', ''),
                                 'input_schema': deepcopy(t['function']['parameters'])}
                                for t in sorted(tools, key=lambda s: s['function']['name'])]
        return payload

    def _open(self, payload):
        self.data_policy.check_cloud_send()
        root = self.base_url if self.base_url.endswith('/v1') else self.base_url + '/v1'
        request = Request(root + '/messages', data=json.dumps(payload).encode(), method='POST',
                          headers={'x-api-key': self.api_key, 'Content-Type': 'application/json',
                                   'anthropic-version': '2023-06-01'})
        try: return urlopen(request, timeout=self.timeout)
        except HTTPError as error:
            raise DeepSeekAPIError('DeepSeek Messages returned HTTP ' + str(error.code), status_code=error.code) from None
        except URLError as error:
            from .retry import is_transient_error
            failure = DeepSeekAPIError('Could not reach DeepSeek Messages (' + type(error.reason).__name__ + ')')
            failure.retryable = is_transient_error(error)
            raise failure from None

    @staticmethod
    def _events(response):
        lines = []
        for raw in response:
            try: line = raw.decode('utf-8').rstrip('\r\n')
            except UnicodeError: raise _error('invalid UTF-8') from None
            if not line:
                if lines:
                    try: event = _object(json.loads('\n'.join(lines)))
                    except (ValueError, TypeError): raise _error('invalid SSE JSON') from None
                    if event.get('type') == 'error': raise _error('provider stream error')
                    yield event
                    lines = []
            elif line.startswith('data:'):
                data = line[5:]; lines.append(data[1:] if data.startswith(' ') else data)
        if lines: raise _error('unterminated SSE frame')

    def _assemble(self, events):
        blocks, raw_usage, started, reason, model = {}, {}, False, None, None
        for event in events:
            event = _object(event); kind = event.get('type')
            if kind == 'error': raise _error('provider stream error')
            if kind == 'message_start':
                if started: raise _error('duplicate message_start')
                message = _object(event.get('message'))
                raw_usage.update(_object(message.get('usage')))
                model = message.get('model'); started = True
                continue
            if kind not in {'content_block_start', 'content_block_delta', 'content_block_stop', 'message_delta', 'message_stop'}:
                continue
            if not started: raise _error('event before message_start')
            if kind.startswith('content_block_'):
                index = event.get('index')
                if type(index) is not int or index < 0: raise _error('invalid block index')
                if reason is not None: raise _error('block after stop reason')
                if kind == 'content_block_start':
                    if index in blocks: raise _error('duplicate block index')
                    block = deepcopy(_object(event.get('content_block')))
                    if block.get('type') == 'text': _string(block.get('text'))
                    elif block.get('type') == 'thinking':
                        _string(block.get('thinking'))
                        if 'signature' in block: _string(block['signature'])
                    elif block.get('type') == 'tool_use':
                        if not _string(block.get('id')) or not _string(block.get('name')): raise _error('empty tool identity')
                        _object(block.get('input'))
                    else: raise _error('unsupported response block')
                    blocks[index] = {'block': block, 'closed': False, 'json': ''}
                    if block['type'] in {'text', 'thinking'} and block[block['type']]:
                        yield BackendChunk('text' if block['type'] == 'text' else 'reasoning', block[block['type']])
                else:
                    item = blocks.get(index)
                    if item is None or item['closed']: raise _error('delta/stop without open block')
                    block = item['block']
                    if kind == 'content_block_stop':
                        item['closed'] = True
                        if block['type'] == 'tool_use' and item['json']:
                            block['arguments'] = item['json']
                        continue
                    delta = _object(event.get('delta')); dtype = delta.get('type')
                    if dtype == 'text_delta' and block['type'] == 'text':
                        value = _string(delta.get('text')); block['text'] += value; yield BackendChunk('text', value)
                    elif dtype == 'thinking_delta' and block['type'] == 'thinking':
                        value = _string(delta.get('thinking')); block['thinking'] += value; yield BackendChunk('reasoning', value)
                    elif dtype == 'signature_delta' and block['type'] == 'thinking':
                        block['signature'] = block.get('signature', '') + _string(delta.get('signature'))
                    elif dtype == 'input_json_delta' and block['type'] == 'tool_use': item['json'] += _string(delta.get('partial_json'))
                    else: raise _error('delta type mismatch')
            elif kind == 'message_delta':
                stop = _object(event.get('delta')).get('stop_reason')
                if stop is not None:
                    mapped = {'end_turn': 'stop', 'stop_sequence': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length'}
                    if stop not in mapped or reason is not None: raise _error('unsupported or duplicate stop reason')
                    reason = mapped[stop]
                if 'usage' in event: raw_usage.update(_object(event['usage']))
            else:
                if reason is None or any(not b['closed'] for b in blocks.values()): raise _error('unsettled message_stop')
                text, thinking, calls, replay = '', '', [], []
                for item in blocks.values():
                    b = item['block']; btype = b['type']
                    if btype == 'text':
                        replay.append({'type': 'text', 'start': len(text), 'end': len(text) + len(b['text'])}); text += b['text']
                    elif btype == 'thinking':
                        entry = {'type': 'thinking', 'start': len(thinking), 'end': len(thinking) + len(b['thinking'])}
                        if 'signature' in b: entry['signature'] = b['signature']
                        replay.append(entry); thinking += b['thinking']
                    else:
                        arguments = b.get('arguments', json.dumps(b['input'], ensure_ascii=False))
                        if reason != 'length':
                            try: _object(json.loads(arguments))
                            except (ValueError, TypeError): raise _error('invalid tool JSON') from None
                        replay.append({'type': 'tool_use', 'call': len(calls)})
                        calls.append(ToolCall(b['id'], b['name'], arguments))
                if len({c.id for c in calls}) != len(calls): raise _error('duplicate tool identities')
                if reason != 'length' and (bool(calls) != (reason == 'tool_calls')): raise _error('inconsistent tool stop reason')
                if not blocks and reason == 'stop': raise _error('empty response')
                message = Message('assistant', text or None, calls, reasoning_content=thinking or None)
                message.native_replay = {'kind': 'deepseek_messages_v1', 'model': self.model,
                                         'sha256': _identity(message), 'blocks': replay}
                yield BackendChunk('response', response=BackendResponse(message, native_usage(raw_usage), model, reason))
                return
        raise _error('stream ended before message_stop')

    def stream(self, messages, tools=None, thinking=None, max_tokens=None):
        with self._open(self._payload(messages, tools, thinking, max_tokens, stream=True)) as response:
            yield from self._assemble(self._events(response))

    def request(self, messages, tools=None, thinking=None, max_tokens=None):
        with self._open(self._payload(messages, tools, thinking, max_tokens)) as response:
            data = _object(json.loads(response.read().decode('utf-8')))
        events = [{'type': 'message_start', 'message': data}]
        for index, block in enumerate(data.get('content', [])):
            events.extend([{'type': 'content_block_start', 'index': index, 'content_block': block},
                           {'type': 'content_block_stop', 'index': index}])
        events.extend([{'type': 'message_delta', 'delta': {'stop_reason': data.get('stop_reason')}}, {'type': 'message_stop'}])
        for chunk in self._assemble(events):
            if chunk.response is not None: return chunk.response
