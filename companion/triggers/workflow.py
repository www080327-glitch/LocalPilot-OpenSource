"""Host-only workflow evidence. Focus duration is never called editing or fatigue."""
from collections import deque
import hashlib
import json
import re


class WorkflowSignals:
    def __init__(self, sustained_minutes=45):
        self.events = deque(maxlen=200)
        self.sustained_minutes = sustained_minutes

    def reset(self):
        self.events.clear()

    def accept(self, event, observation_id):
        kind = event["kind"]
        if kind in {"system.did_wake", "system.will_sleep", "session.resigned_active", "session.became_active", "system.screens_sleep", "system.screens_wake"}:
            self.reset()
            return None
        obj, evidence = event["object"], event["evidence"]
        bundle = obj.get("bundle_id", "")
        if not bundle:
            return None
        now = event["timestamp"]
        if self.events and now-self.events[-1]["timestamp"] > 600:
            self.reset()
        # A title or file label does not establish a concrete failure. Search
        # only admitted static text (legacy trusted text fixtures stay usable).
        texts = [node["text"] for node in evidence.get("nodes", [])
                 if isinstance(node, dict) and node.get("role") == "AXStaticText" and isinstance(node.get("text"), str)]
        if isinstance(evidence.get("text"), str):
            texts.append(evidence["text"])
        text = "\n".join(texts)
        match = re.search(r"(?:Error|错误|阻塞)\s*[:：]\s*([^\n\"\]}]{3,120})", text, re.I)
        signature = hashlib.sha256(match.group(1).strip().encode()).hexdigest() if match else ""
        title = evidence.get("window_title", "")
        window = hashlib.sha256((bundle+"|"+title).encode()).hexdigest() if kind == "ax.snapshot" and isinstance(title,str) and title and texts else ""
        # Frequent identical notifications must not evict ten minutes of
        # evidence from the bounded deque. Replay identity is checked upstream.
        if self.events and window and self.events[-1]["window"] == window and self.events[-1]["signature"] == signature and now-self.events[-1]["timestamp"] < 20:
            return None
        self.events.append({"timestamp": now, "bundle": bundle, "id": observation_id,
                            "signature": signature, "kind": kind, "window":window, "static_chars":sum(map(len,texts))})
        recent = [e for e in self.events if now-e["timestamp"] <= 3600 and e["bundle"] == bundle]
        errors = [e for e in recent if signature and e["signature"] == signature]
        if len(errors) >= 3 and len({e["id"] for e in errors}) >= 3:
            return {"kind": "edits", "project": bundle, "same_error": True, "errors": len(errors),
                    "reason": "允许的静态界面文本中有三条不同观察记录显示相同错误文字；原因和困难程度未知", "observation_ids": [e["id"] for e in errors[-3:]]}
        usable = [e for e in self.events if e["window"] and e["static_chars"] >= 80 and now-e["timestamp"] <= 1800]
        if (len({e["timestamp"] for e in usable}) >= 3 and len({e["window"] for e in usable}) >= 1
                and now-min(e["timestamp"] for e in usable) >= 600):
            return {"kind":"context_review", "project":"近期窗口", "observation_ids":list(dict.fromkeys(e["id"] for e in usable))[-8:],
                    "context_count":len({e["window"] for e in usable}), "content_evidence":True,
                    "reason":"获准窗口确有静态文字，至少三次独立时刻的观察跨越10分钟；相同内容允许合并存储，不推断困难或任务完成"}
        # Repeated app switches alone carry too little help evidence to notify.
        return None
