"""Run a scripted AgentSession against actual native AX. No model is called."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

from agent.backends import BackendCapabilities, BackendResponse, Message, ModelInfo, ToolCall
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from .build import FIXTURE_ID
from .macos import MacOSAXAdapter
from .runtime import ComputerRuntime


class FixtureDriver:
    """Finite scripted backend using only observed tool results; not an LLM."""
    is_local = False
    model_info = ModelInfo("script", "native-AX-validation-driver", 131072)
    capabilities = BackendCapabilities(supports_tool_calling=True)
    def __init__(self, value):
        self.step = 0
        self.value = value
        self.target = None
    def request(self, messages, **kwargs):
        self.step += 1
        if not kwargs.get("tools"):
            return BackendResponse(Message("assistant", "Scripted flow reached the Runtime finalization boundary."))
        last = next((json.loads(m.content) for m in reversed(messages) if m.role == "tool"), {})
        data = last.get("result", {})
        names = {1: "manage_goal", 2: "inspect_tree", 3: "find_element", 4: "set_value", 5: "inspect_tree",
                 6: "find_element", 7: "press", 8: "verify"}
        name = names.get(self.step)
        if not name:
            return BackendResponse(Message("assistant", "Scripted native AX flow completed; independent host check required."))
        args = {"app": FIXTURE_ID}
        post = lambda id, value: {"selector": {"identifier": id}, "attribute": "value", "equals": value}
        if self.step == 1:
            args = {"action": "create", "description": "Verify native semantic AX value and press"}
        elif self.step in {3, 6}:
            args["selector"] = {"identifier": "lp.fixture.input" if self.step == 3 else "lp.fixture.apply"}
            if self.step == 6:
                old = next(n["value"] for n in data["nodes"] if n.get("identifier") == "lp.fixture.result")
                count = int(old.rsplit(":", 1)[1]) if old.startswith("applied:") else 0
                self.target = f"applied:{self.value}:{count + 1}"
        elif self.step in {4, 7}:
            args.update(element=data["element"], observation=data["observation"])
            args["postcondition"] = post("lp.fixture.input", self.value) if self.step == 4 else post("lp.fixture.result", self.target)
            if self.step == 4:
                args["value"] = self.value
        elif self.step == 8:
            args["postcondition"] = post("lp.fixture.result", self.target)
        return BackendResponse(Message("assistant", None, [ToolCall(f"native-{self.step}", name, json.dumps(args))]))


def run(output):
    adapter = MacOSAXAdapter([FIXTURE_ID])
    runtime = ComputerRuntime(adapter, allowed_apps=[FIXTURE_ID])
    registry = create_default_registry(Path.cwd(), permission_mode="approve-mutations")
    value = f"V2 native Session {time.time_ns()}"
    backend = FixtureDriver(value)
    session = AgentSession(registry, backend=backend, policy="cloud-only", computer_runtime=runtime,
        streaming=False, budgets=SessionBudgets(max_steps=12, max_tool_calls=16, max_token_units=1048576))
    before = adapter.environment()
    try:
        result = session.run_turn("Run a disposable AX fixture validation through the shared Runtime.")
        approvals = 0
        while result.status == "approval_required":
            approvals += 1
            result = session.approve()  # Explicit harness approval, not model approval.
        independent = adapter.inspect_tree(FIXTURE_ID)
        actual = next(n["value"] for n in independent["nodes"] if n.get("identifier") == "lp.fixture.result")
        after = adapter.environment()
        passed = result.status == "completed" and actual == backend.target and before["mouse"] == after["mouse"] and before["frontmost_pid"] == after["frontmost_pid"]
        report = {"status": "passed" if passed else "failed", "evidence": "scripted_AgentSession_with_real_native_AX",
            "os": platform.platform(), "model_calls": 0, "scripted_backend_requests": backend.step,
            "host_harness_approvals": approvals, "independent_result": actual, "expected": backend.target,
            "before": before, "after": after, "runtime": runtime.summary(), "engineering_status": result.engineering_status,
            "goal_records": session._goal_records(), "events": [e.to_dict() for e in session.events.events],
            "permission_audit": registry.gateway.audit,
            "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [
                Path("computer/native/AXBridge.swift"), Path("computer/runtime.py"), Path("agent/session.py")]}}
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: report[k] for k in ("status", "evidence", "model_calls", "host_harness_approvals", "runtime")}, ensure_ascii=False, indent=2))
        if not passed:
            raise RuntimeError("Native AX validation failed; inspect evidence.")
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/evidence/computer-use-v2/native-session.json")
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
