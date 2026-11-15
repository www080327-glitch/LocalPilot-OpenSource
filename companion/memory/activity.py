"""Local calendar-day projection of retained, currently authorized evidence."""
from datetime import datetime, timedelta
from pathlib import Path
import re
import time

from .presentation import APP_NAMES
from .observations import static_text_excerpt


def requested_activity_day(question):
    question = question.strip().rstrip("?？。!！")
    match = re.fullmatch(
        r"(?:请|帮我|你能)?(?:总结一下|总结|回顾一下|回顾)?(?:我)?(今天|昨天|今日|昨日)"
        r"(?:都)?(?:干了什么|做了什么|在做什么|忙什么|的工作|的活动|工作总结|活动总结)", question)
    if match:
        return "yesterday" if match[1] in {"昨天", "昨日"} else "today"
    return None


def activity_digest(memory, day="today", limit=30, now=None):
    if day not in {"today", "yesterday"} or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Activity day must be today/yesterday and limit must be 1..100")
    now = time.time() if now is None else now
    start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if day == "yesterday":
        start -= timedelta(days=1)
    until = min((start + timedelta(days=1)).timestamp(), now + .001)
    rows = memory.timeline(start.timestamp(), until, limit=limit + 1 if limit < 100 else limit, now=now)
    truncated = len(rows) > limit or len(rows) == 100
    items = []
    for row in reversed(rows[:limit]):
        obj, proof = row["object"], row["evidence"]
        bundle = obj.get("bundle_id", "")
        app = obj.get("app") or APP_NAMES.get(bundle, bundle)
        kind = row["kind"]
        if kind == "ax.snapshot":
            text = static_text_excerpt(proof) or "没有保留可读静态文字，无法概括正文。"
            label = (app or "应用") + " · " + (proof.get("window_title") or "标题未读取")
        elif row["source"] == "file_observer":
            label = "文件记录 · " + Path(row["source_reference"]).name
            text = row["summary"][:600]
        elif row["source"] == "localpilot":
            label = "LocalPilot 任务记录"
            text = row["summary"][:600]
        elif kind.startswith("imported."):
            label = obj.get("label", "导入记录") + " · " + obj.get("role", "来源文字")
            text = proof.get("text") or row["summary"][:600]
        else:
            label = app or row["source"]
            text = row["summary"][:600]
        items.append({"id":row["id"], "timestamp":row["timestamp"],
                      "time":datetime.fromtimestamp(row["timestamp"]).strftime("%H:%M"),
                      "label":label, "text":text, "source":row["source"], "kind":kind,
                      "source_reference":row["source_reference"] or bundle,
                      "evidence_type":row["evidence_type"], "evidence_epistemic":row["evidence_epistemic"],
                      "read_status":proof.get("read_status", "NOT_APPLICABLE"),
                      "timestamp_basis":proof.get("timestamp_basis", "observation_time"),
                      "retained_occurrences":row["retained_occurrences"]})
    coverage = "仅含仍保留且目前获准读取的观察；窗口出现不证明实际编辑或任务完成，未读取的会议声音和隐藏内容不在记录中。缺原始时间的导出按文件修改时间归档，不证明活动发生日期；自动语音转写可能误识别。"
    label = "今天" if day == "today" else "昨天"
    text = (label + "的已记录活动：\n\n" + "\n\n".join(
        f"{item['time']} · {item['label']}\n{item['text']}\n来源：{item['source']} / {item['id']}"
        for item in items)) if items else label + "没有仍可读取的活动记录，不能据此判断你没有工作。"
    if truncated:
        text += "\n\n这里只显示最近一部分记录。"
    return {"status":"ok", "date":start.date().isoformat(), "timezone":datetime.fromtimestamp(now).astimezone().tzname(),
            "text":text + "\n\n" + coverage, "items":items, "truncated":truncated, "coverage":coverage,
            "model":{"status":"not_called", "reason":"retained_observation_digest"}}


def requested_source_activity(question):
    lowered = question.casefold().strip().rstrip("?？。!！")
    kind = "codex" if "codex" in lowered else "meeting" if any(s in lowered for s in ("会议", "meeting", "会里", "开会", "开的会", "什么会", "哪些会", "哪个会")) else None
    overview = re.search(r"(?:说(?:了)?什么|讨论了什么|做了什么|干了什么|干什么|有什么记录|活动记录|工作记录|对话记录)$", lowered)
    summary = re.fullmatch(r"(?:请|帮我)?(?:总结|回顾)(?:一下)?(?:我)?(?:今天|昨天|最近)?(?:的)?(?:codex|会议|meeting)(?:里|中|的)?(?:记录|内容|工作|对话)?", lowered)
    return kind if kind and (overview or summary) else None


def source_activity_answer(memory, question, kind, now=None):
    now = time.time() if now is None else now
    day = "yesterday" if any(s in question for s in ("昨天", "昨日")) else "today" if any(s in question for s in ("今天", "今日")) else None
    start = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if day == "yesterday": start -= timedelta(days=1)
    since, until = (start.timestamp(), (start+timedelta(days=1)).timestamp()) if day else (0, now+.001)
    rows = (memory.timeline(since, until, limit=100, now=now, kind="imported."+kind) if day
            else memory.records(limit=500, kind="imported."+kind, now=now))
    native = (memory.timeline(since, until, limit=100, now=now, kind="ax.snapshot") if day
              else memory.records(limit=200, kind="ax.snapshot", now=now))
    truncated = len(rows) >= (100 if day else 500) or len(native) >= (100 if day else 200)
    for row in native:
        app = row["object"].get("bundle_id", "").casefold()
        if (kind == "codex" and "codex" in app or kind == "meeting" and any(word in app for word in ("zoom", "meeting", "teams"))):
            rows.append(row)
    rows = sorted((row for row in rows if since <= row["timestamp"] < until), key=lambda row: row["timestamp"], reverse=True)
    items = []
    for row in rows[:6]:
        proof, obj = row["evidence"], row["object"]
        text = static_text_excerpt(proof) if row["kind"] == "ax.snapshot" else proof.get("text") or row["summary"]
        if not text: continue
        items.append({"id":row["id"], "timestamp":row["timestamp"], "text":text,
            "label":obj.get("label") or obj.get("app") or obj.get("bundle_id", ""),
            "role":obj.get("role", "窗口可读文字"), "source_reference":row["source_reference"],
            "source_path":obj.get("source_path", ""), "locator":proof.get("locator", ""),
            "timestamp_basis":proof.get("timestamp_basis", "observation_time"),
            "evidence_type":row["evidence_type"], "read_status":proof.get("read_status", "UNKNOWN"),
            "raw_state":row["raw_state"]})
    scope = "这些是已授权来源中实际保留的文字，证明记录里包含什么，不独立证明用户做过什么或任务完成；缺原始时间的导出按文件修改时间归档，不证明活动发生日期。自动语音转写可能误识别、重复或遗漏，不验证说话者身份。"
    text = "相关记录的可核对摘录：\n\n" + "\n\n".join(
        f"{item['label']} · {item['role']}\n{item['text']}\n来源：{item['id']} / {item['locator']}" for item in items) if items else "当前范围没有可读取的相关记录；不能据此判断没有开展工作或会议。"
    return {"status":"ok", "text":text+"\n\n"+scope, "items":items, "coverage":scope,
            "truncated":truncated or len(rows)>6, "model":{"status":"not_called", "reason":"source_activity_excerpt"}}
