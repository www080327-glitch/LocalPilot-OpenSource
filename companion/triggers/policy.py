from datetime import datetime
import time
import uuid
import json


def expire_notices(store, now=None):
    """Age unanswered records even under DND; update feedback exactly once."""
    now = time.time() if now is None else now
    with store.db:
        # A queued/silent item was not necessarily seen. Expiring it is not
        # evidence that the user ignored or rejected help.
        unseen = store.db.execute("UPDATE notices SET status='expired_unseen' WHERE status='pending' AND timestamp<? AND delivery<>'displayed_native_banner'", (now-3600,)).rowcount
        presented = store.get("notice_presented_times", {})
        rows = store.db.execute("SELECT id,type,timestamp FROM notices WHERE status='pending' AND timestamp<? AND delivery='displayed_native_banner'", (now-3600,)).fetchall()
        rows = [r for r in rows if presented.get(r["id"], r["timestamp"]) < now-3600]
        grouped = {}
        for r in rows: grouped[r["type"]] = grouped.get(r["type"], 0)+1
        aged = list(grouped.items())
        if not aged:
            return unseen
        count = sum(n for _, n in aged)
        store.db.executemany("UPDATE notices SET status='ignored' WHERE id=?", [(r["id"],) for r in rows])
        totals = store.get("runtime_totals", {})
        totals["ignored"] = totals.get("ignored", 0) + count
        feedback = store.get("notice_feedback", {})
        for kind, amount in aged:
            item = feedback.setdefault(kind, {})
            item["ignored"] = min(16, item.get("ignored", 0) + amount)
        for key, value in (("runtime_totals", totals), ("notice_feedback", feedback)):
            store.db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
    return count


class NoticePolicy:
    def __init__(self, config, store):
        self.config, self.store = config, store

    def quiet(self, now=None):
        if self.store.get("dnd", self.config.dnd):
            return True
        hour = datetime.fromtimestamp(time.time() if now is None else now).hour
        start, end = self.config.quiet_start_hour, self.config.quiet_end_hour
        return start <= hour < end if start < end else (hour >= start or hour < end) if start != end else False

    def allowed(self, kind, event_key, now=None):
        now = time.time() if now is None else now
        expire_notices(self.store, now)
        level = self.store.get("proactive_level", self.config.proactive_level)
        if level == "off" or (level == "low" and kind not in {"deadline", "repeated_error", "localpilot_completed", "explicit_reminder", "startup", "morning"}):
            return False
        if self.quiet(now):
            return False
        feedback = self.store.get("notice_feedback", {}).get(kind, {})
        if feedback.get("muted"):
            return False
        if self.store.db.execute("SELECT 1 FROM notices WHERE event_key=?", (event_key,)).fetchone():
            return False
        rows = list(self.store.db.execute("SELECT * FROM notices ORDER BY timestamp DESC LIMIT 1000"))
        settings = self.settings(kind)
        streak = self.store.get("ignore_streak", 0)
        unanswered = sum(r["status"] in {"pending", "ignored"} and r["delivery"] == "displayed_native_banner" for r in rows[:3])
        factor = 2 ** min(4, max(streak, unanswered))
        factor = max(factor, 2 ** min(4, feedback.get("ignored", 0)))
        if rows and now-rows[0]["timestamp"] < self.config.cooldown_seconds * factor:
            return False
        if sum(datetime.fromtimestamp(r["timestamp"]).date() == datetime.fromtimestamp(now).date() for r in rows) >= self.config.max_notices_per_day:
            return False
        if sum(r["type"] == kind and datetime.fromtimestamp(r["timestamp"]).date() == datetime.fromtimestamp(now).date() for r in rows) >= settings["daily_limit"]:
            return False
        if any(r["type"] == kind and now-r["timestamp"] < settings["cooldown_seconds"] * factor for r in rows):
            return False
        return True

    def settings(self, kind):
        feedback = self.store.get("notice_feedback", {}).get(kind, {})
        more = feedback.get("more", False)
        ignored = feedback.get("ignored", 0)
        # More reminders never lowers the original safety floor or global daily cap.
        threshold = min(.99, self.config.relevance_threshold + .02 * min(4, ignored))
        return {"muted": feedback.get("muted", False), "threshold": threshold,
                "cooldown_seconds": max(self.config.cooldown_seconds, self.config.type_cooldown_seconds * (.75 if more else 1)),
                "daily_limit": min(self.config.max_notices_per_day, 3 if more else 2),
                "ignore_backoff": 2 ** min(4, ignored)}

    def record(self, kind, key, message, delivery="popup_available", now=None):
        nid = uuid.uuid4().hex
        self.store.db.execute("INSERT INTO notices VALUES(?,?,?,?,?,?,?)", (nid, kind, key, now or time.time(), message[:600], "pending", delivery))
        self.store.db.commit()
        return nid

    def respond(self, notice_id, action):
        if action not in {"ignore", "not_needed", "reply", "help", "useful", "mute", "more"}:
            raise ValueError("Unknown notice action")
        row = self.store.db.execute("SELECT status,type FROM notices WHERE id=?", (notice_id,)).fetchone()
        if not row or row[0] not in {"pending", "ignored"}:
            raise ValueError("No actionable notice")
        self.store.db.execute("UPDATE notices SET status=? WHERE id=?", (action, notice_id))
        self.store.db.commit()
        self.store.set("ignore_streak", min(16, self.store.get("ignore_streak", 0)+1) if action in {"ignore", "not_needed"} else 0)
        all_feedback = self.store.get("notice_feedback", {})
        feedback = all_feedback.setdefault(row["type"], {"ignored":0, "useful":0, "muted":False})
        if action in {"ignore", "not_needed"}:
            feedback["ignored"] = min(16, feedback.get("ignored", 0) + 1)
        elif action in {"useful", "reply", "help", "more"}:
            feedback["ignored"] = 0
            feedback["useful"] = feedback.get("useful", 0) + 1
            if action == "more":
                feedback["more"] = True
                feedback["muted"] = False
        elif action == "mute":
            feedback["muted"] = True
        self.store.set("notice_feedback", all_feedback)
        if action in {"useful", "not_needed", "mute"}:
            feedback = self.store.get("explicit_notice_feedback", {})
            feedback[action] = feedback.get(action, 0) + 1
            self.store.set("explicit_notice_feedback", feedback)

    def summary(self):
        explicit = self.store.get("explicit_notice_feedback", {})
        total = explicit.get("useful", 0) + explicit.get("not_needed", 0)
        return {"level": self.store.get("proactive_level", self.config.proactive_level),
                "delivery": self.store.get("proactive_delivery", self.config.proactive_delivery),
                "feedback": explicit, "useful_rate": explicit.get("useful", 0) / total if total else None,
                "feedback_evidence": "USER_FEEDBACK" if total else "UNKNOWN",
                "type_feedback": self.store.get("notice_feedback", {})}
