"""Explicit conversation/transcript exports, never model reasoning or tool payloads."""
from datetime import datetime
import json
import math
import re

from .events import bounded_text, redact_text

EXTENSIONS = {"codex": {".jsonl", ".json"}, "meeting": {".txt", ".md", ".vtt", ".srt", ".jsonl"}}
_PRIVATE_MESSAGE = re.compile(r"<(?:think|analysis|environment_context|permissions|turn_aborted)\b", re.I)
_CUE = re.compile(r"(\d+:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}\.\d{3})")


def parse_source(kind, content, suffix, fallback_timestamp):
    text = content.decode("utf-8-sig")
    if kind == "codex":
        return _codex(text, suffix, fallback_timestamp)
    return _meeting(text, suffix, fallback_timestamp)


def _timestamp(value, fallback):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            value = None
    if type(value) in {float, int} and math.isfinite(value) and value >= 0:
        return float(value), "source_timestamp"
    return fallback, "file_modified_time_not_source_event_time"


def _chunks(text, locator, **metadata):
    text = redact_text(text).strip()
    for index in range(0, len(text), 900):
        yield {"text": bounded_text(text[index:index+900], 3600),
               "locator": locator + (f" / part {index//900+1}" if len(text) > 900 else ""), **metadata}


def _codex(text, suffix, fallback):
    if suffix == ".jsonl":
        rows = [(number, json.loads(line)) for number, line in enumerate(text.splitlines(), 1) if line.strip()]
    else:
        value = json.loads(text)
        messages = value.get("messages") if isinstance(value, dict) else value
        if not isinstance(messages, list):
            raise ValueError("Conversation JSON requires a messages array")
        rows = list(enumerate(messages, 1))
    if any(not isinstance(row, dict) for _, row in rows):
        raise ValueError("Conversation export must contain message objects")
    # CLI rollouts may contain both visible events and response protocol copies.
    # Prefer the visible event stream to avoid recording the same utterance twice.
    visible_events = any(row.get("type") == "event_msg" and isinstance(row.get("payload"), dict)
                         and row["payload"].get("type") in {"user_message", "agent_message"} for _, row in rows)
    records, skipped = [], 0
    for number, row in rows:
        message = row.get("payload", row)
        if not isinstance(message, dict):
            skipped += 1
            continue
        if visible_events:
            role = {"user_message": "user", "agent_message": "assistant"}.get(message.get("type"))
            body = message.get("message")
            allowed = row.get("type") == "event_msg" and role is not None
        else:
            role, body = message.get("role"), message.get("content")
            allowed = (role in {"user", "assistant"} and row.get("type") in {None, "response_item", "message"}
                       and message.get("type") in {None, "message"})
            if isinstance(body, list):
                body = "\n".join(part["text"] for part in body if isinstance(part, dict)
                                 and part.get("type") in {"text", "input_text", "output_text"}
                                 and isinstance(part.get("text"), str))
        if (not allowed or message.get("channel", row.get("channel")) in {"analysis", "reasoning"}
                or not isinstance(body, str) or not body.strip() or _PRIVATE_MESSAGE.search(body)):
            skipped += 1
            continue
        timestamp, basis = _timestamp(row.get("timestamp", message.get("timestamp")), fallback)
        records.extend(_chunks(body, f"record {number}", role=role, timestamp=timestamp,
                               timestamp_basis=basis, epistemic="reported" if role == "assistant" else "source_record"))
    return records, {"skipped_records": skipped, "format": "visible_codex_messages",
                     "coverage": "仅包含所选导出中的用户与助手可见文字；不含隐藏推理、系统环境、工具参数或执行收据。"}


def _meeting(text, suffix, fallback):
    records, skipped = [], 0
    if suffix == ".jsonl":
        from .meeting import parse_message
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            row = parse_message((line + "\n").encode())
            if row["type"] != "transcript":
                skipped += 1
                continue
            records.extend(_chunks(row["text"], f"segment {row['segment']} / record {number}",
                role="automatic_transcript:"+row["source"], timestamp=row["ended_at"], timestamp_basis="automatic_transcription_time",
                capture_source=row["source"], started_at=row["started_at"], ended_at=row["ended_at"],
                epistemic="reported", automatic_transcription=True))
        return records, {"skipped_records":skipped, "format":"automatic_on_device_transcript",
                         "coverage":"所选麦克风/系统音轨的自动转写，可能误识别、重复或遗漏；说话者身份与事实未经验证；不含原始音视频。"}
    if suffix in {".vtt", ".srt"}:
        blocks, block = [], []
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                block.append((number, line))
            elif block:
                blocks.append(block)
                block = []
        if block:
            blocks.append(block)
        for block in blocks:
            if block[0][1].lstrip().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
                skipped += 1
                continue
            lines = [line for _, line in block]
            cue = next((i for i, line in enumerate(lines) if _CUE.search(line)), None)
            if cue is None:
                skipped += 1
                continue
            match = _CUE.search(lines[cue])
            body = "\n".join(lines[cue+1:]).strip()
            if body:
                records.extend(_chunks(body, f"lines {block[cue+1][0]}-{block[-1][0]}",
                    role="transcript", timestamp=fallback, timestamp_basis="file_modified_time_not_meeting_time",
                    cue_start=match[1], cue_end=match[2], epistemic="source_record"))
    else:
        lines = text.splitlines()
        for start in range(0, len(lines), 12):
            records.extend(_chunks("\n".join(lines[start:start+12]), f"lines {start+1}-{min(start+12,len(lines))}",
                role="transcript", timestamp=fallback, timestamp_basis="file_modified_time_not_meeting_time", epistemic="source_record"))
    return records, {"skipped_records": skipped, "format": "provided_transcript_text",
                     "coverage": "仅含用户选取的会议文字/字幕；文件修改时间不证明会议发生时间，不采集音频，也不验证说话者身份或任务完成。"}
