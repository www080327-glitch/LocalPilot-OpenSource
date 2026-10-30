import io
import json
import unittest
from unittest.mock import patch

from agent.backends import Message, ToolCall
from agent.deepseek_native import DeepSeekNativeBackend, native_usage
from agent.deepseek import DeepSeekStreamError


def events(blocks=None, stop='end_turn'):
    result = [{'type': 'message_start', 'message': {'model': 'deepseek-flash', 'usage': {
        'input_tokens': 11, 'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 0}}}]
    for i, block in enumerate(blocks or [{'type': 'text', 'text': 'hello'}]):
        result += [{'type': 'content_block_start', 'index': i, 'content_block': block},
                   {'type': 'content_block_stop', 'index': i}]
    return result + [{'type': 'message_delta', 'delta': {'stop_reason': stop}, 'usage': {'output_tokens': 7}}, {'type': 'message_stop'}]


class NativeTests(unittest.TestCase):
    def setUp(self): self.backend = DeepSeekNativeBackend(api_key='synthetic-test-only')
    def response(self, seq): return list(self.backend._assemble(seq))[-1].response

    def test_default_output_budget_can_hold_a_report_and_chart_tool_call(self):
        self.assertEqual(self.backend._payload([Message("user", "task")], thinking="none")["max_tokens"],8192)
        self.assertEqual(self.backend._payload([Message("user", "task")], thinking="none",max_tokens=128)["max_tokens"],128)

    def test_wire_thinking_tools_and_pairing(self):
        history = [Message('system', 'fixed'), Message('user', 'task'),
                   Message('assistant', tool_calls=[ToolCall('a', 'read_file', '{"path":"a"}')]),
                   Message('tool', 'result', tool_call_id='a')]
        wire = self.backend._payload(history, [], 'none', 100)
        self.assertEqual(wire['thinking'], {'type': 'disabled'})
        self.assertNotIn('output_config', wire)
        self.assertEqual(wire['messages'][-1]['content'][0]['tool_use_id'], 'a')
        self.assertEqual(wire['system'], 'fixed')
        with self.assertRaises(ValueError): self.backend._payload(history[:-1])

    def test_high_effort_and_unknown_effort(self):
        self.assertEqual(self.backend._payload([Message('user', 'x')], thinking='high')['output_config'], {'effort': 'high'})
        with self.assertRaises(ValueError): self.backend._payload([], thinking='medium')

    def test_usage_does_not_drop_cache_reads(self):
        usage = self.response(events()).usage
        self.assertEqual(usage['prompt_tokens'], 111)
        self.assertEqual(usage['prompt_cache_miss_tokens'], 11)
        self.assertIsNone(usage['reasoning_tokens'])
        self.assertIsNone(native_usage({'input_tokens': 11})['prompt_tokens'])
        with self.assertRaises(DeepSeekStreamError): native_usage({'output_tokens': True})

    def test_replay_is_bound_and_persists(self):
        message = self.response(events([{'type': 'thinking', 'thinking': 'r', 'signature': 'sig'}, {'type': 'text', 'text': 'x'}])).message
        restored = Message.from_dict(message.to_dict(include_reasoning=True))
        self.assertEqual(self.backend._assistant(restored)[0]['signature'], 'sig')
        restored.content = 'tampered'
        self.assertNotIn('signature', self.backend._assistant(restored)[0])
        self.backend.model = 'another-model'
        self.assertNotIn('signature', self.backend._assistant(message)[0])
        self.assertNotIn('native_replay', message.to_dict())

    def test_native_block_order_and_fragment_assembly(self):
        seq = events([{'type': 'thinking', 'thinking': '', 'signature': ''},
                      {'type': 'text', 'text': 'observing'}, {'type': 'tool_use', 'id': 'a', 'name': 'read_file', 'input': {}}], 'tool_use')
        seq.insert(2, {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'r'}})
        at = next(i for i,e in enumerate(seq) if e.get('index') == 2 and e['type'] == 'content_block_stop')
        seq.insert(at, {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '{"path":"a"}'}})
        response = self.response(seq)
        self.assertEqual(response.message.tool_calls[0].arguments, '{"path":"a"}')
        self.assertEqual([b['type'] for b in self.backend._assistant(response.message)], ['thinking', 'text', 'tool_use'])

    def test_stream_faults_never_release_response(self):
        variants = [events()[:-1], events()[:1] + events(), events()[1:],
                    events()[:2] + [events()[1]] + events()[2:]]
        for seq in variants:
            responses = []
            with self.assertRaises(DeepSeekStreamError):
                for chunk in self.backend._assemble(seq):
                    if chunk.response: responses.append(chunk.response)
            self.assertEqual(responses, [])

    def test_duplicate_tool_ids_and_bad_json(self):
        blocks = [{'type': 'tool_use', 'id': 'a', 'name': 'x', 'input': {}}] * 2
        with self.assertRaises(DeepSeekStreamError): self.response(events(blocks, 'tool_use'))
        seq = events(blocks[:1], 'tool_use')
        seq.insert(2, {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': '{'}})
        with self.assertRaises(DeepSeekStreamError): self.response(seq)
        seq[-2]['delta']['stop_reason'] = 'max_tokens'
        response = self.response(seq)
        self.assertEqual(response.finish_reason, 'length')

    def test_unterminated_sse_rejected(self):
        with self.assertRaises(DeepSeekStreamError): list(self.backend._events([b'data: {}\n']))
        self.assertEqual(list(self.backend._events([b': ping\n', b'data: {}\n', b'\n'])), [{}])

    def test_public_transport_headers_only(self):
        with patch('agent.deepseek_native.urlopen', return_value=io.BytesIO()) as opened:
            self.backend._open({'model': 'deepseek-flash'})
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.deepseek.com/anthropic/v1/messages')
        self.assertEqual(set(dict(request.header_items())), {'X-api-key', 'Content-type', 'Anthropic-version'})

    def test_nonstream_uses_same_validation(self):
        data = {'model': 'deepseek-flash', 'content': [{'type': 'text', 'text': 'ok'}],
                'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 2,
                    'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}
        with patch.object(self.backend, '_open', return_value=io.BytesIO(json.dumps(data).encode())):
            self.assertEqual(self.backend.request([Message('user', 'x')]).message.content, 'ok')


if __name__ == '__main__': unittest.main()
