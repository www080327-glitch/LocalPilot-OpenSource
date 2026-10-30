"""Minimal append-only tool-calling loop for DeepSeek-compatible backends."""

import json
import time
from dataclasses import asdict, dataclass

from .system_prompt import PROMPT_VERSION
from .tool_budget import measure_tool_budget
from .profiles import prompt_text
from .policy import DataPolicy


@dataclass
class ModelCallUsage:
    latency_seconds: float
    tool_call_count: int
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None
    reported_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class AgentResult:
    text: str
    messages: list
    model_calls: list[ModelCallUsage]
    prompt_version: str = PROMPT_VERSION
    status: str = "completed"
    approvals: list | None = None
    tool_budget: dict | None = None
    prompt_profile: str = "standard"
    tool_profile: str = "full"
    runtime_status: str | None = None
    deliverable_status: str = "missing"
    verification_status: str = "not_run"
    engineering_status: str = "unverified"
    verification: dict | None = None
    runtime_metrics: dict | None = None
    completion: dict | None = None
    task_outcome: str = "unverified"

    @property
    def task_succeeded(self):
        """Automation must use host task acceptance, never turn termination."""
        return self.task_outcome == "passed"

    @property
    def total_steps(self):
        return len(self.model_calls)

    @property
    def total_tool_calls(self):
        return sum(call.tool_call_count for call in self.model_calls)

    def usage_summary(self):
        cache_available = all(
            call.prompt_cache_hit_tokens is not None
            and call.prompt_cache_miss_tokens is not None
            for call in self.model_calls
        )
        hit_tokens = sum(call.prompt_cache_hit_tokens or 0 for call in self.model_calls)
        miss_tokens = sum(call.prompt_cache_miss_tokens or 0 for call in self.model_calls)
        cache_total = hit_tokens + miss_tokens
        return {
            "prompt_version": self.prompt_version,
            "status": self.status,
            "runtime_status": self.runtime_status or self.status,
            "deliverable_status": self.deliverable_status,
            "verification_status": self.verification_status,
            "engineering_status": self.engineering_status,
            "task_outcome": self.task_outcome,
            "task_succeeded": self.task_succeeded,
            "verification": self.verification,
            "runtime_metrics": self.runtime_metrics,
            "completion": self.completion,
            "tool_budget": self.tool_budget,
            "prompt_profile": self.prompt_profile,
            "tool_profile": self.tool_profile,
            "total_steps": self.total_steps,
            "total_tool_calls": self.total_tool_calls,
            "reported_models": sorted({call.reported_model for call in self.model_calls if call.reported_model}),
            "model_latency_seconds": sum(call.latency_seconds for call in self.model_calls),
            "cache": {
                "status": "available" if cache_available else "unavailable",
                "hit_tokens": hit_tokens if cache_available else None,
                "miss_tokens": miss_tokens if cache_available else None,
                "hit_ratio": hit_tokens / cache_total if cache_available and cache_total else None,
            },
            "model_calls": [asdict(call) for call in self.model_calls],
        }


class MaxStepsExceeded(RuntimeError):
    """Raised when the model keeps requesting work past the configured limit."""


class Agent:
    def __init__(self, backend, registry, max_steps=8, system_prompt=None, trace=None,
                 minimal_mode=False, *, prompt_profile=None, max_tool_calls=12, data_policy=None):
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.backend = backend
        self.registry = registry
        self.max_steps = max_steps
        if isinstance(max_tool_calls, bool) or not isinstance(max_tool_calls, int) or max_tool_calls < 0:
            raise ValueError("max_tool_calls must be a nonnegative integer")
        self.max_tool_calls = max_tool_calls
        self.prompt_profile = prompt_profile or ("minimal_0" if minimal_mode else "standard")
        if minimal_mode and self.prompt_profile != "minimal_0":
            raise ValueError("minimal_mode is an alias for prompt_profile=minimal_0")
        self.system_prompt = prompt_text(self.prompt_profile) if system_prompt is None else system_prompt
        if system_prompt is not None:
            self.prompt_profile = "custom"
        self.data_policy = DataPolicy(local_only=any(policy.local_only for policy in (
            data_policy or DataPolicy(), registry.gateway.data_policy,
            getattr(backend, "data_policy", DataPolicy()))))
        if self.data_policy.local_only:
            registry.gateway.data_policy = self.data_policy
        self.trace = trace
        self.minimal_mode = minimal_mode

    def run(self, task):
        """Compatibility entry point using the same session engine as the CLI."""
        from .session import AgentSession, SessionBudgets
        session = AgentSession(self.registry, backend=self.backend,
            policy="local-only" if self.data_policy.local_only else "cloud-only",
            budgets=SessionBudgets(max_steps=self.max_steps, max_tool_calls=self.max_tool_calls),
            data_policy=self.data_policy, trace=self.trace,
            prompt_profile=self.prompt_profile,
            system_prompt="" if self.minimal_mode else self.system_prompt,
            streaming=False, runtime_tools=False, legacy=True)
        return session.run_turn(task)

    @staticmethod
    def _assistant_message(response):
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("DeepSeek response did not contain choices[0].message") from error
        if not isinstance(message, dict):
            raise ValueError("DeepSeek response message must be an object")
        return message

    @staticmethod
    def _usage_value(response, name):
        usage = response.get("usage") or {}
        value = usage.get(name)
        if value is None and name == "prompt_cache_hit_tokens":
            value = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        return value

    def _run_tool_call(self, tool_call):
        call_id = tool_call.get("id", "")
        function = tool_call.get("function") or {}
        name = function.get("name", "<unknown>")
        try:
            raw_arguments = function.get("arguments", "{}")
            arguments = json.loads(raw_arguments)
            result = self.registry.call(name, arguments)
            unsuccessful = isinstance(result, dict) and result.get("status") in {
                "denied", "approval_required", "timeout", "nonzero_exit", "error"
            }
            content = {"ok": not unsuccessful, "result": result}
            if unsuccessful:
                content["error"] = {"type": result["status"], "message": "Tool operation did not complete successfully."}
        except json.JSONDecodeError as error:
            content = {
                "ok": False,
                "error": {
                    "type": "invalid_json_arguments",
                    "message": f"Tool arguments must be valid JSON: {error.msg}",
                },
            }
        except Exception as error:
            content = {
                "ok": False,
                "error": {"type": type(error).__name__, "message": str(error)},
            }

        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(content, ensure_ascii=False),
        }

    def _emit_trace(self, event):
        if self.trace is not None:
            self.trace(event)

    @staticmethod
    def _safe_arguments(raw_arguments):
        try:
            arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError):
            return {"summary": "invalid JSON arguments"}
        if not isinstance(arguments, dict):
            return {"summary": "arguments are not an object"}
        # Patches and commands now carry code/content: trace only metadata.
        summary = {key: arguments[key] for key in ("path", "max_results", "timeout", "output_limit") if key in arguments}
        if isinstance(arguments.get("changes"), list):
            summary["changes"] = [{"path": item.get("path"), "operation": item.get("operation")}
                                  for item in arguments["changes"] if isinstance(item, dict)]
        if isinstance(arguments.get("argv"), list):
            summary["argument_count"] = len(arguments["argv"])
        return summary

    @staticmethod
    def _tool_trace(tool_call, tool_result, step):
        try:
            payload = json.loads(tool_result["content"])
        except (KeyError, json.JSONDecodeError):
            payload = {"ok": False, "error": {"type": "InvalidToolResult"}}
        result = payload.get("result")
        summary = {"ok": bool(payload.get("ok"))}
        if not payload.get("ok"):
            summary["error_type"] = (payload.get("error") or {}).get("type", "ToolError")
        elif isinstance(result, str):
            summary["result_chars"] = len(result)
        elif isinstance(result, list):
            summary["result_count"] = len(result)
            if result and isinstance(result[0], dict) and "line" in result[0]:
                summary["match_count"] = len(result)
        elif isinstance(result, dict):
            summary["result_type"] = result.get("type", "metadata")
            summary["size_bytes"] = result.get("size_bytes")
            summary["status"] = result.get("status")
        else:
            summary["result_type"] = type(result).__name__
        return {
            "event": "tool_result",
            "step": step,
            "tool_call_id": tool_call.get("id"),
            "name": (tool_call.get("function") or {}).get("name", "<unknown>"),
            "summary": summary,
        }
