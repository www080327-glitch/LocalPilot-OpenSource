"""Small provider-neutral types used by the runtime."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BackendCapabilities:
    supports_reasoning_effort: bool = False
    supports_streaming: bool = False
    supports_tool_calling: bool = False
    supports_parallel_tool_calls: bool = False
    supports_native_thinking: bool = False
    supported_thinking_efforts: tuple[str, ...] = ()
    default_thinking_effort: str | None = None
    supports_vision: bool = False


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_class: str | None = None
    effective_context: int | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str

    @classmethod
    def from_dict(cls, value):
        function = value.get("function", {})
        return cls(id=value["id"], name=function["name"],
                   arguments=function["arguments"])

    def to_dict(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.name, "arguments": self.arguments}}


@dataclass
class Message:
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    # Optional provider metadata, never sent by generic adapters. Text and tool
    # arguments remain canonical; native replay stores only offsets/signatures.
    native_replay: dict | None = None

    @classmethod
    def from_dict(cls, value):
        return cls(role=value["role"], content=value.get("content"),
                   tool_calls=[ToolCall.from_dict(call)
                               for call in value.get("tool_calls") or []],
                   tool_call_id=value.get("tool_call_id"),
                   reasoning_content=value.get("reasoning_content"),
                   native_replay=value.get("native_replay"))

    def to_dict(self, *, include_reasoning=False):
        result = {"role": self.role, "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [call.to_dict() for call in self.tool_calls]
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        if include_reasoning and self.role == "assistant" and self.reasoning_content is not None:
            result["reasoning_content"] = self.reasoning_content
        if include_reasoning and self.role == "assistant" and self.native_replay is not None:
            result["native_replay"] = self.native_replay
        return result


@dataclass
class BackendResponse:
    message: Message
    usage: dict | None = None
    model: str | None = None
    # None preserves compatibility with older/scripted backends. HTTP adapters
    # supply the actual provider value, including length/content_filter.
    finish_reason: str | None = None


@dataclass
class BackendChunk:
    kind: str
    text: str = ""
    response: BackendResponse | None = None


class LocalBackendUnavailable(RuntimeError):
    """A local model backend has not been connected yet."""


class LocalBackend:
    """Explicit placeholder until a verified local engine is configured."""

    is_local = True

    def __init__(self, name="local-unavailable"):
        self.model_info = ModelInfo(name=name)
        self.capabilities = BackendCapabilities()

    def health_check(self):
        return False

    def request(self, messages: list[Message], tools=None, thinking=None,
                max_tokens=None):
        raise LocalBackendUnavailable("No local model backend is configured.")

    def stream(self, messages: list[Message], tools=None, thinking=None,
               max_tokens=None):
        raise LocalBackendUnavailable("No local model backend is configured.")
