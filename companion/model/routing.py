"""Local-first inference tiers. Planning cannot submit tasks or transmit context.

L0 gates evidence/permission; L1 handles simple text; explicitly configured L2
handles harder text. L3 only produces a confirmation requirement for the existing
LocalPilot Adapter. No event or failed generation silently grants task authority.
"""
from dataclasses import asdict, dataclass
import re

from companion.model.reliability import augment_messages, guard_result, host_gate
from companion.model.structured import parse
from companion.runtime.routing import refers_to_conversation, execution_status_question

TOOL_REQUEST = re.compile(r"(?:帮我|替我|请(?:你)?|直接|执行|运行|开始|取消|帮忙).{0,35}"
                          r"(?:修改|删除|部署|安装|写(?:入|代码)|重构|发(?:送)?邮件|操作(?:电脑|GUI)|"
                          r"运行命令|点击|输入|拖拽|打开浏览器)|"
                          r"(?:执行|运行)(?:这个|该|以下)?(?:命令|脚本|shell)|"
                          r"computer use|(?:click|drag|type into|delete file|edit file|deploy|send email)", re.I)
DEEP_REQUEST = re.compile(r"深入(?:分析|理解|研究)|详细(?:分析|评估)|多(?:份|个)?(?:文档|文件|事件)|"
                          r"跨(?:文档|文件)|综合(?:分析|核对|比较)|复杂(?:上下文|问题|推理)|"
                          r"风险评估|预算优化|in.depth|deep analysis|cross.document|multiple documents", re.I)
SYNTHESIS = re.compile(r"分析|综合|比较|对照|核对|冲突|compare|analy|synthesi", re.I)


@dataclass(frozen=True)
class RoutePlan:
    level: int
    reason: str
    requested_level: int
    requires_confirmation: bool = False
    degraded: bool = False
    cloud_transfer: str = "not_authorized_by_routing"

    def to_dict(self):
        return asdict(self)


class TieredInference:
    def __init__(self, primary, secondary=None, config=None):
        self.primary, self.secondary, self.config = primary, secondary, config
        self.last_plan = None
        self.counts = {"l0": 0, "l1": 0, "l2": 0, "l3_prepared": 0, "degraded": 0}

    def secondary_available(self):
        return self.secondary is not None and self.secondary.available()

    def plan(self, question, memories=(), observations=(), *, force_deep=False,
             requires_agent=False, low_confidence=False, evidence_conflict=False,
             background=False, permission_denied=False):
        gate = host_gate(question, memories, observations, permission_denied=permission_denied)
        if gate:
            return RoutePlan(0, gate["reason"], 0)
        # Background observations never wake a strong model or prepare a task.
        # Event text is data. A later explicit user request gets its own plan.
        if background:
            return RoutePlan(1, "background_bounded_local", 1)
        explanation_only = bool(re.search(r"^(?:请|能否|你能)?(?:解释|说明|介绍|讲讲)", question)) and not re.search(
            r"(?:并|然后|同时|再).{0,15}(?:修改|删除|执行|运行|点击|输入|部署)", question)
        if requires_agent or (TOOL_REQUEST.search(question) and not execution_status_question(question) and not explanation_only):
            return RoutePlan(3, "explicit_tool_or_agent_request", 3, requires_confirmation=True)
        sources = {str(row.get("source_reference") or row.get("id") or "")
                   for row in memories if row.get("type") in {"document", "summary"}}
        multi_source = len(sources - {""}) > 1 and SYNTHESIS.search(question)
        roles = {row.get("metadata", {}).get("role", row.get("role", "unknown"))
                 for row in memories if row.get("type") == "conversation"}
        role_sensitive = refers_to_conversation(question) and {"user", "assistant"} <= roles
        if force_deep or evidence_conflict or low_confidence or DEEP_REQUEST.search(question) or multi_source or role_sensitive:
            reason = ("user_requested_deep" if force_deep or DEEP_REQUEST.search(question) else
                      "evidence_conflict" if evidence_conflict else "low_confidence" if low_confidence else
                      "role_sensitive_history" if role_sensitive else "multi_source_synthesis")
            if self.config is not None:
                return RoutePlan(2, reason, 2, requires_confirmation=True,
                                 degraded=not (getattr(self.config, "localpilot_analysis_route", "") and getattr(self.config,"localpilot_endpoint","")))
            return RoutePlan(2 if self.secondary_available() else 1, reason, 2,
                             degraded=not self.secondary_available())
        return RoutePlan(1, "simple_local_text", 1)

    def complete(self, messages, *, question="", memories=(), observations=(), max_tokens=None,
                 schema=None, force_deep=False, requires_agent=False, low_confidence=False,
                 evidence_conflict=False, background=False, permission_denied=False, cancelled=None):
        plan = self.plan(question, memories, observations, force_deep=force_deep,
                         requires_agent=requires_agent, low_confidence=low_confidence,
                         evidence_conflict=evidence_conflict, background=background,
                         permission_denied=permission_denied)
        self.last_plan = plan
        attempts = []
        if plan.level == 0:
            gate = host_gate(question, memories, observations, permission_denied=permission_denied)
            self.counts["l0"] += 1
            return {"status": gate["status"], "text": gate["text"], "routing": plan.to_dict(),
                    "reliability": {"status": "HOST_CONTROL", "reason": gate["reason"]}, "attempts": [],
                    "model_called": False}
        if plan.level == 3 or plan.level == 2 and plan.requires_confirmation:
            self.counts["l3_prepared"] += 1
            return {"status": "needs_confirmation", "text": "NEEDS_AGENT", "routing": plan.to_dict(),
                    "attempts": [], "model_called": False}
        if cancelled is not None and cancelled():
            return {"status": "unavailable", "text": "观察已暂停，本次推理已取消。", "routing": plan.to_dict(),
                    "reliability": {"status": "HOST_CONTROL", "reason": "model_cancelled"},
                    "attempts": [], "model_called": False}
        prompt = augment_messages(messages, memories, observations)
        result, audit = self._call(plan.level, prompt, max_tokens, schema, memories, observations, attempts)
        if cancelled is not None and cancelled():
            return {"status": "unavailable", "text": "观察已暂停，本次推理已取消。", "routing": plan.to_dict(),
                    "reliability": {"status": "HOST_CONTROL", "reason": "model_cancelled"},
                    "attempts": attempts, "model_called": any(a["result"].get("model_called",True) is not False for a in attempts)}
        # Only one real stronger retry, and only on concrete host/model failure.
        # A generated confidence claim by itself is never a calibrated signal.
        bad = (result.get("status") in {"unavailable", "truncated", "unverified"} or
               schema is not None and parse(result, schema) is None)
        if plan.level == 1 and bad and not background and self.secondary_available():
            plan = RoutePlan(2, "host_quality_gate", 2)
            self.last_plan = plan
            result, audit = self._call(2, prompt, max_tokens, schema, memories, observations, attempts)
            if cancelled is not None and cancelled():
                return {"status": "unavailable", "text": "观察已暂停，本次推理已取消。", "routing": plan.to_dict(),
                        "reliability": {"status": "HOST_CONTROL", "reason": "model_cancelled"},
                        "attempts": attempts, "model_called": any(a["result"].get("model_called",True) is not False for a in attempts)}
        if plan.degraded:
            self.counts["degraded"] += 1
        return result | {"routing": plan.to_dict(), "reliability": audit,
                         "attempts": attempts, "model_called": any(a["result"].get("model_called",True) is not False for a in attempts)}

    def _call(self, level, messages, max_tokens, schema, memories, observations, attempts):
        model = self.secondary if level == 2 else self.primary
        kwargs = {"max_tokens": max_tokens}
        if schema is not None:
            kwargs["schema"] = schema
        raw = model.complete(messages, **kwargs)
        self.counts["l" + str(level)] += 1
        result, audit = guard_result(raw, memories, observations, schema=schema)
        attempts.append({"level": level, "result": raw, "reliability": audit})
        return result, audit

    def tick(self):
        self.primary.tick()
        if self.secondary is not None:
            self.secondary.tick()

    def unload(self):
        self.primary.unload()
        if self.secondary is not None:
            self.secondary.unload()

    def request_stop(self):
        self.primary.request_stop()
        if self.secondary is not None:
            self.secondary.request_stop()

    def stats(self):
        return {"counts": dict(self.counts), "last_plan": self.last_plan.to_dict() if self.last_plan else None,
                "primary": self.primary.stats(), "secondary": self.secondary.stats() if self.secondary else None}
