"""Offline contract tests for backend conversion, streaming, and retries."""

import io
import json
import ssl
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from agent.backends import LocalBackend, LocalBackendUnavailable, Message
from agent.deepseek import DeepSeekBackend, DeepSeekStreamError, SafeRedirectHandler
from agent.retry import RetryPolicy, call_with_retry


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body

    def __iter__(self):
        return iter(self.body.splitlines(keepends=True))


def sse(*chunks, done=True):
    events = ["data: " + json.dumps(chunk) + "\n\n" for chunk in chunks]
    if done:
        events.append("data: [DONE]\n\n")
    return "".join(events).encode()


class BackendContractTests(unittest.TestCase):
    def test_message_conversion_preserves_reasoning_for_provider_only(self):
        message = Message.from_dict({
            "role": "assistant", "content": None, "reasoning_content": "private",
            "tool_calls": [{"id": "c", "type": "function", "index": 0,
                            "function": {"name": "read_file", "arguments": '{"path":"a"}',
                                         "extra": "drop"}}],
        })
        self.assertEqual(message.to_dict(), {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c", "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"a"}'}}],
        })
        self.assertEqual(message.reasoning_content, "private")
        self.assertEqual(message.to_dict(include_reasoning=True)["reasoning_content"], "private")

    def test_local_placeholder_is_unavailable(self):
        backend = LocalBackend()
        self.assertTrue(backend.is_local)
        self.assertFalse(backend.health_check())
        with self.assertRaises(LocalBackendUnavailable):
            backend.request([])
        with self.assertRaises(LocalBackendUnavailable):
            backend.stream([])

    def test_deepseek_request_normalizes_and_sends_supported_parameters(self):
        backend = DeepSeekBackend(api_key="fake")
        body = {"model": "deepseek-flash", "usage": {"prompt_tokens": 3},
                "choices": [{"message": {"role": "assistant", "content": "hello",
                                         "reasoning_content": "hidden"}}]}
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(json.dumps(body).encode())) as opened:
            answer = backend.request([Message("user", "hi")], thinking="high", max_tokens=50)
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["max_tokens"], 50)
        self.assertEqual(answer.message.to_dict(), {"role": "assistant", "content": "hello"})
        self.assertEqual(answer.message.reasoning_content, "hidden")
        self.assertEqual(answer.usage, {"prompt_tokens": 3})

    def test_thinking_with_tools_replays_reasoning_history(self):
        backend = DeepSeekBackend(api_key="fake")
        body = {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(json.dumps(body).encode())) as opened:
            backend.request([Message("assistant", None, reasoning_content="reasoning"), Message("user", "hi")],
                            tools=[{"type": "function"}], thinking="max")
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertEqual(payload["messages"][0]["reasoning_content"], "reasoning")

    def test_stream_collects_fragmented_tool_calls_and_final_usage(self):
        backend = DeepSeekBackend(api_key="fake")
        body = sse(
            {"model": "deepseek-flash", "choices": [{"index": 0, "delta": {"content": "Hi"}}]},
            {"choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {"name": "read_", "arguments": '{"pa'}}]}}]},
            {"choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": 0, "function": {"name": "file", "arguments": 'th":"a"}'}}]},
                          "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"completion_tokens": 8}},
        )
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(body)) as opened:
            chunks = list(backend.stream([Message("user", "hi")]))
        self.assertEqual([chunk.kind for chunk in chunks], ["text", "response"])
        self.assertEqual(chunks[0].text, "Hi")
        answer = chunks[-1].response
        self.assertEqual(answer.message.tool_calls[0].name, "read_file")
        self.assertEqual(answer.message.tool_calls[0].arguments, '{"path":"a"}')
        self.assertEqual(answer.usage, {"completion_tokens": 8})
        self.assertTrue(json.loads(opened.call_args.args[0].data)["stream"])

    def test_truncated_stream_after_text_is_not_retryable(self):
        backend = DeepSeekBackend(api_key="fake")
        body = sse({"choices": [{"index": 0, "delta": {"content": "partial"}}]}, done=False)
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(body)):
            chunks = backend.stream([Message("user", "hi")])
            self.assertEqual(next(chunks).text, "partial")
            with self.assertRaises(DeepSeekStreamError) as caught:
                list(chunks)
        self.assertFalse(caught.exception.retryable)

    def test_rejects_http_base_url(self):
        with self.assertRaises(ValueError):
            DeepSeekBackend(api_key="fake", base_url="http://api.deepseek.com")

    def test_redirect_cannot_downgrade_tls_or_leak_authorization(self):
        from urllib.request import Request
        request = Request("https://api.deepseek.com/chat/completions", headers={"Authorization": "Bearer fake"})
        handler = SafeRedirectHandler()
        for target in ("http://api.deepseek.com/retry", "https://other.example/retry"):
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "redirect", {}, target)

    def test_unknown_model_omits_unverified_reasoning_parameter(self):
        backend = DeepSeekBackend(api_key="fake", model="future-model")
        payload = backend._payload([Message("user", "hello")])
        self.assertNotIn("reasoning_effort", payload)
        self.assertFalse(backend.capabilities.supports_reasoning_effort)
        with self.assertRaisesRegex(ValueError, "provider default only"):
            backend._payload([Message("user", "hello")], thinking="high")

    def test_reasoning_sse_and_text_sse_keep_complete_message(self):
        backend = DeepSeekBackend(api_key="fake")
        body = sse(
            {"choices": [{"index": 0, "delta": {"reasoning_content": "think "}}]},
            {"choices": [{"index": 0, "delta": {"reasoning_content": "more"}}]},
            {"choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": "stop"}]},
        )
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(body)):
            chunks = list(backend.stream([Message("user", "hi")], thinking="low"))
        self.assertEqual([chunk.kind for chunk in chunks], ["reasoning", "reasoning", "text", "response"])
        self.assertEqual(chunks[-1].response.message.reasoning_content, "think more")
        self.assertEqual(chunks[-1].response.message.content, "answer")

    def test_reasoning_only_interruption_is_not_retryable(self):
        backend = DeepSeekBackend(api_key="fake")
        body = sse({"choices": [{"index": 0, "delta": {"reasoning_content": "partial"}}]}, done=False)
        with patch("agent.deepseek.urlopen", return_value=FakeResponse(body)):
            chunks = backend.stream([Message("user", "hi")])
            self.assertEqual(next(chunks).kind, "reasoning")
            with self.assertRaises(DeepSeekStreamError) as caught:
                list(chunks)
        self.assertFalse(caught.exception.retryable)



class RetryTests(unittest.TestCase):
    def test_retries_transient_and_reports_attempts(self):
        calls = []
        sleeps = []
        retries = []

        def request():
            calls.append(1)
            if len(calls) < 3:
                raise URLError(TimeoutError("timeout"))
            return "ok"

        result = call_with_retry(request, RetryPolicy(jitter=0),
                                 on_retry=retries.append, sleep=sleeps.append)
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [0.5, 1.0])
        self.assertEqual([item["attempt"] for item in retries], [1, 2])

    def test_certificate_and_client_errors_do_not_retry(self):
        for error in (ssl.SSLCertVerificationError("bad cert"),
                      HTTPError("https://example.com", 401, "no", {}, io.BytesIO())):
            calls = []

            def request():
                calls.append(1)
                raise error

            with self.assertRaises(type(error)):
                call_with_retry(request, sleep=lambda _: None)
            self.assertEqual(len(calls), 1)
            if isinstance(error, HTTPError):
                error.close()

    def test_http_429_and_503_retry(self):
        for code in (429, 503):
            calls = []
            error = HTTPError("https://example.com", code, "retry", {}, io.BytesIO())

            def request():
                calls.append(1)
                if len(calls) == 1:
                    raise error
                return "ok"

            self.assertEqual(call_with_retry(request, sleep=lambda _: None), "ok")
            self.assertEqual(len(calls), 2)
            error.close()

    def test_partial_stream_error_is_never_replayed(self):
        calls = []

        def request():
            calls.append(1)
            try:
                raise TimeoutError("socket timed out")
            except TimeoutError as cause:
                raise DeepSeekStreamError("partial", retryable=False) from cause

        with self.assertRaises(DeepSeekStreamError):
            call_with_retry(request, sleep=lambda _: None)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
