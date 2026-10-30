"""Real native AX PoC. Does not use a model, Session or Codex private implementation."""
import argparse
import json
from pathlib import Path
import time

from .build import FIXTURE_ID
from .macos import MacOSAXAdapter


def run(adapter):
    before = adapter.environment()
    tree = adapter.inspect_tree(FIXTURE_ID)
    if tree.get("status") != "ok":
        raise RuntimeError(json.dumps(tree))
    value = f"LocalPilot AX PoC {time.time_ns()}"
    field = next(n for n in tree["nodes"] if n.get("identifier") == "lp.fixture.input")
    set_receipt = adapter.action(FIXTURE_ID, field["handle"], "set_value", value=value, allow_frontmost=False)
    tree = adapter.inspect_tree(FIXTURE_ID)
    assert next(n["value"] for n in tree["nodes"] if n.get("identifier") == "lp.fixture.input") == value
    button = next(n for n in tree["nodes"] if n.get("identifier") == "lp.fixture.apply")
    press_receipt = adapter.action(FIXTURE_ID, button["handle"], "press", action="AXPress", allow_frontmost=False)
    after_tree = adapter.inspect_tree(FIXTURE_ID)
    result = next(n["value"] for n in after_tree["nodes"] if n.get("identifier") == "lp.fixture.result")
    assert result.startswith(f"applied:{value}:")
    after = adapter.environment()
    assert before["mouse"] == after["mouse"]
    assert before["frontmost_pid"] == after["frontmost_pid"]
    assert set_receipt["ax_error"] == press_receipt["ax_error"] == 0
    return {"status": "passed", "evidence": "real_native_AX", "before": before, "after": after,
        "enumerated_nodes": len(after_tree["nodes"]), "set_value": set_receipt, "press": press_receipt,
        "result": result, "mouse_unchanged": True, "frontmost_unchanged": True,
        "screenshots": 0, "coordinate_actions": 0, "model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    adapter = MacOSAXAdapter([FIXTURE_ID])
    try:
        result = run(adapter)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
