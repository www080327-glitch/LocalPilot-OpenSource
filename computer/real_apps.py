"""Real App AX validation on explicit disposable content; no LLM or visual input.

This harness provisionally authorizes background trials, not general app
qualification. Failed results remain in the report. No private UI trees are saved.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from agent.registry import create_default_registry
from .macos import MacOSAXAdapter
from .runtime import ComputerRuntime

APPS = {"Finder": "com.apple.finder", "Safari": "com.apple.Safari", "TextEdit": "com.apple.TextEdit",
        "System Settings": "com.apple.systempreferences", "Chrome": "com.google.Chrome", "WeChat": "com.tencent.xinWeChat"}


def exact(selector, attribute, value):
    return {"selector": selector, "attribute": attribute, "equals": value}


class Trial:
    def __init__(self, app, scope, report):
        self.app, self.scope, self.report = app, scope, report
        self.adapter = MacOSAXAdapter([app])
        self.runtime = ComputerRuntime(self.adapter, allowed_apps=[app], background_safe_apps=[app], verification_timeout=1)
        self.registry = create_default_registry(Path.cwd(), permission_mode="approve-mutations")
        self.runtime.register_tools(self.registry)
        self.cases = []
        self.report[app] = {"evidence": "real_app_public_native_AX_controlled_trials", "cases": self.cases}

    def tree(self, **extra):
        tool_view = self.registry.call("inspect_tree", {"app": self.app, "max_nodes": 512, "max_depth": 18, **self.scope, **extra})
        record = self.runtime.observations.get(self.app)
        # Harness-only raw inspection for selecting known controlled controls.
        # Model-facing truncation remains explicit in the tool view.
        return {**record["tree"], "tool_view_nodes": len(tool_view.get("nodes", [])), "tool_view_omitted_nodes": tool_view.get("omitted_nodes", 0)} if record else tool_view

    def add(self, name, outcome, **details):
        case = {"case": name, "outcome": outcome, **details}
        self.cases.append(case)
        print(self.app, name, outcome, details.get("error", ""), flush=True)
        return case

    def enumerate(self):
        before = self.adapter.environment()
        tree = self.tree()
        after = self.adapter.environment()
        self.add("enumeration", "PASS" if tree.get("status") == "ok" and tree.get("nodes") else "BLOCKED",
            nodes=len(tree.get("nodes", [])), window_count=tree.get("window_count"), truncated=tree.get("truncated"),
            focused_window_fallback=tree.get("focused_window_fallback"), AXWindows_count=tree.get("AXWindows_count"),
            role_counts=dict(Counter(n["role"] for n in tree.get("nodes", []))),
            error=tree.get("error"), before=before, after=after)
        return tree

    def action(self, name, selector, condition, *, tool="press", **args):
        if self.runtime.paused:
            resumed = self.runtime.resume()
            self.add("host_resync_before_" + name, "PASS" if resumed.get("status") == "ok" else "BLOCKED", result=resumed, category="host_control")
        tree = self.tree()
        found = self.registry.call("find_element", {"app": self.app, "selector": selector})
        if found.get("status") != "ok":
            return self.add(name, "BLOCKED", category="functional_action", error=found.get("error"), action_sent=False)
        arguments = {"app": self.app, "element": found["element"], "observation": found["observation"], "postcondition": condition, **args}
        before_environment = self.adapter.environment()
        decision = self.registry.call(tool, arguments)
        approved = decision.get("status") == "approval_required"
        receipt = self.registry.call(tool, arguments, approved=True) if approved else decision
        after_environment = self.adapter.environment()
        fresh = self.adapter.inspect_tree(self.app, max_nodes=512, max_depth=18, **self.scope)
        independently_verified = self.runtime._postcondition(fresh, condition)
        # Repeat observation to expose transient/one-off state verification.
        repeat = self.adapter.inspect_tree(self.app, max_nodes=512, max_depth=18, **self.scope)
        repeat_verified = self.runtime._postcondition(repeat, condition)
        passed = receipt.get("status") == "ok" and independently_verified and repeat_verified
        case = self.add(name, "PASS" if passed else "FAIL" if receipt.get("action_sent") else "BLOCKED",
            category="functional_action", tool=tool, selector=selector, postcondition=condition,
            harness_approval=approved, receipt=receipt, action_sent=receipt.get("action_sent", False),
            independently_verified=independently_verified, repeat_verified=repeat_verified,
            error=receipt.get("error"), vision_calls=0, coordinate_calls=0)
        case.update(before_environment=before_environment, after_environment=after_environment)
        return case

    def finish(self):
        self.report[self.app]["runtime"] = self.runtime.summary()
        self.report[self.app]["permission_audit_count"] = len(self.registry.gateway.audit)
        self.runtime.close()


def run(output):
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "model_calls": 0, "physical_state": "unlocked_awake_only",
              "actual_human_concurrent_use": "NOT_RUN_until_user_confirmation", "apps": {},
              "default_background_qualifications_changed": False}
    apps = report["apps"]
    try:
        trial = Trial(APPS["TextEdit"], {"window_title": "LocalPilot-AX-TextEdit.txt"}, apps)
        try:
            tree = trial.enumerate()
            text = next((n for n in tree.get("nodes", []) if n["role"] == "AXTextArea"), None)
            area = next((n for n in tree.get("nodes", []) if n["role"] == "AXScrollArea"), None)
            bars = [n for n in tree.get("nodes", []) if n["role"] == "AXScrollBar"]
            if area and bars:
                trial.action("scroll_down", {"role": "AXScrollArea", "identifier": area["identifier"]},
                    {"selector": {"identifier": bars[0]["identifier"]}, "attribute": "value", "not_equals": bars[0]["value"]}, tool="scroll", direction="down")
            if text:
                selector = {"role": "AXTextArea", "identifier": text["identifier"]}
                value = "LocalPilot real App AXValue test " + str(time.time_ns())
                trial.action("set_document_value", selector, exact(selector, "value", value), tool="set_value", value=value)
                trial.scope["include_menu_bar"] = True
                trial.action("menu_select_all", {"role": "AXMenuItem", "title": "全选"}, exact(selector, "selection_length", len(value)))
                # Only our disposable text document is edited; no save to user files.
                trial.scope["include_menu_bar"] = False
                trial.action("restore_disposable_text", selector, exact(selector, "value", text["value"]), tool="set_value", value=text["value"])
        finally:
            trial.finish()

        trial = Trial(APPS["Chrome"], {"window_title": "LocalPilot Real App AX - Google Chrome"}, apps)
        try:
            tree = trial.enumerate()
            selector = {"role": "AXTextField", "title": "LocalPilot test input"}
            trial.action("set_web_input", selector, exact(selector, "value", "LocalPilot Chrome AX"), tool="set_value", value="LocalPilot Chrome AX")
            live = trial.tree()
            live_input = next((n.get("value") for n in live.get("nodes", []) if n.get("title") == "LocalPilot test input" and n.get("role") == "AXTextField"), None)
            trial.action("press_web_button", {"role": "AXButton", "title": "Apply LocalPilot value"},
                {"selector": {"role": "AXStaticText", "value": "LocalPilot applied: " + str(live_input)}, "exists": True})
            trial.action("restore_web_input", selector, exact(selector, "value", "initial"), tool="set_value", value="initial")
            region = next((n for n in tree.get("nodes", []) if n.get("description") == "LocalPilot scroll region"), None)
            if region:
                trial.action("scroll_web_region", {"role": region["role"], "description": region["description"]},
                    {"selector": {"role": "AXStaticText", "value": "LocalPilot scroll start"}, "exists": False}, tool="scroll", direction="down")
        finally:
            trial.finish()

        trial = Trial(APPS["Safari"], {"window_title": "LocalPilot Real App AX"}, apps)
        try:
            tree = trial.enumerate()
            selector = {"identifier": "WEB_BROWSER_ADDRESS_AND_SEARCH_FIELD"}
            field = next((n for n in tree.get("nodes", []) if n.get("identifier") == selector["identifier"]), None)
            if field:
                value = "LocalPilot Safari address AX edit"
                trial.action("set_address_value_without_navigation", selector, exact(selector, "value", value), tool="set_value", value=value)
                trial.action("restore_address_value", selector, exact(selector, "value", field["value"]), tool="set_value", value=field["value"])
            sidebar = next((n for n in tree.get("nodes", []) if n.get("identifier") == "SidebarButton"), None)
            if sidebar:
                selector = {"identifier": "SidebarButton"}
                old = sidebar["description"]
                target = "隐藏边栏" if old == "显示边栏" else "显示边栏"
                trial.action("press_sidebar", selector, exact(selector, "description", target))
                trial.action("restore_sidebar", selector, exact(selector, "description", old))
        finally:
            trial.finish()

        trial = Trial(APPS["System Settings"], {}, apps)
        try:
            trial.enumerate()
            selector = {"role": "AXTextField"}
            trial.action("set_settings_search", selector, exact(selector, "value", "LocalPilot AX no match"), tool="set_value", value="LocalPilot AX no match")
            trial.action("clear_settings_search", selector, exact(selector, "value", ""), tool="set_value", value="")
            trial.action("press_general_navigation", {"identifier": "com.apple.settings.general"},
                {"selector": {"role": "AXButton", "description": "关于本机"}, "exists": True})
        finally:
            trial.finish()

        trial = Trial(APPS["Finder"], {"window_title": "LocalPilot"}, apps)
        try:
            trial.enumerate()
            trial.action("press_search_control", {"role": "AXButton", "description": "搜索"}, {"selector": {"role": "AXTextField"}, "exists": True})
            tree = trial.tree()
            fields = [n for n in tree.get("nodes", []) if n["role"] == "AXTextField"]
            if len(fields) == 1:
                selector = {"role": "AXTextField"}
                trial.action("set_finder_search_value", selector, exact(selector, "value", "LocalPilotAX-no-file"), tool="set_value", value="LocalPilotAX-no-file")
                trial.action("clear_finder_search", selector, exact(selector, "value", fields[0]["value"]), tool="set_value", value=fields[0]["value"])
            trial.action("show_view_menu", {"role": "AXPopUpButton", "description": "图标视图"},
                {"selector": {"role": "AXMenuItem", "title": "列表"}, "exists": True}, tool="invoke_action", action="AXShowMenu")
        finally:
            trial.finish()

        trial = Trial(APPS["WeChat"], {}, apps)
        try:
            trial.enumerate()
            trial.add("message_controls", "BLOCKED", reason="No uniquely scoped disposable chat; no sending or private chat interaction attempted.", category="coverage")
        finally:
            trial.finish()
    finally:
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)


if __name__ == "__main__":
    main()
