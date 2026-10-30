"""vLLM Chat Completions adapter. Tools remain proposals to AgentSession."""
import json
import socket
import threading
from .backends import Message
from .context import context_units
from .local_http import LocalBackendError, LocalHTTPBackend


class VLLMBackend(LocalHTTPBackend):
    def __init__(self, *, generation_parameters=None, **kwargs):
        from localpilot_service.backend_contract import generation_options
        self.generation_parameters = generation_options(generation_parameters or {})
        kwargs.setdefault('engine', 'vllm')
        kwargs.setdefault('include_stream_usage', True)
        kwargs.setdefault('supports_tool_calling', False)
        kwargs.setdefault('size_class', 'host-registered')
        kwargs.setdefault('service_location', 'local')
        super().__init__(**kwargs)
        if not self.is_loopback:
            if not self.base_url.startswith('https://') or not self._api_key:
                raise ValueError('Remote vLLM requires HTTPS and authentication')
            self.is_local = False
        self._lock = threading.Lock()
        self._responses = set()
        self.service_contract = {'provider': 'vllm', 'revision': 1,
            'generation_parameters': self.generation_parameters.copy(),
            'profile': self.profile.snapshot(),
            'cancellation': 'client_disconnect; engine_release_requires_qualification'}

    def _payload(self, messages, tools, max_tokens, stream=False, thinking=None):
        messages = [m if isinstance(m, Message) else Message.from_dict(m) for m in messages]
        if tools and not self.capabilities.supports_tool_calling:
            raise ValueError('vLLM tool parser has not been declared by the host')
        if stream and not self.capabilities.supports_streaming:
            raise ValueError('vLLM streaming is not declared')
        # This intentionally uses LP's conservative byte admission, not a token
        # estimate mislabeled as tokenizer output. The server checks tokens too.
        if context_units(messages, tools) + (max_tokens or 0) * 16 > self.model_info.effective_context:
            raise LocalBackendError('vLLM context admission exceeded', retryable=False)
        payload = super()._payload(messages, tools, max_tokens, stream, thinking)
        payload.update(self.generation_parameters)
        return payload

    def discover(self):
        with self._open('/models') as response:
            data = json.load(response)
        models = data.get('data') if isinstance(data, dict) else None
        if not isinstance(models, list) or any(not isinstance(m, dict) or not isinstance(m.get('id'), str) for m in models):
            raise LocalBackendError('Malformed vLLM model discovery', retryable=False)
        return models

    def inspect_service(self):
        result = self.status()
        result.update(provider='vllm', mutations_supported=False,
            load_unload='trusted host process lifecycle; no standard HTTP weight-unload API',
            cancellation=self.service_contract['cancellation'])
        return result

    def _open(self, path, payload=None):
        response = super()._open(path, payload)
        if payload is None:
            return response
        backend = self
        class Tracked:
            def __enter__(self):
                return response
            def __exit__(self, *exc):
                try:
                    response.close()
                finally:
                    with backend._lock:
                        backend._responses.discard(response)
        with self._lock:
            self._responses.add(response)
        return Tracked()

    def cancel_request(self):
        """Cancel this adapter's active requests; never kill a shared server."""
        with self._lock:
            responses = tuple(self._responses)
        for response in responses:
            sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            response.close()
