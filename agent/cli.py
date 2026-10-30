"""Text frontend: commands and event rendering, no agent decisions."""
import json
import shlex

from .session import SessionState

HELP = """输入任务开始/继续对话；每次回答结束后会保留上下文。
/help  /exit  /quit  /settings  /model  /backend
/policy local-only|local-first|balanced|cloud-first|cloud-only
/thinking [value]  显示当前模型支持的档位，或原样切换
/reasoning hidden|summary|full
/permissions approve-all|approve-mutations|local-judge-conservative|local-judge-permissive|full-permission
/plan on|off  /plan revise 修改意见
/approve  /reject [理由]
/goals  /goals add 描述  /goals update ID 状态 [描述]  /goals cancel ID
/computer status  /computer takeover（我来操作）  /computer done（✓ 操作完成）
审批期间请先批准、拒绝或修改计划，再调整设置。
Gateway 是应用层权限检查，不是 OS sandbox。"""


class EventRenderer:
    def __init__(self, output=print):
        self.output = output
        self.has_text = False
        self.has_reasoning = False

    def reset(self):
        self.has_text = False
        self.has_reasoning = False

    def __call__(self, event):
        data = event.data
        if event.type == "ModelResponseStarted":
            if self.has_text or self.has_reasoning:
                self.output("")
            self.reset()
        elif event.type == "TextDelta":
            if not self.has_text:
                if self.has_reasoning:
                    self.output("")
                    self.has_reasoning = False
                self.output("Assistant > ", end="", flush=True)
                self.has_text = True
            self.output(data["text"], end="", flush=True)
        elif event.type == "ReasoningDelta":
            if not self.has_reasoning:
                if self.has_text:
                    self.output("")
                    self.has_text = False
                self.output("Reasoning > ", end="", flush=True)
                self.has_reasoning = True
            self.output(data["text"], end="", flush=True)
        elif event.type == "ReasoningSummary":
            self.output(f"\n推理流已接收（{data['characters']} 字符）；用 /reasoning full 查看后续完整流。")
        elif event.type in {"TurnFinished", "ApprovalRequired"}:
            if self.has_text or self.has_reasoning:
                self.output("")
            if event.type == "ApprovalRequired":
                self.output("\n需要批准（/approve 或 /reject）：" + json.dumps(data, ensure_ascii=False, indent=2))
        elif event.type == "BackendFallback":
            self.output("\n后端转移：" + data["reason"] + " → " + data.get("target", "cloud"))
            self.output("云端将收到的数据类别：" + ", ".join(data.get("data_categories", [])))
        elif event.type == "ModelRetry":
            self.output(f"\n请求暂时失败，{data['delay']:.2f} 秒后重试。")
        elif event.type == "ModelSwitched":
            self.output("\n主模型已切换为：" + data["primary"])
        elif event.type == "ContextCompacted":
            self.output("\n上下文已为本次请求压缩；完整会话和操作回执仍保留在内存中。")
        elif event.type == "ErrorEvent":
            self.output("\nAgent 错误：" + data["message"])
        elif event.type == "ComputerHumanTakeover":
            self.output("\n电脑操作已完全暂停，你可以手动操作；完成后输入 /computer done。")
        elif event.type == "ComputerInterferenceDetected":
            self.output("\n检测到前台焦点或鼠标变化，电脑操作已暂停。")
        elif event.type == "ComputerLockChanged":
            self.output("\n锁屏状态变化，恢复前需要重新读取界面。")
        elif event.type == "SubagentStarted":
            label = data.get("role", data.get("backend", "worker"))
            if data.get("tier"):
                label += f" {data['tier']} ({data.get('provider', 'unknown')}:{data.get('model', 'unknown')})"
            self.output("\n子代理开始：" + label)
        elif event.type in {"SubagentCompleted", "SubagentFailed"} and data.get("id"):
            models = ", ".join(data.get("reported_models", [])) or "未报告"
            self.output(f"\n子代理结果：{data['status']}；API 回报模型：{models}")
        elif event.type == "SubagentEvent":
            child = data["event"]
            if child["type"] == "TextDelta":
                self.output(f"[Worker {data['id']}] " + child["data"]["text"], end="", flush=True)

    def finish(self, result):
        if not self.has_text and result.status not in {"approval_required", "error"}:
            self.output("Assistant > " + result.text)
        if result.status != "approval_required":
            labels = {"passed": "通过（宿主独立检查）", "failed": "未通过", "unverified": "未验证", "incomplete": "交付未完成"}
            self.output("\n工程状态：" + labels.get(result.engineering_status, "未验证"))


def command(session, line):
    """Return an AgentResult only for actions which resume a pending turn."""
    parts = shlex.split(line)
    name = parts[0]
    values = parts[1:]
    if name.startswith("/thinking/"):
        values = [name[len("/thinking/"):]]
        name = "/thinking"
    if name in {"/exit", "/quit"}:
        session.close()
        return "会话已结束。"
    if name == "/help":
        return HELP
    if name == "/computer":
        if not session.computer:
            raise ValueError("Computer Use 未开启；启动时指定 --computer-app bundle.ID")
        if values == ["takeover"]:
            return json.dumps(session.take_over_computer(), ensure_ascii=False)
        if values == ["done"]:
            result = session.resume_computer()
            return json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else result
        if values in ([], ["status"]):
            return json.dumps(session.computer.summary(), ensure_ascii=False, indent=2)
        raise ValueError("使用 /computer status、takeover 或 done")
    if name in {"/settings", "/model"}:
        return json.dumps(session.settings(), ensure_ascii=False, indent=2)
    if name == "/backend":
        backend = session.current_backend
        profile = getattr(backend, "profile", None)
        return json.dumps({"primary": session.primary, "backend": type(backend).__name__,
            "model": session.current_primary_model,
            "profile": profile.snapshot() if profile else None,
            "note": "Offline snapshot; verification is historical, not a current health check."}, ensure_ascii=False, indent=2)
    if name == "/thinking" and not values:
        settings = session.settings()
        return json.dumps({key: settings[key] for key in ("model", "thinking", "supported_thinking_efforts", "default_thinking_effort")}, ensure_ascii=False, indent=2)
    if name in {"/policy", "/thinking", "/permissions", "/reasoning"}:
        if not values:
            return json.dumps(session.settings(), ensure_ascii=False, indent=2)
        if len(values) != 1:
            raise ValueError("此命令只接受一个设置值")
        method = {"/policy": session.set_policy, "/thinking": session.set_thinking,
                  "/reasoning": session.set_reasoning,
                  "/permissions": session.set_permissions}[name]
        method(values[0])
        return "设置已更新。"
    if name == "/plan":
        if not values:
            return json.dumps({"enabled": session.plan_mode, "plan": session.active_plan}, ensure_ascii=False)
        if values[0] == "revise":
            return session.revise_plan(" ".join(values[1:]))
        if values not in (["on"], ["off"]):
            raise ValueError("使用 /plan on、/plan off 或 /plan revise 修改意见")
        session.set_plan_mode(values[0] == "on")
        return "计划模式已更新。"
    if name == "/approve":
        return session.approve()
    if name == "/reject":
        return session.reject(" ".join(values) or "User rejected the request.")
    if name == "/goals":
        if not values:
            return json.dumps(session._goal_records(), ensure_ascii=False, indent=2)
        if values[0] == "add":
            result = session._manage_goal({"action": "create", "description": " ".join(values[1:])})
        elif values[0] == "cancel" and len(values) == 2:
            result = session._manage_goal({"action": "cancel", "id": values[1]})
        elif values[0] == "update" and len(values) >= 3:
            args = {"action": "update", "id": values[1], "status": values[2]}
            if len(values) > 3:
                args["description"] = " ".join(values[3:])
            result = session._manage_goal(args)
        else:
            raise ValueError("使用 /goals add、update 或 cancel；/help 查看参数")
        return json.dumps(result, ensure_ascii=False)
    raise ValueError("未知命令，输入 /help 查看帮助")


def interactive(session, renderer, *, input_fn=None, on_result=None):
    input_fn = input_fn or input
    print("LocalPilot V2 Computer Use Alpha（Agent Runtime V1.4）；输入 /help 查看命令。" if session.computer else "LocalPilot Agent Runtime V1.4；输入 /help 查看命令。")
    print("云端模式会发送对话和获准读取的文件片段；local-first 失败可转云端。")
    while session.state != SessionState.SESSION_FINISHED:
        try:
            for goal_line in session.active_goal_lines():
                print(goal_line)
            line = input_fn("LocalPilot > ").strip()
        except (EOFError, KeyboardInterrupt):
            session.close()
            print("\n会话已结束。")
            break
        if not line:
            continue
        renderer.reset()
        try:
            if line.startswith("/"):
                result = command(session, line)
            elif session.pending_approval:
                if line.lower() == "approve":
                    result = session.approve()
                elif line.lower() == "reject":
                    result = session.reject()
                elif session.state == SessionState.PLAN_AWAITING_APPROVAL:
                    result = session.revise_plan(line)
                else:
                    raise ValueError("当前等待批准，请使用 /approve 或 /reject")
            else:
                result = session.run_turn(line)
            if isinstance(result, str):
                print(result)
            else:
                renderer.finish(result)
                if on_result:
                    on_result(result)
        except (ValueError, KeyError, OSError, RuntimeError) as error:
            print("提示：" + str(error))
    return 0
