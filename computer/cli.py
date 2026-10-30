"""Small semantic console using the existing ToolRegistry and PermissionGateway."""
import argparse
import json
from pathlib import Path

from agent.registry import create_default_registry
from .build import FIXTURE_ID
from .local_native import configured_computer_backend
from .runtime import ComputerRuntime


def normalize_input(line):
    """Remove only known outer terminal paste wrappers, never JSON contents."""
    line = line.strip()
    if line.startswith("\x1b[200~"):
        line = line[len("\x1b[200~"):]
    if line.endswith("\x1b[201~"):
        line = line[:-len("\x1b[201~")]
    return line.strip()


def control(runtime, registry, line, pending):
    """Host input only. A model cannot call these takeover/approval commands."""
    line = normalize_input(line)
    if line == "/takeover":
        pending.clear()  # Human change invalidates any earlier pending write.
        return runtime.take_over()
    if line == "/done":
        pending.clear()
        return runtime.resume()
    if line == "/status":
        return runtime.summary()
    if line == "/reject":
        pending.clear()
        return {"status": "rejected"}
    if line == "/approve":
        if not pending:
            raise ValueError("No pending action")
        name, args = pending.pop("call")
        return registry.call(name, args, approved=True)
    if line.startswith("/"):
        raise ValueError("控制命令必须单独输入一条，例如 /takeover。先按 Ctrl+U 清空当前行，再手动输入并回车；不要附带 Computer > 或其他命令。")
    name, _, raw = line.partition(" ")
    # Unknown or corrupted control input must not be reported as a JSON error.
    registry.metadata(name)
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError:
        raise ValueError(f"{name} 的参数需要完整 JSON；控制命令 /takeover、/done 不需要参数。请清空输入行后重新输入一条命令。") from None
    result = registry.call(name, args)
    if result.get("status") == "approval_required":
        pending["call"] = (name, args)
    return result


def render_result(result, *, raw_json=False):
    """Human status by default; full machine output is an explicit debug option."""
    if raw_json:
        return json.dumps(result, ensure_ascii=False, indent=2)
    if result.get("status") == "ok" and result.get("state") == "human_controlling" and result.get("quiescent") is True:
        return "电脑操作已暂停，已交给你操作。\n手动操作完成后，回这里输入 /done。"
    if result.get("status") == "ok" and result.get("state") == "agent_controlling" and "changes" in result:
        changes = result["changes"]
        changed = any(item.get("changed") is True for item in changes)
        unknown = any(item.get("changed") is None for item in changes)
        label = "检测到界面变化" if changed else "缺少之前的状态，变化尚不能确认" if unknown else "没有检测到界面变化"
        return "已重新读取界面并恢复控制；" + label + "。"
    if result.get("status") == "ok" and "nodes" in result:
        title = result.get("window_title") or next((n.get("title") for n in result["nodes"] if n.get("role") == "AXWindow"), result.get("app"))
        label = json.dumps(str(title)[:100], ensure_ascii=False)
        coverage = "（输出有省略）" if result.get("truncated") else ""
        return f"已读取窗口 {label}：{result.get('native_node_count', len(result['nodes']))} 项控件{coverage}。\n接管测试下一步：单独输入 /takeover，然后按回车。"
    if result.get("status") == "error":
        messages = {
            "app_closed_or_pid_unavailable": "暂时无法找到目标 App。请先打开测试文档，再重新读取窗口。",
            "window_not_found": "指定测试窗口暂未出现在无障碍树中。请确认文档仍打开，再重新读取；不会猜另一个窗口或抢焦点。",
            "accessibility_not_trusted": "当前启动环境没有 AX 读取权限，请把这条提示告诉我，先停止测试。",
            "locked_or_unknown": "电脑仍锁定或状态尚不能确认。请手动解锁后再继续。",
            "interference": "检测到前台或鼠标位置变化，运行已暂停；变化来源尚不能确定。写操作可能已生效，不会自动重试。确认环境后用 /done 重新读取状态。",
        }
        if result.get("error") in messages:
            return messages[result["error"]]
    return json.dumps(result, ensure_ascii=False, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--app", action="append", help="Explicit allowed bundle ID; repeat for more apps")
    parser.add_argument("--audit", help="Optional local JSONL audit path (contains UI state)")
    parser.add_argument("--json", action="store_true", help="Show full JSON instead of concise human-readable status")
    parser.add_argument("--qualified-background-app", action="append", help="Host opt-in only after controlled per-app AX background qualification; otherwise unknown apps are observation-only")
    parser.add_argument("--experimental-native-targets", help="Host qualification JSON; explicitly opts in to scoped native keyboard")
    args = parser.parse_args(argv)
    allowed = args.app or [FIXTURE_ID]
    if args.qualified_background_app and not set(args.qualified_background_app) <= set(allowed):
        parser.error("Background qualification must be within --app scope")
    registry = create_default_registry(args.workspace, permission_mode="approve-mutations")
    audit = Path(args.audit).open("a", encoding="utf-8") if args.audit else None
    def event(name, **data):
        if audit:
            audit.write(json.dumps({"type": name, "data": data}, ensure_ascii=False) + "\n")
            audit.flush()
    runtime = ComputerRuntime(configured_computer_backend(allowed, args.experimental_native_targets), allowed_apps=allowed, event_callback=event,
        background_safe_apps=args.qualified_background_app)
    runtime.register_tools(registry)
    pending = {}
    print("LocalPilot Computer Use V2 Alpha · " + runtime.backend.name)
    print("我来操作：/takeover   ✓ 操作完成：/done   状态：/status")
    print("写操作先预览，再 /approve 或 /reject。输入 /help 查看示例，/exit 退出。")
    try:
        while True:
            try:
                line = ""
                line = normalize_input(input("Computer > "))
                if line == "/exit":
                    break
                if line == "/help":
                    print('inspect_tree {"app":"' + allowed[0] + '"}')
                    print('find_element {"app":"' + allowed[0] + '","selector":{"identifier":"lp.fixture.input"}}')
                    print('set_value {"app":"' + allowed[0] + '","element":"<返回的 element>","observation":"<返回的 observation>","value":"hello","postcondition":{"selector":{"identifier":"lp.fixture.input"},"attribute":"value","equals":"hello"}}')
                    continue
                if line:
                    print(render_result(control(runtime, registry, line, pending), raw_json=args.json))
            except (ValueError, KeyError, RuntimeError, OSError) as exc:
                event("ComputerInputRejected", error_type=type(exc).__name__,
                      category="control_input" if line.startswith("/") else "tool_input_or_dispatch")
                print("提示：" + str(exc))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        runtime.close()
        if audit:
            audit.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
