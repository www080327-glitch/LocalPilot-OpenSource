"""Command-line entry point: python -m agent [options] [task]."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .deepseek import DeepSeekBackend
from .cloud_credentials import CloudCredentialError
from .finalization import FinalizationPolicy
from .loop import MaxStepsExceeded
from .session import AgentSession, SessionBudgets
from .cli import EventRenderer, interactive
from .local_http import LocalHTTPBackend
from .routing import RoutingPolicy
from .registry import PROFILES, create_default_registry
from .safety import PERMISSION_MODES
from .safety import CapabilityPolicy
from .policy import DataPolicy
from .profiles import PROMPT_PROFILES, TOOL_PROFILES
from .worker_tiers import configure_workers
from .serving import add_serving_arguments, configured_backend
from .backend_verification import verify_backend, render_report, write_report


def main(argv=None, *, recommendation=None):
    parser = argparse.ArgumentParser(description="Run a LocalPilot coding/file Agent task.")
    parser.add_argument(
        "--workspace", default=".", help="Fixed workspace root for tools (default: current directory)."
    )
    parser.add_argument("--model", default="deepseek-flash", help="DeepSeek model name.")
    add_serving_arguments(parser)
    parser.add_argument("--worker-light-model", default="openai:gpt-6-luna",
                        help="LIGHT worker mapping as provider:model (openai or deepseek).")
    parser.add_argument("--worker-strong-model", default="openai:gpt-6-sol",
                        help="STRONG worker mapping as provider:model (openai or deepseek).")
    parser.add_argument("--max-steps", type=int, default=8, help="Maximum request attempts per turn, including retry/worker/judge; reserves a final-only attempt.")
    parser.add_argument('--finalization-recovery-attempts',type=int,choices=range(4),default=0,
        help='Opt-in bounded final-only attempts; default 0 preserves V1.4')
    parser.add_argument(
        "--minimal-mode", action="store_true",
        help="Alias for --prompt-profile minimal_0; tools and permissions are unchanged.",
    )
    parser.add_argument("--profile", choices=PROFILES, default="standard")
    parser.add_argument("--prompt-profile", choices=PROMPT_PROFILES)
    parser.add_argument("--tool-profile", choices=TOOL_PROFILES)
    parser.add_argument("--max-tool-calls", type=int, default=12)
    parser.add_argument("--max-token-units", type=int, default=262144,
                        help="Conservative byte admission per turn, not provider token billing.")
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--max-workers-per-turn", type=int, default=2)
    parser.add_argument("--max-worker-steps", type=int, default=3)
    parser.add_argument("--max-worker-tool-calls", type=int, default=4)
    parser.add_argument("--max-worker-token-units", type=int, default=32768)
    parser.add_argument("--local-only", action="store_true", help="Hard no-cloud policy; requires a configured local backend.")
    parser.add_argument("--allow-host-execute", action="store_true", help="Opt into experimental unsandboxed host commands, still subject to the Gateway.")
    parser.add_argument("--permission-mode", choices=PERMISSION_MODES, default="approve-mutations")
    parser.add_argument("--policy", choices=[p.value for p in RoutingPolicy], default="balanced")
    parser.add_argument("--thinking", help="Exact provider-native thinking effort for the selected model.")
    parser.add_argument("--reasoning", choices=["hidden", "summary", "full"], default="summary")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--computer-app", action="append", help="Enable AX Computer Use Alpha for an explicit running macOS bundle ID; repeat for more apps. UI evidence can be sent to the configured backend.")
    parser.add_argument("--computer-background-qualified-app", action="append", help="Host opt-in after controlled background qualification; must also be in --computer-app scope")
    parser.add_argument("--no-stream", action="store_true", help="Use buffered responses.")
    parser.add_argument("--audit-log", help="Host-selected JSONL path for bounded policy/receipt metadata.")
    parser.add_argument("--usage-log", help="Optional JSONL file for lightweight usage metrics.")
    parser.add_argument(
        "--debug-trace",
        action="store_true",
        help="Print step and tool-result summaries to stderr (never full file content).",
    )
    parser.add_argument("task", nargs="*", help="Task text; if omitted, enter it interactively.")
    args = parser.parse_args(argv)

    task = " ".join(args.task).strip()
    computer_runtime = None
    try:
        local = configured_backend(args, recommendation)
        if args.backend_status or args.backend_verify:
            if args.task:
                raise ValueError("Backend diagnostics do not accept an Agent task")
            if not isinstance(local, LocalHTTPBackend):
                print("Local backend: Not Configured")
                return 1
            if args.local_only and (not local.is_loopback or local.profile.service_location == "remote"):
                raise ValueError("LOCAL_ONLY forbids a remote service, including a declared remote tunnel")
            if args.backend_verify:
                report = verify_backend(local, args.backend_checks.split(","), evidence_kind=args.verification_evidence)
                print(render_report(report))
                if args.backend_report:
                    for path in write_report(report, args.backend_report):
                        print("Report: " + str(path))
                return 0 if report["passed"] else 2
            print(json.dumps(local.profile.snapshot(), ensure_ascii=False, indent=2))
            return 0
        if args.backend_report:
            raise ValueError("--backend-report requires --backend-verify")
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise NotADirectoryError(f"Workspace root is not a directory: {workspace}")
        data_policy = DataPolicy(local_only=args.local_only)
        backend = None
        if not args.local_only:
            try:
                backend = DeepSeekBackend(model=args.model, data_policy=data_policy)
            except ValueError as error:
                if not isinstance(error, CloudCredentialError) or error.category != 'missing_credentials':
                    raise
                print("Cloud backend: Missing Credentials — 请设置 DEEPSEEK_API_KEY。", file=sys.stderr)
        workers, worker_availability = ({}, {}) if args.local_only else configure_workers({
            "LIGHT": args.worker_light_model, "STRONG": args.worker_strong_model},
            data_policy=data_policy)
        local_state = local.status() if isinstance(local, LocalHTTPBackend) else None
        local_available = bool(local_state and local_state["model_available"])
        if not backend and not local_available:
            print("无法进入 Agent 会话：云端和本地后端均不可用。", file=sys.stderr)
            print("请设置 DEEPSEEK_API_KEY，或启动本地服务并指定 --local-base-url 和 --local-model。", file=sys.stderr)
            if local_state and local_state.get("error"):
                print("本地后端：" + local_state["error"], file=sys.stderr)
            return 1
        trace = (lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr)) if args.debug_trace else None
        registry = create_default_registry(workspace, profile=args.profile,
            tool_profile=args.tool_profile, permission_mode=args.permission_mode,
            capabilities=CapabilityPolicy(execute=args.allow_host_execute), data_policy=data_policy)
        renderer = EventRenderer()
        if args.computer_background_qualified_app and not args.computer_app:
            raise ValueError("Background qualification requires explicit --computer-app scope")
        if args.computer_background_qualified_app and not set(args.computer_background_qualified_app) <= set(args.computer_app):
            raise ValueError("Background qualification must be within --computer-app scope")
        if args.computer_app:
            from computer.macos import MacOSAXAdapter
            from computer.runtime import ComputerRuntime
            computer_runtime = ComputerRuntime(MacOSAXAdapter(args.computer_app), allowed_apps=args.computer_app,
                background_safe_apps=args.computer_background_qualified_app)
        session = AgentSession(registry, cloud_backend=backend, local_backend=local,
            cloud_worker_backends=workers, worker_availability=worker_availability,
            policy="local-only" if args.local_only else args.policy, thinking=args.thinking,
            reasoning=args.reasoning,
            budgets=SessionBudgets(max_steps=args.max_steps, max_tool_calls=args.max_tool_calls,
                max_token_units=args.max_token_units, max_output_tokens=args.max_output_tokens,
                max_subagents_per_turn=args.max_workers_per_turn,
                max_worker_steps=args.max_worker_steps,
                max_worker_tool_calls=args.max_worker_tool_calls,
                max_worker_token_units=args.max_worker_token_units),
            data_policy=data_policy, trace=trace, event_callback=renderer,
            prompt_profile=args.prompt_profile or ("minimal_0" if args.minimal_mode else
                                                  "minimal_1" if args.profile == "minimal" else "standard"),
            streaming=not args.no_stream, plan_mode=args.plan, computer_runtime=computer_runtime,
            finalization_policy=FinalizationPolicy(args.finalization_recovery_attempts) if args.finalization_recovery_attempts else None)
        if isinstance(local, LocalHTTPBackend):
            state = local_state
            print("Local backend: " + ("Available" if state["model_available"] else
                  "Unavailable — " + state.get("error", "model not listed")))
        else:
            print("Local backend: Unavailable / Not Configured")
            print("请配置 --local-base-url 和 --local-model；不会自动下载模型。")
        if backend:
            print("Cloud backend: Available（凭据已配置，尚未探测网络）；对话和获准工具内容会发送至云端。")
        if not args.local_only:
            for tier, info in worker_availability.items():
                state = "Configured / API access unverified" if info["available"] else "Unavailable / missing credentials"
                print(f"Worker {tier}: {info['provider']}:{info['configured_model']} — {state}")
        def log_result(result):
            if args.usage_log:
                record = {"timestamp": datetime.now(timezone.utc).isoformat(),
                          "model": session.current_primary_model, **result.usage_summary()}
                with Path(args.usage_log).expanduser().open("a", encoding="utf-8") as log_file:
                    log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        try:
            if not task:
                return interactive(session, renderer, on_result=log_result)
            result = session.run_turn(task)
            renderer.finish(result)
            log_result(result)
            return 3 if result.status == "approval_required" else (0 if result.status == "completed" else 2)
        finally:
            if args.audit_log:
                with Path(args.audit_log).expanduser().open("a", encoding="utf-8") as audit_file:
                    for event in registry.gateway.audit:
                        audit_file.write(json.dumps(event, ensure_ascii=False) + "\n")
            session.close()
    except MaxStepsExceeded as error:
        print(f"Agent stopped: {error}", file=sys.stderr)
        return 2
    except (ValueError, OSError, RuntimeError) as error:
        if computer_runtime:
            computer_runtime.close()
        print(f"Agent error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
