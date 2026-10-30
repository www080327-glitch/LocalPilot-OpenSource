"""Host entrypoint: python -m localpilot_api --workspace ..."""
import argparse
import math
import os
from pathlib import Path

from agent.deepseek import DeepSeekBackend
from agent.permissions import PermissionMode
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.routing import RoutingPolicy
from agent.safety import CapabilityPolicy
from agent.serving import add_serving_arguments, configured_backend
from agent.session import AgentSession, SessionBudgets
from agent.worker_tiers import configure_workers
from .server import APIServer
from .service import TaskService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--route", default="localpilot", help="Public logical model ID, independent of backend model")
    parser.add_argument("--cloud-model", default="deepseek-flash")
    parser.add_argument("--permission-mode", choices=[p.value for p in PermissionMode], default="approve-mutations")
    parser.add_argument("--policy", choices=[p.value for p in RoutingPolicy], default="balanced")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--thinking")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--allow-host-execute", action="store_true")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument('--max-tool-calls', type=int, default=12)
    parser.add_argument('--max-worker-steps', type=int, default=3)
    parser.add_argument('--max-worker-tool-calls', type=int, default=4)
    parser.add_argument('--max-worker-token-units', type=int, default=32768)
    parser.add_argument("--max-token-units", type=int, default=262144, help="Existing Runtime byte admission budget; not provider token usage")
    parser.add_argument("--max-sessions", type=int, default=64)
    parser.add_argument("--max-tasks", type=int, default=512)
    parser.add_argument("--runtime-db", help="Optional private SQLite runtime database; default is memory")
    parser.add_argument("--auto-resume-safe", action="store_true", help="Continue recovered SAFE_TO_RESUME checkpoints on startup")
    parser.add_argument('--finalization-recovery-attempts',type=int,choices=range(4),default=0,
        help='Opt-in bounded final-only delivery attempts (0 preserves V1.4; 1-3 include failures/interruption)')
    parser.add_argument('--async-subagents', action='store_true', help='Opt-in V4.3 file-only asynchronous child dispatch')
    parser.add_argument('--hybrid', action='store_true', help='Opt-in host catalog, canonical handoff and cloud egress')
    parser.add_argument('--hybrid-primary', choices=['local', 'cloud'])
    parser.add_argument('--cloud-egress', choices=['LOCAL_ONLY', 'CLOUD_ALLOWED', 'REQUIRES_APPROVAL'], default='REQUIRES_APPROVAL')
    parser.add_argument('--cloud-egress-path', action='append', default=[], help='Exact workspace path whose read body may leave the host')
    parser.add_argument('--hybrid-auto-failover', action='store_true', help='Bounded transient failure fallback at safe model boundaries')
    parser.add_argument('--async-global-limit', type=int, default=4)
    parser.add_argument('--async-session-limit', type=int, default=2)
    parser.add_argument('--async-model-limit', type=int, default=2)
    parser.add_argument('--async-local-model-limit', type=int)
    parser.add_argument('--async-cloud-model-limit', type=int)
    parser.add_argument('--async-child-limit', type=int, default=8)
    parser.add_argument('--async-ram-budget-mib', type=int, default=1024)
    parser.add_argument("--computer-app", action="append")
    parser.add_argument("--computer-observation-ttl", type=float, default=30, help="AX observation freshness limit in seconds; native identity checks still apply")
    parser.add_argument("--computer-background-qualified-app", action="append")
    parser.add_argument("--computer-experimental-native-targets", help="Host qualification JSON; default-off native keyboard")
    add_serving_arguments(parser)
    args = parser.parse_args(argv)
    if not math.isfinite(args.computer_observation_ttl) or not 0 < args.computer_observation_ttl <= 3600:
        parser.error("computer observation TTL must be within (0, 3600]")
    api_key = os.environ.get("LOCALPILOT_API_KEY")
    if not api_key:
        parser.error("Set LOCALPILOT_API_KEY for API authentication")
    workspace = Path(args.workspace).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        parser.error("workspace must be an existing directory")
    if args.computer_background_qualified_app and not set(args.computer_background_qualified_app) <= set(args.computer_app or []):
        parser.error("Background qualification must be within --computer-app scope")
    if args.computer_app and args.max_sessions != 1:
        parser.error("Computer Use requires --max-sessions 1 (one device owner)")
    if args.computer_experimental_native_targets and not args.computer_app:
        parser.error("Native qualification requires --computer-app scope")
    if args.backend_verify or args.backend_status or args.backend_report:
        parser.error("Run backend diagnostics with python -m agent before starting the API")
    from agent.async_runtime import AsyncPolicy
    if args.async_subagents and args.computer_app:
        parser.error('Async subagents are qualified for file tools only')
    if not args.async_subagents and (args.async_local_model_limit is not None or args.async_cloud_model_limit is not None):
        parser.error('Model category admission limits require --async-subagents')
    async_policy = AsyncPolicy(max_running_children=args.async_global_limit,
        max_local_model_requests=args.async_local_model_limit, max_cloud_model_requests=args.async_cloud_model_limit,
        max_running_per_session=args.async_session_limit, max_model_requests=args.async_model_limit,
        max_children_per_turn=args.async_child_limit, ram_budget_mib=args.async_ram_budget_mib) if args.async_subagents else None
    data_policy = DataPolicy(local_only=args.local_only)
    from agent.finalization import FinalizationPolicy
    finalization = FinalizationPolicy(args.finalization_recovery_attempts) if args.finalization_recovery_attempts else None
    from agent.hybrid import HybridPolicy, CloudEgressPolicy
    hybrid = HybridPolicy(CloudEgressPolicy(args.cloud_egress, tuple(args.cloud_egress_path)),
                          automatic_failover=args.hybrid_auto_failover) if args.hybrid else None
    if not args.hybrid and (args.hybrid_primary or args.cloud_egress_path or args.hybrid_auto_failover or args.cloud_egress != 'REQUIRES_APPROVAL'):
        parser.error('Hybrid options require --hybrid')
    def factory(callback):
        cloud = None
        from agent.cloud_credentials import deepseek_configured
        if not args.local_only and deepseek_configured():
            cloud = DeepSeekBackend(model=args.cloud_model, data_policy=data_policy)
        local = configured_backend(args)
        workers, availability = ({}, {}) if args.local_only else configure_workers(data_policy=data_policy)
        registry = create_default_registry(workspace, permission_mode=args.permission_mode,
            capabilities=CapabilityPolicy(execute=args.allow_host_execute), data_policy=data_policy)
        computer = None
        if args.computer_app:
            from computer.local_native import configured_computer_backend
            from computer.runtime import ComputerRuntime
            computer = ComputerRuntime(configured_computer_backend(args.computer_app, args.computer_experimental_native_targets), allowed_apps=args.computer_app,
                background_safe_apps=args.computer_background_qualified_app, observation_ttl=args.computer_observation_ttl)
        return AgentSession(registry, cloud_backend=cloud, local_backend=local, cloud_worker_backends=workers,
            worker_availability=availability, data_policy=data_policy,
            policy="local-only" if args.local_only else args.policy, thinking=args.thinking,
            budgets=SessionBudgets(max_steps=args.max_steps, max_token_units=args.max_token_units,
                max_tool_calls=args.max_tool_calls, max_worker_steps=args.max_worker_steps,
                max_worker_tool_calls=args.max_worker_tool_calls, max_worker_token_units=args.max_worker_token_units,
                max_subagents_per_turn=args.async_child_limit if async_policy else 2), plan_mode=args.plan,
            event_callback=callback, computer_runtime=computer, finalization_policy=finalization, async_policy=async_policy,
            hybrid_policy=hybrid, hybrid_primary=args.hybrid_primary)
    service = TaskService({args.route: factory}, max_sessions=args.max_sessions, max_tasks=args.max_tasks,
        persistence=args.runtime_db, auto_resume=args.auto_resume_safe, async_policy=async_policy)
    server = APIServer((args.host, args.port), service, api_key=api_key,
                       control_token=os.environ.get("LOCALPILOT_API_CONTROL_TOKEN"))
    print(f"LocalPilot Runtime API: http://{args.host}:{server.server_port} · route={args.route} · workspace={workspace}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
