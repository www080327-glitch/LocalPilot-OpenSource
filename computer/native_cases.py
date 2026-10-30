"""Real AX fault and postcondition experiments on the disposable fixture only."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from agent.registry import create_default_registry
from .build import BUILD, FIXTURE_ID
from .macos import MacOSAXAdapter
from .runtime import ComputerRuntime


def post(identifier, value):
    return {"selector": {"identifier": identifier}, "attribute": "value", "equals": value}


def launch():
    subprocess.run(["open", "-g", str(BUILD / "LocalPilot AX Fixture.app")], check=True)


def run(output):
    adapters = [MacOSAXAdapter([FIXTURE_ID]), MacOSAXAdapter([FIXTURE_ID])]
    primary, external = adapters
    runtime = ComputerRuntime(primary, allowed_apps=[FIXTURE_ID])
    registry = create_default_registry(Path.cwd(), permission_mode="full-permission")
    runtime.register_tools(registry)
    results = []
    def record(name, success, detail):
        results.append({"case": name, "status": "passed" if success else "failed", "detail": detail})
        if not success:
            raise AssertionError(name)
    def native_find(adapter, identifier):
        tree = adapter.inspect_tree(FIXTURE_ID)
        return next(n for n in tree["nodes"] if n.get("identifier") == identifier)
    def found(identifier):
        runtime.observe(FIXTURE_ID)
        return runtime.find_element(FIXTURE_ID, {"identifier": identifier})
    def action(name, target, value, expected_id, expected):
        hit = found(target)
        args = {"app": FIXTURE_ID, "element": hit["element"], "observation": hit["observation"], "postcondition": post(expected_id, expected)}
        if name == "set_value":
            args["value"] = value
        return registry.call(name, args)
    before = primary.environment()
    try:
        tree = runtime.inspect_tree(FIXTURE_ID)
        record("AX_tree_enumeration", tree.get("status") == "ok" and len(tree["nodes"]) >= 4, {"nodes": len(tree["nodes"]), "windows": tree["window_count"]})
        value = "Native fault suite " + str(time.time_ns())
        set_result = action("set_value", "lp.fixture.input", value, "lp.fixture.input", value)
        record("semantic_set_value", set_result.get("verified") is True, set_result)
        old = native_find(external, "lp.fixture.result")["value"]
        next_count = int(old.rsplit(":", 1)[1]) + 1 if old.startswith("applied:") else 1
        press_result = action("press", "lp.fixture.apply", None, "lp.fixture.result", f"applied:{value}:{next_count}")
        record("semantic_press_postcondition", press_result.get("verified") is True, press_result)
        verified = registry.call("verify", {"app": FIXTURE_ID, "postcondition": post("lp.fixture.result", f"applied:{value}:{next_count}")})
        record("fresh_independent_postcondition", verified["verified"], verified)
        stale = found("lp.fixture.input")
        runtime.observe(FIXTURE_ID)
        rejected = registry.call("set_value", {"app": FIXTURE_ID, "element": stale["element"], "observation": stale["observation"], "value": "should not apply", "postcondition": post("lp.fixture.input", "should not apply")})
        record("stale_observation", rejected.get("error") == "stale_observation", rejected)
        old_field = native_find(primary, "lp.fixture.input")
        other_field = native_find(external, "lp.fixture.input")
        external.action(FIXTURE_ID, other_field["handle"], "set_value", value="external edit", allow_frontmost=False)
        changed = primary.action(FIXTURE_ID, old_field["handle"], "set_value", value="should not apply", allow_frontmost=False)
        record("element_changed_before_dispatch", changed.get("error") == "element_changed" and not changed.get("action_sent"), changed)
        old_field = native_find(primary, "lp.fixture.input")
        replace = native_find(external, "lp.fixture.replace")
        external.action(FIXTURE_ID, replace["handle"], "press", action="AXPress", allow_frontmost=False)
        replaced = primary.action(FIXTURE_ID, old_field["handle"], "set_value", value="should not apply", allow_frontmost=False)
        record("stale_replaced_native_element", replaced.get("error") in {"stale_element", "element_changed"} and not replaced.get("action_sent"), replaced)
        runtime.observe(FIXTURE_ID)
        takeover = runtime.take_over()
        other_field = native_find(external, "lp.fixture.input")
        external.action(FIXTURE_ID, other_field["handle"], "set_value", value="host simulates manual edit", allow_frontmost=False)
        resumed = runtime.resume()
        record("scripted_host_handoff_with_real_AX_change", takeover["quiescent"] and resumed["changes"][0]["changed"], resumed)
        failed = action("set_value", "lp.fixture.input", "applied but wrong expected", "lp.fixture.input", "impossible expected")
        record("wrong_postcondition_after_actual_write", failed["action_sent"] and not failed["verified"] and failed["ax_status"] == "ok", failed)
        assert runtime.paused
        assert runtime.resume()["status"] == "ok"  # Explicit harness resync after failed postcondition.
        fallback = action("expand", "lp.fixture.apply", None, "lp.fixture.result", "expanded")
        record("unsupported_AX_fallback_accounting", fallback.get("error") == "unsupported_action" and runtime.summary()["rates"]["vision_fallback_rate"] == 0, fallback)
        after = primary.environment()
        record("mouse_and_foreground_unchanged", before["mouse"] == after["mouse"] and before["frontmost_pid"] == after["frontmost_pid"], {"before": before, "after": after})
        old_field = native_find(primary, "lp.fixture.input")
        for app in primary.inspect_apps()["apps"]:
            pid = app["pid"]
            executable = subprocess.check_output(["ps", "-p", str(pid), "-o", "comm="], text=True).strip()
            if "LocalPilot AX Fixture.app/Contents/MacOS/AXFixture" not in executable:
                raise RuntimeError("Only the disposable fixture process may be terminated")
            os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if not primary.inspect_apps()["apps"]:
                break
            time.sleep(0.025)
        closed = primary.action(FIXTURE_ID, old_field["handle"], "set_value", value="should not apply", allow_frontmost=False)
        record("app_closed_before_native_write", closed.get("error") == "app_closed" and not closed.get("action_sent"), closed)
    finally:
        summary = runtime.summary()
        runtime.close()
        external.close()
        launch()
        report = {"evidence": "real_native_AX_plus_explicit_host_fault_injection", "status": "passed" if len(results) == 12 and all(r["status"] == "passed" for r in results) else "failed",
            "cases": results, "runtime": summary, "model_calls": 0, "physical_lock_tests": "NOT_RUN", "actual_human_manual_intervention": "NOT_RUN"}
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(results)}/12 native fixture experiments: {report['status']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/evidence/computer-use-v2/native-cases.json")
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
