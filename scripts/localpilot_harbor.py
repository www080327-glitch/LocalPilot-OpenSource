"""Optional Harbor adapter: the product AgentSession drives task-container Shell.

Install pinned Harbor in an evaluation environment; no Harbor dependency is
added to the desktop or Core. There is deliberately no host filesystem tool.
"""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path, PurePosixPath

from harbor.agents.base import BaseAgent

from agent.engine_v5 import EngineV5Policy
from agent.permissions import ToolRiskMetadata
from agent.policy import DataPolicy
from agent.registry import ToolRegistry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_service.backend_contract import ServiceDeepSeekNativeBackend, ServiceOpenAIBackend


class ContainerShell:
    def __init__(self, environment, loop, cwd):
        self.environment, self.loop, self.cwd = environment, loop, cwd

    def __call__(self, workspace_root, command, timeout=120):
        # AgentSession is synchronous. Only Harbor's owning event loop may
        # operate its environment; workspace_root is never a dispatch target.
        pending = asyncio.run_coroutine_threadsafe(self.environment.exec(
            command=command, cwd=self.cwd, timeout_sec=timeout), self.loop)
        result = pending.result()
        return {"status": "ok" if result.return_code == 0 else "nonzero_exit",
                "exit_code": result.return_code, "stdout": result.stdout or "",
                "stderr": result.stderr or "", "action_sent": True,
                "process_completed": result.return_code >= 0,
                "action_may_have_applied": result.return_code < 0,
                "partial_effects_possible": result.return_code > 0,
                "replay_allowed": False, "verification": "NOT_RUN",
                "execution_target": "harbor_task_environment"}


class LocalPilotHarborAgent(BaseAgent):
    def __init__(self, logs_dir, model_name=None, *, endpoint,
                 provider_kind="local-openai", api_key_env=None,
                 context_tokens=65536, max_steps=24, max_tool_calls=40,
                 max_token_units=1000000, max_output_tokens=2048,
                 model_timeout=120, chat_template_kwargs=None, model_budget=None, **kwargs):
        if provider_kind not in {"local-openai", "remote-openai", "deepseek-native"}:
            raise ValueError("Use an explicit local-openai, remote-openai or deepseek-native provider")
        if api_key_env is not None and (not isinstance(api_key_env, str) or not api_key_env.isidentifier()):
            raise ValueError("api_key_env must name an environment variable")
        key = os.environ.get(api_key_env) if api_key_env else None
        if api_key_env and not key:
            raise ValueError("Configured model credential is absent")
        cloud = provider_kind != "local-openai"
        if cloud and (not key or not endpoint.startswith("https://")):
            raise ValueError("Remote inference requires HTTPS and a configured credential")
        if kwargs.get("mcp_servers") or kwargs.get("skills_dir") or kwargs.get("load_trajectory"):
            raise ValueError("This adapter has not qualified MCP, Skills or trajectory import")
        kwargs.pop("skip_model_parsing", None)
        super().__init__(logs_dir=Path(logs_dir), model_name=model_name,
                         skip_model_parsing=True, **kwargs)
        self.budgets = SessionBudgets(max_steps=max_steps, max_tool_calls=max_tool_calls,
            max_token_units=max_token_units, max_output_tokens=max_output_tokens,
            max_subagents_per_turn=0)
        self.data_policy = DataPolicy(local_only=not cloud)
        if provider_kind == "deepseek-native":
            if chat_template_kwargs:
                raise ValueError("Native Messages does not accept local chat template overrides")
            self.backend = ServiceDeepSeekNativeBackend(base_url=endpoint, model=model_name,
                api_key=key, data_policy=self.data_policy, effective_context=context_tokens,
                timeout=model_timeout, generation_parameters={"temperature": 0})
        else:
            backend_type = ServiceOpenAIBackend
            extra = {}
            if model_budget is not None:
                if provider_kind != 'local-openai':
                    raise ValueError('Measured model budgets require the local tokenizer transport')
                from scripts.harbor_model_budget import BudgetedLocalBackend
                backend_type = BudgetedLocalBackend
                extra = {'model_budget':model_budget, 'budget_log':Path(logs_dir)/'model-budget.jsonl'}
            self.backend = backend_type(base_url=endpoint, model=model_name,
                api_key=key, allow_remote=cloud, effective_context=context_tokens,
                timeout=model_timeout, supports_streaming=True, include_stream_usage=True,
                chat_template_kwargs=chat_template_kwargs, generation_parameters={"temperature": 0}, **extra)
        self.backend.is_local = not cloud
        self.cloud = cloud
        self.measured_local = model_budget is not None and not cloud
        self.container_cwd = None

    @staticmethod
    def name():
        return "localpilot"

    def version(self):
        from localpilot_service import VERSION
        return VERSION

    async def setup(self, environment):
        result = await environment.exec(command="pwd", timeout_sec=10)
        cwd = (result.stdout or "").strip()
        if result.return_code != 0 or not cwd.startswith("/") or "\n" in cwd:
            raise RuntimeError("Could not identify the task container working directory")
        self.container_cwd = str(PurePosixPath(cwd))

    async def run(self, instruction, environment, context):
        if self.container_cwd is None:
            raise RuntimeError("Harbor setup must complete before run")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        # This empty host directory only satisfies registry identity. All model
        # tools are the container bridge; built-in host tools are not registered.
        identity = self.logs_dir / "registry-identity"
        identity.mkdir(exist_ok=True)
        registry = ToolRegistry(identity, permission_mode="full-permission",
                                data_policy=self.data_policy)
        shell = ContainerShell(environment, asyncio.get_running_loop(), self.container_cwd)
        registry.register("shell", shell, ToolRiskMetadata(mutating=True, requires_shell=True,
            external_side_effect=True), schema={"type": "function", "function": {
                "name": "shell", "description": "Run a command in the Harbor task container, never the host. Use Shell to inspect and edit task files. Exit zero is not task verification.",
                "parameters": {"type": "object", "properties": {
                    "command": {"type": "string", "minLength": 1, "maxLength": 16000},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 3600}},
                    "required": ["command"], "additionalProperties": False}}})
        session = AgentSession(registry, backend=self.backend,
            policy="cloud-only" if self.cloud else "local-only", data_policy=self.data_policy,
            permission_mode="full-permission", budgets=self.budgets,
            engine_policy=EngineV5Policy(), retry_policy=RetryPolicy(max_attempts=1),
            event_callback=self._record_event,
            system_prompt="You are LocalPilot. Work only through the shell tool in the task container. The container working directory is " + self.container_cwd + ". "
                "Do not assume Python or other optional programs are installed. Check availability with command -v NAME || true before using them. "
                "Keep mutations and optional verification in separate shell calls: a later command failure leaves earlier effects uncertain. Never repeat an uncertain mutation.")
        context.metadata = {"runtime": "AgentSession", "engine": "v5",
            "tool_target": "harbor_task_environment", "budgets": asdict(self.budgets),
            "cost_status": "UNKNOWN", "subagents": "disabled_in_this_adapter"}
        if self.measured_local:
            context.cost_usd = 0
            context.metadata['cost_status'] = 'LOCAL_API_ZERO_HARDWARE_AND_ENERGY_UNMEASURED'
        worker = asyncio.create_task(asyncio.to_thread(self._run_session, session, instruction))
        worker.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        try:
            result = await asyncio.shield(worker)
            (self.logs_dir / "localpilot-result.json").write_text(
                json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n")
            context.metadata.update(runtime_status=result.status, task_outcome=result.task_outcome)
            # Usage is complete only when every request has reported it. No
            # price table is guessed, and an unsuccessful request can still cost.
            metrics = result.runtime_metrics or {}
            calls = result.model_calls
            if calls and not metrics.get("failed_attempts"):
                for field, source in (("n_input_tokens", "input_tokens"),
                                      ("n_output_tokens", "output_tokens"),
                                      ("n_cache_tokens", "prompt_cache_hit_tokens")):
                    values = [getattr(call, source) for call in calls]
                    if all(value is not None for value in values):
                        setattr(context, field, sum(values))
            if result.status != "completed":
                raise RuntimeError("LocalPilot execution ended with " + result.status)
        except asyncio.CancelledError:
            session.request_cancel()
            context.metadata["cancellation"] = "requested; container process termination unconfirmed"
            # environment.exec cancellation has no portable process-kill
            # receipt. Leave this trial UNKNOWN for Harbor to tear down.
            raise

    def _record_event(self, event):
        with (self.logs_dir / "localpilot-events.jsonl").open("a") as stream:
            stream.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    @staticmethod
    def _run_session(session, instruction):
        try:
            return session.run_turn(instruction)
        finally:
            session.close()
            close = getattr(session.current_backend, 'close_counter', None)
            if close:
                close()
