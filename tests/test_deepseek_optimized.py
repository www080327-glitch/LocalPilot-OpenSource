"""Protocol fault injection; scripted HTTP fixtures, never real model claims."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from agent.backends import Message, ToolCall
from agent.deepseek import DeepSeekBackend, DeepSeekStreamError
from agent.deepseek_optimized import DeepSeekOptimizedBackend
from localpilot_service.backend_contract import ServiceDeepSeekOptimizedBackend
from tests.test_runtime_backends import FakeResponse, sse


class DeepSeekOptimizedTests(unittest.TestCase):
    def setUp(self):
        self.backend = DeepSeekOptimizedBackend(api_key="synthetic-key")

    def test_none_disables_thinking_without_unsupported_effort(self):
        payload = self.backend._payload([Message("user", "hi")], thinking="none")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(DeepSeekBackend(api_key="fake")._payload([], thinking="none")["reasoning_effort"], "none")

    def test_high_uses_explicit_enabled(self):
        for effort in ["low", "high", "max"]:
            body = self.backend._payload([], thinking=effort)
            self.assertEqual(body["thinking"], {"type": "enabled"})
            self.assertEqual(body["reasoning_effort"], effort)
        with self.assertRaises(ValueError):
            self.backend._payload([], thinking="ultra")

    def test_conditional_replay_keeps_all_reasoning_with_tools(self):
        messages = [Message("assistant", "answer", reasoning_content="reasoning")]
        before = deepcopy(messages)
        self.assertEqual(self.backend._payload(messages, tools=[])["messages"][0]["reasoning_content"], "reasoning")
        self.assertNotIn("reasoning_content", self.backend._payload(messages)["messages"][0])
        self.assertEqual(messages, before)

    def test_tool_schema_canonical_order_has_no_inventory_or_logs(self):
        tools = [{"type":"function", "function":{"name":name,"parameters":{"type":"object"}}} for name in ["z","a"]]
        before = deepcopy(tools)
        payload = self.backend._payload([], tools)
        self.assertEqual([t["function"]["name"] for t in payload["tools"]], ["a", "z"])
        self.assertEqual(tools, before)
        self.assertFalse(any(k.startswith("dsh_") for k in payload))

    def test_pairing_rejects_orphans_missing_and_duplicate_results(self):
        call = Message("assistant", tool_calls=[ToolCall("c", "read_file", "{}")])
        result = Message("tool", "ok", tool_call_id="c")
        for messages in [[result], [call], [call, Message("user", "new"), result], [call, result, result],
                         [Message("assistant", tool_calls=call.tool_calls*2), result]]:
            with self.assertRaises(ValueError): self.backend._payload(messages)
        self.backend._payload([call, Message("system", "current authority"), result])

    def test_no_repair_of_invalid_tool_arguments(self):
        call = Message("assistant", tool_calls=[ToolCall("c", "read_file", "{invalid")])
        payload = self.backend._payload([call, Message("tool", "Gateway: invalid JSON", tool_call_id="c")])
        self.assertEqual(payload["messages"][0]["tool_calls"][0]["function"]["arguments"], "{invalid")

    def test_unterminated_done_frame_never_releases_response(self):
        raw = b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\ndata: [DONE]'
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(raw)):
            chunks = []
            with self.assertRaises(DeepSeekStreamError):
                for chunk in self.backend.stream([]): chunks.append(chunk)
        self.assertFalse(any(chunk.response for chunk in chunks))

    def test_comments_crlf_usage_and_fragmented_tools(self):
        frames = sse({"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c","function":{"name":"read_file","arguments":'{"path":'}}]}}]},
                     {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":'"a"}'}}]},"finish_reason":"tool_calls"}]},
                     {"choices":[],"usage":{"prompt_tokens":1500,"prompt_cache_hit_tokens":1024,"completion_tokens":12}})
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(b': heartbeat\r\n\r\n'+frames.replace(b'\n',b'\r\n'))):
            response = list(self.backend.stream([]))[-1].response
        self.assertEqual(json.loads(response.message.tool_calls[0].arguments), {"path":"a"})
        self.assertEqual(response.usage["prompt_cache_hit_tokens"], 1024)

    def test_duplicate_response_identity_and_negative_index_are_rejected(self):
        for calls in [[{"index":-1,"id":"c","function":{"name":"read_file","arguments":"{}"}}],
                      [{"index":i,"id":"c","function":{"name":"read_file","arguments":"{}"}} for i in [0,1]]]:
            raw = sse({"choices":[{"delta":{"tool_calls":calls},"finish_reason":"tool_calls"}]})
            with patch("agent.deepseek.urlopen", return_value=FakeResponse(raw)):
                with self.assertRaises(DeepSeekStreamError): list(self.backend.stream([]))

    def test_service_configuration_fingerprint_distinguishes_engine(self):
        backend = ServiceDeepSeekOptimizedBackend(api_key="fake", generation_parameters={"temperature":0})
        self.assertEqual(backend.service_contract["agent_engine"], "deepseek_optimized")
        self.assertEqual(backend._payload([],thinking="none")["temperature"], 0)

    def test_token_budget_is_not_silently_expanded(self):
        self.assertEqual(self.backend._payload([],max_tokens=123)["max_tokens"],123)
        for value in [0,-1,True,1.2]:
            with self.assertRaises(ValueError):self.backend._payload([],max_tokens=value)


if __name__ == "__main__": unittest.main()
