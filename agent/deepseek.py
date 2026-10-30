"""Dependency-free DeepSeek chat completions client."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .backends import (BackendCapabilities, BackendChunk, BackendResponse,
                       Message, ModelInfo, ToolCall)
from .policy import DataPolicy
from .cloud_credentials import resolve_deepseek_key


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        original, target = urlparse(request.full_url), urlparse(newurl)
        if target.scheme != "https" or target.netloc != original.netloc:
            raise ValueError("Cross-origin or HTTP redirects are forbidden for authenticated model requests")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def urlopen(request, *, timeout):
    """Use normal certificate validation and reject credential-leaking redirects."""
    return build_opener(SafeRedirectHandler()).open(request, timeout=timeout)


class DeepSeekAPIError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class DeepSeekStreamError(RuntimeError):
    """The stream ended before a complete response was received."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class DeepSeekBackend:
    """Send model requests; never execute returned tool calls."""

    is_local = False
    provider = "deepseek"
    _KNOWN_THINKING_MODELS = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"}

    def __init__(self, api_key=None, model="deepseek-flash",
                 base_url="https://api.deepseek.com", timeout=30,
                 data_policy=None, effective_context=131072, key_file=None):
        self.data_policy = data_policy or DataPolicy()
        self.data_policy.check_cloud_send()
        self.api_key = resolve_deepseek_key(api_key, key_file=key_file)
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("DeepSeek base_url must be an HTTPS URL without credentials")
        if isinstance(effective_context, bool) or not isinstance(effective_context, int) or effective_context < 1:
            raise ValueError("effective_context must be a positive admission estimate")
        self.model = model
        # Exact first-party DSH catalog capability; never infer from protocol
        # compatibility or a model-name substring.
        self.supports_in_history_system_prompt = model == "deepseek-flash"
        # Conservative byte-admission ceiling, not a claim about provider token context.
        self.model_info = ModelInfo(name=model, size_class="cloud", effective_context=effective_context)
        verified_thinking = model in self._KNOWN_THINKING_MODELS
        self.capabilities = BackendCapabilities(
            supports_reasoning_effort=verified_thinking,
            supports_streaming=True,
            supports_tool_calling=True,
            supports_parallel_tool_calls=False,
            supports_native_thinking=verified_thinking,
            supported_thinking_efforts=("none", "low", "high", "max") if verified_thinking else (),
            default_thinking_effort="high" if verified_thinking else None,
        )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def thinking_mapping(self, thinking, has_tools=False):
        """Return the exact provider effort; never translate or disable it for tools."""
        if thinking is None:
            return {"requested": thinking, "effective": "provider_default",
                    "provider_value": None, "reason": "provider_default"}
        if thinking not in self.capabilities.supported_thinking_efforts:
            raise ValueError(f"{self.provider}:{self.model} does not support thinking '{thinking}'; supported: {', '.join(self.capabilities.supported_thinking_efforts) or 'provider default only'}")
        return {"requested": thinking, "effective": thinking,
                "provider_value": thinking, "reason": None}

    def _payload(self, messages, tools=None, thinking=None, max_tokens=None,
                 stream=False):
        payload = {"model": self.model, "messages": [
            message.to_dict(include_reasoning=self.provider == "deepseek") if isinstance(message, Message) else Message.from_dict(message).to_dict(include_reasoning=self.provider == "deepseek")
            for message in messages
        ]}
        if tools is not None:
            payload["tools"] = tools
        if thinking is not None:
            mapped = self.thinking_mapping(thinking, has_tools=tools is not None)
            if mapped["provider_value"] is not None:
                payload["reasoning_effort"] = mapped["provider_value"]
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
                raise ValueError("max_tokens must be a positive integer")
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _open(self, payload):
        self.data_policy.check_cloud_send()
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as error:
            # Provider/proxy bodies can echo Authorization in encoded form.
            # Retain the status, never attach arbitrary error bodies to ledgers.
            raise DeepSeekAPIError(
                f"{self.provider} API returned HTTP {error.code}",
                status_code=error.code,
            ) from None
        except URLError as error:
            from .retry import is_transient_error
            failure = DeepSeekAPIError(f"Could not reach the {self.provider} API ({type(error.reason).__name__})")
            failure.retryable = is_transient_error(error)
            reason = str(error.reason).lower()
            failure.transport_kind = ('tls_certificate' if 'certificate' in reason else
                'timeout' if 'timed out' in reason or 'timeout' in reason else
                'dns' if 'name resolution' in reason or 'nodename' in reason else
                'connection_failure')
            raise failure from None

    def chat(self, messages, tools=None):
        """Legacy interface: return the untouched decoded API response."""
        payload = {"model": self.model, "messages": messages}
        if tools is not None:
            payload["tools"] = tools
        with self._open(payload) as response:
            return json.loads(response.read().decode("utf-8"))

    def request(self, messages: list[Message], tools=None, thinking=None,
                max_tokens=None):
        with self._open(self._payload(messages, tools, thinking, max_tokens)) as response:
            data = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices") or []
        if not choices:
            raise DeepSeekAPIError("DeepSeek returned no completion choice")
        if choices[0].get("finish_reason") not in {None, "stop", "tool_calls"}:
            error = DeepSeekAPIError("DeepSeek returned an incomplete or filtered response; no tools executed")
            error.retryable = False
            error.response = BackendResponse(message=Message.from_dict(choices[0]["message"]),
                usage=data.get("usage"), model=data.get("model"), finish_reason=choices[0].get("finish_reason"))
            raise error
        return BackendResponse(message=Message.from_dict(choices[0]["message"]),
                               usage=data.get("usage"), model=data.get("model"), finish_reason=choices[0].get("finish_reason"))

    @staticmethod
    def _events(response):
        data_lines = []
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                if data_lines:
                    yield "\n".join(data_lines)
                    data_lines = []
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
        if data_lines:
            yield "\n".join(data_lines)

    def stream(self, messages: list[Message], tools=None, thinking=None,
               max_tokens=None):
        """Yield reasoning and text deltas, then one complete response."""
        payload = self._payload(messages, tools, thinking, max_tokens, stream=True)
        content_parts = []
        reasoning_parts = []
        calls = {}
        usage = None
        model = None
        done = False
        finish_reason = None
        try:
            with self._open(payload) as response:
                for event in self._events(response):
                    if event == "[DONE]":
                        done = True
                        break
                    try:
                        data = json.loads(event)
                    except json.JSONDecodeError as error:
                        raise DeepSeekStreamError("Invalid DeepSeek stream event") from error
                    model = data.get("model") or model
                    if data.get("usage") is not None:
                        usage = data["usage"]
                    for choice in data.get("choices") or []:
                        if choice.get("index", 0) != 0:
                            continue
                        if choice.get("finish_reason") is not None:
                            finish_reason = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        text = delta.get("content") or ""
                        reasoning = delta.get("reasoning_content") or ""
                        if reasoning:
                            reasoning_parts.append(reasoning)
                            yield BackendChunk(kind="reasoning", text=reasoning)
                        if text:
                            content_parts.append(text)
                            yield BackendChunk(kind="text", text=text)
                        for fragment in delta.get("tool_calls") or []:
                            index = fragment["index"]
                            call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            call["id"] += fragment.get("id") or ""
                            function = fragment.get("function") or {}
                            call["name"] += function.get("name") or ""
                            call["arguments"] += function.get("arguments") or ""
        except Exception as error:
            if content_parts or reasoning_parts or calls:
                partial = DeepSeekStreamError("DeepSeek stream failed after partial output", retryable=False)
                partial.response = BackendResponse(Message('assistant', ''.join(content_parts) or None,
                    tool_calls=[ToolCall(**calls[index]) for index in sorted(calls)],
                    reasoning_content=''.join(reasoning_parts) or None), usage, model, 'stream_interrupted')
                raise partial from error
            raise
        if not done or finish_reason not in {"stop", "tool_calls"}:
            error = DeepSeekStreamError("DeepSeek stream ended without a complete response",
                                       retryable=not bool(content_parts or reasoning_parts or calls))
            if done and finish_reason is not None:
                error.retryable = False
                error.response = BackendResponse(Message('assistant', ''.join(content_parts) or None,
                    tool_calls=[ToolCall(**calls[index]) for index in sorted(calls)],
                    reasoning_content=''.join(reasoning_parts) or None), usage, model, finish_reason)
            raise error
        if any(not call["id"] or not call["name"] for call in calls.values()):
            raise DeepSeekStreamError("DeepSeek stream contained an incomplete tool call")
        message = Message(role="assistant", content="".join(content_parts) or None,
                          tool_calls=[ToolCall(**calls[index]) for index in sorted(calls)],
                          reasoning_content="".join(reasoning_parts) or None)
        yield BackendChunk(kind="response", response=BackendResponse(
            message=message, usage=usage, model=model, finish_reason=finish_reason))
