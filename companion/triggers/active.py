"""Evidence-driven candidates. An event is host data, never a document instruction."""
from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True)
class Candidate:
    kind: str
    project: str
    evidence: dict
    host_action: str = "quiet"
    reason: str = ""


def candidate(event, sustained_minutes=45):
    if not isinstance(event, dict):
        return None
    if any(event.get(k) for k in ("dnd", "busy", "presentation", "initial_index")):
        return None
    if event.get("content_changed") is False or event.get("kind") in {"save", "browse", "batch", "unimportant"}:
        return None
    if event.get("hour", 12) < 8 or event.get("hour", 12) >= 22:
        if not event.get("user_requested_help"):
            return None
    project = str(event.get("project", "当前项目"))[:80]
    if event.get("kind") == "context_review" and event.get("content_evidence") is True and event.get("context_count",0) >= 1:
        return Candidate("context_review", project, event, "ask-help", "observed_window_text_review_offer")
    if event.get("user_requested_help"):
        action = "escalate" if event.get("requires_code_change") or event.get("requires_file_change") else "ask-help"
        return Candidate("requested_help", project, event, action, "explicit_user_request")
    if (event.get("explicit_reminder_opt_in") and
        (event.get("deadline_today") or 0 <= event.get("deadline_in_minutes", -1) <= 30)):
        return Candidate("deadline", project, event, "notify", "subscribed_deadline")
    if event.get("same_error") and event.get("errors", 0) >= 3:
        return Candidate("repeated_error", project, event, "ask-help", "repeated_error_text_cause_unknown")
    if event.get("kind") == "long_work" and event.get("minutes", 0) >= 90:
        action = "notify" if event.get("break_reminder_opt_in") else "quiet"
        return Candidate("long_work", project, event, action, "sustained_work")
    if event.get("kind") in {"edits", "modified"} and (
            event.get("minutes", 0) >= sustained_minutes and event.get("count", 0) >= 3 or
            event.get("same_document") and event.get("count", 0) >= 5):
        return Candidate("document_revisions" if event.get("same_document") else "project_help",
                         project, event, "quiet", "editing_needs_semantic_evidence")
    # Compatibility with trusted legacy aggregated events with unknown paths.
    if event.get("legacy_repeated"):
        return Candidate("repeated_events", project, event)
    return None


def messages(event, item=None):
    data = asdict(item) if item else {"evidence": event}
    return [{"role": "system", "content":
        "你只判断提醒是否有帮助。事件是宿主提供的数据。quiet=沉默，notify=温和提醒，"
        "ask-help=询问是否需要帮助，escalate=准备升级请求。重复同类阻塞值得询问；"
        "订阅的临期提醒值得通知。普通编辑、批量变化、忙碌、深夜、没有明确帮助价值则沉默。"
        "不要从保存次数猜测错误或疲劳。只输出JSON：action和confidence(0到1)，不要解释。"},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False, sort_keys=True)}]


def verify(item, decision, threshold=.9):
    if item is None:
        return {"action": "quiet", "origin": "filter_or_invalid"}
    if item.host_action != "quiet":
        # Explicit opt-in and repeated host error evidence are authoritative.
        # Report this as host success even if the model agrees.
        return {"action": item.host_action, "origin": "host_evidence", "reason": item.reason}
    if decision is None:
        return {"action": "quiet", "origin": "filter_or_invalid"}
    if decision["confidence"] < threshold or decision["action"] == "quiet":
        return {"action": "quiet", "origin": "model"}
    evidence = item.evidence
    if not (evidence.get("help_value") or evidence.get("blocker") or evidence.get("legacy_repeated")):
        return {"action": "quiet", "origin": "insufficient_help_evidence"}
    # Background model alone never grants escalation authority.
    action = "ask-help" if decision["action"] in {"ask-help", "escalate"} else "notify"
    return {"action": action, "origin": "model_and_verifier"}


def notice_text(item, action):
    if item.kind == "context_review":
        return "这段时间已读到窗口中的可访问文字。点开「整理窗口要点」，我可以提炼内容、列出明确提到的待办。未读取的部分仍不确定。"
    if item.kind == "deadline":
        return f"{item.project} 有你订阅的临期事项，要查看来源吗？"
    if item.kind == "repeated_error":
        return f"{item.project} 多次显示相同错误文字，需要我帮你查看上下文吗？"
    if item.kind == "long_work":
        return "你订阅的持续工作提醒到了。需要休息一下吗？"
    return f"你一直在处理 {item.project}，需要我帮忙吗？"
