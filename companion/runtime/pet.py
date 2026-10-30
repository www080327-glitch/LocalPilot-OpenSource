"""Pet presentation policy over the existing Companion; no executor or credentials."""
import re
from contextlib import contextmanager


def agent_profile(question):
    from companion.runtime.routing import needs_agent
    if re.search(r'多文件|多个文件|跨文件|重构|项目|部署|长程|多阶段|复杂|代码|refactor|project|deploy', question, re.I):
        return "standard" if needs_agent(question) or re.search(r'帮我|请|执行|修改', question) else None
    if needs_agent(question) or re.search(r'(帮我|请|替我).{0,25}(读取|查询|整理|列出|重命名|移动|文件夹|文件)', question):
        return "minimal"
    return None


def delegation(question, profile):
    return {"status":"delegation_required", "text":"这件事需要" + ("极简" if profile == "minimal" else "标准") + " Agent 使用工具。可以打开任务审核后继续。",
            "agent_profile":profile, "original_question":question, "model":{"status":"not_called"},
            "task_execution":"not_started", "cloud_transfer":"not_authorized"}


@contextmanager
def pet_scope(service, on_delta=None):
    # The service serializes commands on its owning thread. Restore all flags even
    # after a failed request; a pet question cannot change the normal agent route.
    auto = service.config.localpilot_auto_local
    prior = getattr(service, "pet_request", False)
    disabled = getattr(service.store, "conversation_disabled", False)
    callback = getattr(service.model, "on_delta", None)
    memory = service.store.get("pet_memory_enabled", True)
    service.config.localpilot_auto_local = False
    service.pet_request = True
    service.store.conversation_disabled = not memory
    service.model.on_delta = on_delta
    try:
        yield
    finally:
        service.config.localpilot_auto_local = auto
        service.pet_request = prior
        service.store.conversation_disabled = disabled
        service.model.on_delta = callback


def command(service, data):
    cmd = data["command"]
    if cmd == "pet_ask":
        text = data.get("text")
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
            raise ValueError("Question must contain 1..4000 characters")
        from companion.model.reliability import host_gate
        gate = host_gate(text)
        if gate and gate["reason"] == "permission_boundary":
            return gate | {"model":{"status":"not_called"}}
        profile = agent_profile(text)
        if profile:
            return delegation(text, profile)
        with pet_scope(service, data.get("_on_delta")):
            result = service.ask(text)
        return result
    if cmd == "pet_memory":
        if "enabled" in data:
            if type(data["enabled"]) is not bool:
                raise ValueError("Memory switch must be boolean")
            service.store.set("pet_memory_enabled", data["enabled"])
        return {"status":"ok", "enabled":service.store.get("pet_memory_enabled", True)}
    if cmd == "pet_export":
        return {"version":1, "memories":service.store.records(10000),
                "reminders":service.store.get("explicit_reminders", []),
                "memory_enabled":service.store.get("pet_memory_enabled", True),
                "scope":"Companion saved user data; no Core database or credentials"}
    raise ValueError("Unknown pet command")
