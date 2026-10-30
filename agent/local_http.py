"""OpenAI-compatible local chat completions transport; tool execution stays in AgentSession."""

import ipaddress
import json
import math
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .backends import BackendCapabilities, BackendChunk, BackendResponse, Message, ModelInfo, ToolCall
from .deepseek import DeepSeekBackend
from .serving import ServingProfile


class LocalBackendError(RuntimeError):
    def __init__(self, message, *, status_code=None, retryable=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.response = response


class LocalResourceExhausted(LocalBackendError):
    """Explicit pre-completion provider admission failure, no executable output."""
    resource_exhausted = True


def reject_provider_error(data):
    error = data.get('error') if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return
    if error.get('code') == 'prefill_memory_aborted' and not data.get('choices'):
        # Do not echo arbitrary provider bodies, machine details or credentials.
        raise LocalResourceExhausted('Local inference rejected by provider memory guard', retryable=True)
    raise LocalBackendError('Local provider returned an error envelope', retryable=False)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        fp.close()
        raise LocalBackendError("Local server redirect refused", retryable=False)


class LocalHTTPBackend:
    """A configured endpoint; context and capability values are operator claims."""

    is_local = True

    def __init__(self, *, base_url, model, effective_context=131072,
                 size_class="unknown", timeout=30, allow_remote=False,
                 supports_tool_calling=True, supports_streaming=True,
                 chat_template_kwargs=None, include_stream_usage=False,
                 api_key=None, reasoning_replay=False, supports_reasoning=None,
                 reasoning_efforts=(), engine="UNKNOWN", engine_version="UNKNOWN",
                 model_revision="UNKNOWN", hardware="UNKNOWN", device="UNKNOWN",
                 service_location="unknown", supports_vision=False):
        if not isinstance(base_url, str):
            raise ValueError("base_url must be an HTTP(S) URL string")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Local base_url must be an HTTP(S) URL without credentials, query or fragment")
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if not loopback and not allow_remote:
            raise ValueError("Local base_url must use a numeric loopback address unless allow_remote=True")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Local model identifier is required")
        if isinstance(effective_context, bool) or not isinstance(effective_context, int) or effective_context < 1:
            raise ValueError("effective_context must be a positive configured estimate")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        if api_key is not None and (not isinstance(api_key, str) or not api_key.strip() or any(c in api_key for c in "\r\n")):
            raise ValueError("api_key must be a nonempty single-line string")
        if any(type(value) is not bool for value in (supports_tool_calling, supports_streaming, reasoning_replay, include_stream_usage, supports_vision)):
            raise ValueError("Backend capability/options must be booleans")
        if supports_reasoning is not None and type(supports_reasoning) is not bool:
            raise ValueError("supports_reasoning must be boolean or None")
        if not isinstance(reasoning_efforts, (list, tuple)) or any(not isinstance(v, str) or not v for v in reasoning_efforts):
            raise ValueError("reasoning_efforts must be a list/tuple of nonempty provider-native values")
        if reasoning_efforts and supports_reasoning is not True:
            raise ValueError("reasoning_efforts requires an explicit reasoning capability declaration")
        if service_location not in {"local", "remote", "unknown"}:
            raise ValueError("service_location must be local, remote or unknown")
        if any(not isinstance(v, str) or not v.strip() for v in (engine, engine_version, model_revision, hardware, device)):
            raise ValueError("Provenance fields must be nonempty strings; use UNKNOWN when unknown")
        self.base_url = base_url.rstrip("/")
        self.is_loopback = loopback
        self.model = model
        self.timeout = timeout
        self.chat_template_kwargs = dict(chat_template_kwargs or {})
        self.include_stream_usage = bool(include_stream_usage)
        self._api_key = api_key
        self.reasoning_replay = reasoning_replay
        self.supports_reasoning = supports_reasoning
        self.model_info = ModelInfo(model, size_class, effective_context)
        self.capabilities = BackendCapabilities(supports_streaming=supports_streaming,
            supports_vision=supports_vision,
            supports_tool_calling=supports_tool_calling,
            supports_reasoning_effort=bool(reasoning_efforts),
            supports_native_thinking=supports_reasoning is True,
            supported_thinking_efforts=tuple(reasoning_efforts))
        self.profile = ServingProfile(self.base_url, model, effective_context,
            engine, engine_version, model_revision, hardware, device, service_location,
            {"streaming": supports_streaming, "tool_calling": supports_tool_calling,
             "reasoning": supports_reasoning, "context": True},
            {"chat_template_kwargs": self.chat_template_kwargs.copy(),
             "include_stream_usage": self.include_stream_usage,
             "reasoning_replay": reasoning_replay, "reasoning_efforts": list(reasoning_efforts),
             "timeout_seconds": float(timeout), "routing_size_class": size_class,
             "authentication_configured": api_key is not None})
        # Bypass environment HTTP proxies even for explicitly permitted remote endpoints.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _open(self, path, payload=None):
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if payload and payload.get("stream") else "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        request = Request(self.base_url + path,
                          data=None if payload is None else json.dumps(payload).encode("utf-8"),
                          headers=headers,
                          method="GET" if payload is None else "POST")
        try:
            return self._opener.open(request, timeout=self.timeout)
        except HTTPError as error:
            # Server bodies may echo credentials or prompt data. Do not put
            # untrusted response bodies in CLI/audit/verification diagnostics.
            error.close()
            raise LocalBackendError(f"Local model server returned HTTP {error.code}",
                                    status_code=error.code) from error
        except ssl.SSLCertVerificationError as error:
            raise LocalBackendError(f"Local HTTPS certificate verification failed: {error}",
                                    retryable=False) from error
        except (URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            certificate_error = isinstance(reason, ssl.SSLCertVerificationError) or any(
                term in str(reason).lower() for term in ("certificate", "cert verify"))
            raise LocalBackendError(f"Local model server unavailable at {self.base_url}: {error}",
                                    retryable=not certificate_error) from error

    def status(self):
        """Fresh service and model discovery; no model download or inference."""
        result = {"service_running": False, "model_available": False,
                  "model": self.model, "effective_context": self.model_info.effective_context,
                  "effective_context_source": "configured_estimate",
                  "capabilities": self.capabilities.__dict__.copy(),
                  "profile": self.profile.snapshot()}
        try:
            with self._open("/models") as response:
                data = json.loads(response.read().decode("utf-8"))
            models = data["data"]
            if not isinstance(models, list):
                raise ValueError("data is not a list")
            result["service_running"] = True
            result["model_available"] = any(isinstance(item, dict) and item.get("id") == self.model for item in models)
            if not result["model_available"]:
                result["error"] = f"Model {self.model!r} is not listed by the local server; install or load it manually."
        except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
            result["error"] = str(error)
        return result

    def health_check(self):
        state = self.status()
        return state["service_running"] and state["model_available"]

    def thinking_mapping(self, thinking, has_tools=False):
        if thinking is not None and thinking in self.capabilities.supported_thinking_efforts:
            return {"requested": thinking, "effective": thinking, "provider_value": thinking,
                    "reason": "operator_configured_mapping_not_verified"}
        if thinking is not None:
            raise ValueError("Local server does not declare this reasoning effort")
        return {"requested": thinking, "effective": "provider_default", "provider_value": None,
                "reason": "local_server_reasoning_mapping_unverified"}

    def _payload(self, messages, tools, max_tokens, stream=False, thinking=None):
        if not self.capabilities.supports_vision and any(isinstance((item.content if isinstance(item, Message) else item.get('content')), list) for item in messages):
            raise LocalBackendError('Provider vision capability is not explicitly enabled', retryable=False)
        payload = {"model": self.model, "messages": [
            (item if isinstance(item, Message) else Message.from_dict(item)).to_dict(include_reasoning=self.reasoning_replay)
            for item in messages], "stream": stream}
        if tools is not None and self.capabilities.supports_tool_calling:
            payload["tools"] = tools
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
                raise ValueError("max_tokens must be a positive integer")
            payload["max_tokens"] = max_tokens
        if self.chat_template_kwargs:
            payload["chat_template_kwargs"] = self.chat_template_kwargs.copy()
        if stream and self.include_stream_usage:
            payload["stream_options"] = {"include_usage": True}
        if thinking is not None:
            payload["reasoning_effort"] = self.thinking_mapping(thinking)["provider_value"]
        return payload

    @staticmethod
    def _choice(data):
        if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
            raise LocalBackendError("Malformed local completion: missing choices", retryable=False)
        choice = data["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("finish_reason"), str) or not choice["finish_reason"]:
            raise LocalBackendError("Local completion missing finish_reason", retryable=False)
        try:
            message = Message.from_dict(choice["message"])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise LocalBackendError("Malformed local completion message", retryable=False) from error
        if message.role != "assistant" or (choice["finish_reason"] == "tool_calls" and not message.tool_calls):
            raise LocalBackendError("Malformed local assistant or tool-call response", retryable=False)
        LocalHTTPBackend._validate_message(message)
        return BackendResponse(message, LocalHTTPBackend._usage(data), data.get("model"), choice["finish_reason"])

    @staticmethod
    def _usage(data):
        usage = data.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise LocalBackendError("Malformed local usage metadata", retryable=False)
        if usage is None:
            return None
        normalized = dict(usage)
        details = usage.get("prompt_tokens_details")
        if details is not None and not isinstance(details, dict):
            raise LocalBackendError("Malformed local cache usage metadata", retryable=False)
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        if cached is not None:
            total = usage.get("prompt_tokens")
            if type(cached) is not int or cached < 0 or (total is not None and (type(total) is not int or total < cached)):
                raise LocalBackendError("Invalid local cache token counters", retryable=False)
            if normalized.get("prompt_cache_hit_tokens") is not None and normalized["prompt_cache_hit_tokens"] != cached:
                raise LocalBackendError("Conflicting local cache token counters", retryable=False)
            normalized["prompt_cache_hit_tokens"] = cached
            if total is not None:
                miss = total - cached
                if normalized.get("prompt_cache_miss_tokens") is not None and normalized["prompt_cache_miss_tokens"] != miss:
                    raise LocalBackendError("Conflicting local cache miss counters", retryable=False)
                normalized["prompt_cache_miss_tokens"] = miss
        return normalized

    @staticmethod
    def _validate_message(message):
        if any(v is not None and not isinstance(v, str) for v in (message.content, message.reasoning_content)):
            raise LocalBackendError("Malformed local assistant text", retryable=False)
        if any(not isinstance(c.id, str) or not c.id or not isinstance(c.name, str) or not c.name or not isinstance(c.arguments, str) for c in message.tool_calls):
            raise LocalBackendError("Malformed local tool call", retryable=False)

    def request(self, messages, tools=None, thinking=None, max_tokens=None):
        with self._open("/chat/completions", self._payload(messages, tools, max_tokens, thinking=thinking)) as response:
            try:
                data = json.loads(response.read().decode("utf-8"))
            except (ValueError, UnicodeError) as error:
                raise LocalBackendError("Malformed local completion JSON", retryable=False) from error
        reject_provider_error(data)
        return self._choice(data)

    def stream(self, messages, tools=None, thinking=None, max_tokens=None):
        content_parts, reasoning_parts, calls = [], [], {}
        model, usage, finish_reason, done = None, None, None, False
        fragment_bytes = 0
        fragment_limit = (max_tokens or 131072) * 16
        def partial():
            # Evidence only; incomplete fields must never become executable calls.
            return BackendResponse(Message('assistant', ''.join(content_parts) or None,
                [ToolCall(**calls[index]) for index in sorted(calls)],
                reasoning_content=''.join(reasoning_parts) or None), usage, model,
                finish_reason if finish_reason not in {None, 'stop', 'tool_calls'} else 'stream_interrupted')
        try:
            with self._open("/chat/completions", self._payload(messages, tools, max_tokens, stream=True, thinking=thinking)) as response:
                for event in DeepSeekBackend._events(response):
                    if event == "[DONE]":
                        done = True
                        break
                    try:
                        data = json.loads(event)
                        if not isinstance(data, dict):
                            raise ValueError("event is not an object")
                        reject_provider_error(data)
                        model = data.get("model") or model
                        if data.get("usage") is not None:
                            usage = self._usage(data)
                        for choice in data.get("choices") or []:
                            if choice.get("index", 0) != 0:
                                continue
                            finish_reason = choice.get("finish_reason") or finish_reason
                            delta = choice.get("delta") or {}
                            reasoning = delta.get("reasoning_content") or ""
                            part = delta.get("content") or ""
                            if not isinstance(part, str) or not isinstance(reasoning, str):
                                raise ValueError("delta text must be strings")
                            fragment_bytes += len(part.encode()) + len(reasoning.encode())
                            if reasoning:
                                reasoning_parts.append(reasoning)
                                yield BackendChunk("reasoning", reasoning)
                            if part:
                                content_parts.append(part)
                                yield BackendChunk("text", part)
                            for fragment in delta.get("tool_calls") or []:
                                index = fragment["index"]
                                if type(index) is not int or index < 0:
                                    raise ValueError("tool call index must be a nonnegative integer")
                                call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                                call["id"] += fragment.get("id") or ""
                                function = fragment.get("function") or {}
                                call["name"] += function.get("name") or ""
                                call["arguments"] += function.get("arguments") or ""
                                fragment_bytes += len((function.get('arguments') or '').encode())
                            if fragment_bytes > fragment_limit:
                                raise ValueError('Local stream exceeded output byte guard')
                    except (ValueError, KeyError, TypeError, AttributeError) as error:
                        raise LocalBackendError("Malformed local SSE event", retryable=False) from error
        except Exception as error:
            if content_parts or reasoning_parts or calls:
                raise LocalBackendError("Local stream interrupted after response fragments; no replay",
                                        retryable=False, response=partial()) from error
            raise
        if not done or not isinstance(finish_reason, str) or not finish_reason:
            raise LocalBackendError("Local stream ended without a complete response",
                                    retryable=False if content_parts or reasoning_parts or calls else True,
                                    response=partial())
        if any(not call["id"] or not call["name"] for call in calls.values()) or (finish_reason == "tool_calls" and not calls):
            raise LocalBackendError("Incomplete local streamed tool call", retryable=False, response=partial())
        message = Message("assistant", "".join(content_parts) or None,
                          [ToolCall(**calls[index]) for index in sorted(calls)],
                          reasoning_content="".join(reasoning_parts) or None)
        self._validate_message(message)
        yield BackendChunk("response", response=BackendResponse(message, usage, model, finish_reason))
