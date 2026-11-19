"""Optional Harbor adapter: the product AgentSession drives task-container Shell.

Install pinned Harbor in an evaluation environment; no Harbor dependency is
added to the desktop or Core. There is deliberately no host filesystem tool.
"""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path, PurePosixPath
import threading

from harbor.agents.base import BaseAgent

from agent.async_runtime import AsyncPolicy
from agent.engine_v5 import EngineV5Policy
from agent.permissions import ToolRiskMetadata
from agent.policy import DataPolicy
from agent.registry import ToolRegistry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from localpilot_service.backend_contract import (ServiceDeepSeekNativeBackend,
    ServiceOpenAIBackend, ServiceOpenAICloudBackend)
from scripts.harbor_orchestration import orchestration_contract


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


class ContainerRegistryFactory:
    def __init__(self, shell):
        self.shell = shell
        self.registries = []

    def __call__(self, workspace, *, permission_mode, capabilities=None, data_policy):
        registry = ToolRegistry(workspace, permission_mode=permission_mode,
                                capabilities=capabilities, data_policy=data_policy)
        registry.register("shell", self.shell, ToolRiskMetadata(mutating=True, requires_shell=True,
            external_side_effect=True), schema={"type": "function", "function": {
                "name": "shell", "description": "Run a command in the Harbor task container, never the host. Use Shell to inspect and edit task files. Exit zero is not task verification.",
                "parameters": {"type": "object", "properties": {
                    "command": {"type": "string", "minLength": 1, "maxLength": 16000},
                    "timeout": {"type": "integer", "minimum": 1, "maximum": 3600}},
                    "required": ["command"], "additionalProperties": False}}})
        self.registries.append(registry)
        return registry


class LocalPilotHarborAgent(BaseAgent):
    def __init__(self, logs_dir, model_name=None, *, endpoint,
                 provider_kind="local-openai", api_key_env=None,
                 context_tokens=65536, max_steps=24, max_tool_calls=40,
                 max_token_units=1000000, max_output_tokens=2048,
                 model_timeout=120, chat_template_kwargs=None, model_budget=None,
                 orchestration="single", max_children=None, max_running_children=None,
                 max_worker_steps=None, max_worker_tool_calls=None,
                 max_worker_token_units=None, max_worker_output_tokens=None, **kwargs):
        self.orchestration = orchestration_contract({'orchestration':orchestration,
            'max_children':max_children, 'max_running_children':max_running_children,
            'provider_kind':provider_kind, 'model_budget':model_budget,
            'max_worker_steps':max_worker_steps, 'max_worker_tool_calls':max_worker_tool_calls,
            'max_worker_token_units':max_worker_token_units, 'max_worker_output_tokens':max_worker_output_tokens,
            'max_output_tokens':max_output_tokens})
        if provider_kind not in {"local-openai", "remote-openai", "deepseek-native", "openai"}:
            raise ValueError("Use an explicit local-openai, remote-openai, deepseek-native or openai provider")
        if provider_kind == "openai" and api_key_env is None:
            api_key_env = "OPENAI_API_KEY"
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
            max_subagents_per_turn=self.orchestration['max_children'],
            **self.orchestration.get('worker_budgets', {}))
        self.data_policy = DataPolicy(local_only=not cloud)
        if provider_kind == "deepseek-native":
            if chat_template_kwargs:
                raise ValueError("Native Messages does not accept local chat template overrides")
            self.backend = ServiceDeepSeekNativeBackend(base_url=endpoint, model=model_name,
                api_key=key, data_policy=self.data_policy, effective_context=context_tokens,
                timeout=model_timeout, generation_parameters={"temperature": 0})
        else:
            backend_type = ServiceOpenAICloudBackend if provider_kind == "openai" else ServiceOpenAIBackend
            extra = {}
            if model_budget is not None:
                if provider_kind != 'local-openai':
                    raise ValueError('Measured model budgets require the local tokenizer transport')
                from scripts.harbor_model_budget import BudgetedLocalBackend
                backend_type = BudgetedLocalBackend
                extra = {'model_budget':model_budget, 'budget_log':Path(logs_dir)/'model-budget.jsonl',
                         'record_admission_denials':self.orchestration['mode'] == 'multi-agent'}
            self.backend = backend_type(base_url=endpoint, model=model_name,
                api_key=key, allow_remote=cloud, effective_context=context_tokens,
                timeout=model_timeout, supports_streaming=True, include_stream_usage=True,
                chat_template_kwargs=chat_template_kwargs,
                generation_parameters={} if provider_kind == "openai" else {"temperature": 0}, **extra)
        self.backend.is_local = not cloud
        self.cloud = cloud
        self.measured_local = model_budget is not None and not cloud
        self.container_cwd = None
        self._event_lock = threading.Lock()

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

    def _new_session(self, environment):
        if self.container_cwd is None:
            raise RuntimeError("Harbor setup must complete before run")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        # This empty host directory only satisfies registry identity. All model
        # tools are the container bridge; built-in host tools are not registered.
        identity = self.logs_dir / "registry-identity"
        identity.mkdir(exist_ok=True)
        shell = ContainerShell(environment, asyncio.get_running_loop(), self.container_cwd)
        factory = ContainerRegistryFactory(shell)
        registry = factory(identity, permission_mode="full-permission", data_policy=self.data_policy)
        child_options = {}
        child_prompt = ""
        if self.orchestration['mode'] == 'multi-agent':
            running = self.orchestration['max_running_children']
            child_options = {'child_registry_factory':factory,
                'child_registry_contract':{'kind':'harbor-container-shell', 'version':1, 'cwd':self.container_cwd},
                'async_policy':AsyncPolicy(max_running_children=running, max_running_per_session=running,
                    max_children_per_turn=self.orchestration['max_children'],
                    max_model_requests=1, max_local_model_requests=1, cpu_slots=running,
                    ram_budget_mib=64*running)}
            child_prompt = (" You may delegate independent work using mode=async, backend_preference=local. "
                "All workers share this same container, model and total request/token budget. "
                "Use read_only=false when a worker needs shell: arbitrary shell commands cannot be certified read-only. "
                "Give workers disjoint file ownership for edits, then collect their results with wait_children and verify them. "
                "Do not delegate just to increase the number of agents.")
        session = AgentSession(registry, backend=self.backend,
            policy="cloud-only" if self.cloud else "local-only", data_policy=self.data_policy,
            permission_mode="full-permission", budgets=self.budgets,
            engine_policy=EngineV5Policy(), retry_policy=RetryPolicy(max_attempts=1),
            event_callback=self._record_event, **child_options,
            system_prompt="You are LocalPilot. Work only through the shell tool in the task container. The container working directory is " + self.container_cwd + ". "
                "Do not assume Python or other optional programs are installed. Check availability with command -v NAME || true before using them. "
                "Keep mutations and optional verification in separate shell calls: a later command failure leaves earlier effects uncertain. Never repeat an uncertain mutation." + child_prompt)
        return session, factory

    async def run(self, instruction, environment, context):
        session, factory = self._new_session(environment)
        context.metadata = {"runtime": "AgentSession", "engine": "v5",
            "tool_target": "harbor_task_environment", "budgets": asdict(self.budgets),
            "cost_status": "UNKNOWN", "subagents": "disabled_in_this_adapter" if self.orchestration['mode'] == 'single' else "enabled_shared_container"}
        if self.orchestration['mode'] == 'multi-agent':
            context.metadata['orchestration'] = self.orchestration
        if self.measured_local:
            context.cost_usd = 0
            context.metadata['cost_status'] = 'LOCAL_API_ZERO_HARDWARE_AND_ENERGY_UNMEASURED'
        worker = asyncio.create_task(asyncio.to_thread(self._run_session, session, instruction, factory))
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
            accounted_denials = (self.orchestration['mode'] == 'multi-agent' and self.backend.disqualified is None
                and self.backend.requests == len(calls) and metrics.get('failed_attempts') == self.backend.denied_attempts)
            if calls and (not metrics.get("failed_attempts") or accounted_denials):
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
        with self._event_lock, (self.logs_dir / "localpilot-events.jsonl").open("a") as stream:
            stream.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def _run_session(self, session, instruction, factory):
        try:
            return session.run_turn(instruction)
        finally:
            try:
                session.close()
            finally:
                try:
                    if self.orchestration['mode'] == 'multi-agent':
                        self._record_orchestration(session, factory)
                finally:
                    close = getattr(session.current_backend, 'close_counter', None)
                    if close:
                        close()

    def _record_orchestration(self, session, factory):
        children = list(session._children.values())
        value = {'contract':self.orchestration,
            'shared_backend':session.current_backend is self.backend and all(child.current_backend is self.backend for child in children),
            'shared_scheduler':all(child._scheduler is session._scheduler for child in children),
            'model_slots':session._scheduler.policy.max_model_requests,
            'cancellation_requested':session._stop_requested.is_set(),
            'registries':[sorted(registry._tools) for registry in factory.registries],
            'children':[{key:record[key] for key in ('id','status','configured_model','read_only','model_calls')}
                        for record in session.subagents],
            'model_attempts':session._attempts, 'model_calls':len(session._usage),
            'failed_attempts':session._failed_attempts}
        for name in ('input_tokens','output_tokens'):
            counts = [getattr(call,name) for call in session._usage]
            value[name] = sum(counts) if all(count is not None for count in counts) else None
        (self.logs_dir/'localpilot-orchestration.json').write_text(json.dumps(value,indent=2) + '\n')
