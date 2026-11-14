"""Local calendar-day projection of retained, currently authorized evidence."""
from datetime import datetime, timedelta
from pathlib import Path
import re
import time

from .presentation import APP_NAMES


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
            texts = list(dict.fromkeys(n["text"].strip() for n in proof.get("nodes", [])
                         if n.get("role") == "AXStaticText" and isinstance(n.get("text"), str) and n["text"].strip()))
            text = "；".join(texts)[:600] or "没有保留可读静态文字，无法概括正文。"
            label = (app or "应用") + " · " + (proof.get("window_title") or "标题未读取")
        elif row["source"] == "file_observer":
            label = "文件记录 · " + Path(row["source_reference"]).name
            text = row["summary"][:600]
        elif row["source"] == "localpilot":
            label = "LocalPilot 任务记录"
            text = row["summary"][:600]
        else:
            label = app or row["source"]
            text = row["summary"][:600]
        items.append({"id":row["id"], "timestamp":row["timestamp"],
                      "time":datetime.fromtimestamp(row["timestamp"]).strftime("%H:%M"),
                      "label":label, "text":text, "source":row["source"], "kind":kind,
                      "source_reference":row["source_reference"] or bundle,
                      "evidence_type":row["evidence_type"], "evidence_epistemic":row["evidence_epistemic"],
                      "read_status":proof.get("read_status", "NOT_APPLICABLE"),
                      "retained_occurrences":row["retained_occurrences"]})
    coverage = "仅含仍保留且目前获准读取的观察；窗口出现不证明实际编辑或任务完成，未读取的会议声音和隐藏内容不在记录中。"
    label = "今天" if day == "today" else "昨天"
    text = (label + "的已记录活动：\n\n" + "\n\n".join(
        f"{item['time']} · {item['label']}\n{item['text']}\n来源：{item['source']} / {item['id']}"
        for item in items)) if items else label + "没有仍可读取的活动记录，不能据此判断你没有工作。"
    if truncated:
        text += "\n\n这里只显示最近一部分记录。"
    return {"status":"ok", "date":start.date().isoformat(), "timezone":datetime.fromtimestamp(now).astimezone().tzname(),
            "text":text + "\n\n" + coverage, "items":items, "truncated":truncated, "coverage":coverage,
            "model":{"status":"not_called", "reason":"retained_observation_digest"}}
