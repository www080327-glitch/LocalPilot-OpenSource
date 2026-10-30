"""OpenAI Chat Completions adapter for bounded cloud workers."""

import os

from .backends import BackendCapabilities
from .deepseek import DeepSeekBackend


class OpenAIWorkerBackend(DeepSeekBackend):
    provider = "openai"

    def __init__(self, *, model, api_key=None, data_policy=None):
        if model not in {"gpt-6-luna", "gpt-6-sol"}:
            raise ValueError("OpenAI worker adapter supports only verified gpt-6-luna/gpt-6-sol mappings.")
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("Set OPENAI_API_KEY to enable OpenAI cloud workers.")
        super().__init__(api_key=key, model=model, base_url="https://api.openai.com/v1",
                         data_policy=data_policy)
        self.capabilities = BackendCapabilities(supports_reasoning_effort=True,
            supports_streaming=True, supports_tool_calling=True,
            supports_native_thinking=True,
            supported_thinking_efforts=("none",),
            default_thinking_effort="none")

    def thinking_mapping(self, thinking, has_tools=False):
        if thinking is None:
            return {"requested": None, "effective": "provider_default",
                    "provider_value": None, "reason": "provider_default"}
        if thinking not in self.capabilities.supported_thinking_efforts:
            raise ValueError(f"{self.provider}:{self.model} does not support thinking '{thinking}'")
        return {"requested": thinking, "effective": thinking,
                "provider_value": thinking, "reason": None}

    def _payload(self, messages, tools=None, thinking=None, max_tokens=None, stream=False):
        payload = super()._payload(messages, tools=tools, thinking=thinking,
                                   max_tokens=None, stream=stream)
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
                raise ValueError("max_tokens must be a positive integer")
            payload["max_completion_tokens"] = max_tokens
        return payload
