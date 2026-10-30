"""Opt-in DeepSeek protocol adapter; LocalPilot still owns every tool action.

Tool-history validation and terminated-frame policy are adapted from DeepSeek
Harness serialize.ts / sse.ts at 687f282e8625c6b8d11ff58211a90524be2e4317.
Copyright (c) 2026 DeepSeek. MIT: see third_party/deepseek-harness/LICENSE.
Chat reasoning replay follows the current public Chat API, not Messages replay.
"""
from copy import deepcopy
import json

from .deepseek import DeepSeekBackend, DeepSeekStreamError


class DeepSeekOptimizedBackend(DeepSeekBackend):
    """Chat adapter with explicit thinking, conditional replay and strict frames.

    No DSH identity, session logs, plugin inventory, or alternate tool executor.
    The request is a fresh view; canonical SQLite messages remain untouched.
    """
    engine = "deepseek_optimized"

    def _payload(self, messages, tools=None, thinking=None, max_tokens=None, stream=False):
        payload = super()._payload(messages, tools, thinking, max_tokens, stream)
        if thinking is not None:
            payload["thinking"] = {"type": "disabled" if thinking == "none" else "enabled"}
            if thinking == "none":
                payload.pop("reasoning_effort", None)
        # Current Chat API: ALL assistant reasoning is replayed when tools is
        # present. The older DSH tool-call-only recipe is no longer sufficient.
        if tools is None:
            for message in payload["messages"]:
                message.pop("reasoning_content", None)
        else:
            payload["tools"] = sorted(deepcopy(tools), key=lambda t: t["function"]["name"])
        self._validate_history(payload["messages"])
        return payload

    @staticmethod
    def _validate_history(messages):
        pending = set()
        for message in messages:
            role = message["role"]
            if role == "tool":
                call_id = message.get("tool_call_id")
                if call_id not in pending:
                    raise ValueError("DeepSeek history tool result has no pending call")
                pending.remove(call_id)
                continue
            # RC2 can insert host system snapshots before tool-result groups.
            if role == "system":
                continue
            if pending:
                raise ValueError("DeepSeek history contains unresolved tool calls")
            if role == "assistant":
                for call in message.get("tool_calls", []):
                    call_id = call.get("id")
                    if not isinstance(call_id, str) or not call_id or call_id in pending:
                        raise ValueError("DeepSeek history duplicate or empty tool identity")
                    pending.add(call_id)
        if pending:
            raise ValueError("DeepSeek history ends with unresolved tool calls")

    @staticmethod
    def _events(response):
        # Like upstream eventsource-parser, an unterminated tail is not an
        # event. Heartbeats/comments cannot turn a truncated tool into a call.
        lines = []
        for raw in response:
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                if lines:
                    event = "\n".join(lines)
                    if event != "[DONE]":
                        try:
                            data = json.loads(event)
                            for choice in data.get("choices") or []:
                                for call in (choice.get("delta") or {}).get("tool_calls") or []:
                                    index = call.get("index")
                                    if type(index) is not int or index < 0:
                                        raise ValueError("Invalid tool index")
                        except (ValueError, TypeError, AttributeError):
                            raise DeepSeekStreamError("Malformed DeepSeek SSE event", retryable=False) from None
                    yield event
                    lines = []
            elif line.startswith("data:"):
                value = line[5:]
                lines.append(value[1:] if value.startswith(" ") else value)
        if lines:
            raise DeepSeekStreamError("Unterminated DeepSeek SSE frame", retryable=False)

    @staticmethod
    def _validate_response(response):
        calls = response.message.tool_calls
        ids = [call.id for call in calls]
        if len(set(ids)) != len(ids) or any(not value for value in ids):
            raise DeepSeekStreamError("DeepSeek response contains duplicate or empty tool identities", retryable=False)
        if calls and response.finish_reason != "tool_calls":
            raise DeepSeekStreamError("DeepSeek tool response has inconsistent finish reason", retryable=False)
        # Keep invalid JSON as model-visible Gateway feedback. Never repair it
        # to {} or execute it in this adapter.

    def request(self, messages, tools=None, thinking=None, max_tokens=None):
        response = super().request(messages, tools, thinking, max_tokens)
        self._validate_response(response)
        return response

    def stream(self, messages, tools=None, thinking=None, max_tokens=None):
        for chunk in super().stream(messages, tools, thinking, max_tokens):
            if chunk.response is not None:
                self._validate_response(chunk.response)
            yield chunk

    def chat(self, messages, tools=None):
        with self._open(self._payload(messages, tools)) as response:
            return json.loads(response.read().decode("utf-8"))
