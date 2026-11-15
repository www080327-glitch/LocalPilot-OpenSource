"""Authenticated command dispatch; domain work stays in its owning component."""
from collections import deque
import re
from queue import Empty
import time
import uuid
from companion.observers.events import ObservationEvent, redact_text

class CommandRouter:
    def __init__(self, service):
        self.service = service
        self.handlers = {
            'activity_digest': self.activity_digest,
            'ask': self.ask,
            'authorize_observation': self.authorize_observation,
            'clear': self.clear,
            'consult_cloud': self.consult_cloud,
            'current_context': self.current_context,
            'delete_reminder': self.delete_reminder,
            'desktop_control_presented': self.desktop_control_presented,
            'dnd': self.dnd,
            'escalate': self.escalate,
            'escalation_status': self.escalation_status,
            'feedback_check': self.feedback_check,
            'feedback_health': self.feedback_health,
            'forget': self.forget,
            'forget_observation': self.forget_observation,
            'index': self.index,
            'inference_heartbeat': self.inference_heartbeat,
            'inference_options': self.inference_options,
            'inference_panel_presented': self.inference_panel_presented,
            'inference_start': self.inference_start,
            'localpilot_health': self.localpilot_health,
            'meeting_start': lambda data: service.meetings.start(data.get('capture'), data.get('locale', 'zh-CN'), data.get('label')),
            'meeting_stop': lambda data: service.meetings.stop(),
            'meeting_status': self.meeting_status,
            'notice_action': self.notice_action,
            'notice_presented': self.notice_presented,
            'notices': self.notices,
            'observations': self.observations,
            'pause_observation': self.pause_observation,
            'pet_ask': self.pet,
            'pet_export': self.pet,
            'pet_memory': self.pet,
            'prepare_cloud': self.prepare_cloud,
            'privacy': self.privacy,
            'proactive_settings': self.proactive_settings,
            'recent_memories': self.recent_memories,
            'remember': self.remember,
            'reminders': self.reminders,
            'retention': self.retention,
            'retrieve': self.retrieve,
            'review_context': self.review_context,
            'set_app_exclusions': self.set_app_exclusions,
            'set_reminder': self.set_reminder,
            'source_connect': self.source_connect,
            'source_list': lambda data: service.sources.list(),
            'source_sync': lambda data: service.sources.sync(data.get('source_id')),
            'source_set_enabled': self.source_set_enabled,
            'source_revoke': self.source_revoke,
            'source_coverage': self.source_coverage,
            'training_example_add': self.training_example_add,
            'training_examples': lambda data: service.training.list(),
            'training_example_delete': lambda data: service.training.delete(data.get('id')),
            'training_export': lambda data: service.training.export(data.get('seed', 17), data.get('validation_fraction', .2)),
            'shutdown': self.shutdown,
            'status': self.status,
            'submit_escalation': service.agent_tasks.submit,
            'task_cancel': self.task,
            'task_events': self.task,
            'task_status': self.task,
            'ui_snapshot': self.ui_snapshot,
        }

    def dispatch(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("command"), str):
            raise ValueError("Commands require a named JSON object")
        handler = self.handlers.get(data["command"])
        if handler is None:
            raise ValueError("Unknown command; no file mutation or shell tools are exposed")
        return handler(data)

    def source_connect(self, data):
        return self.service.sources.connect(data.get('kind'), data.get('path'), data.get('label'), data.get('follow', True))

    def source_revoke(self, data):
        if data.get('source_id') == self.service.meetings.state.get('source_id'):
            self.service.meetings.stop(discard=True)
        result = self.service.sources.revoke(data.get('source_id'))
        result['removed_training_examples'] = self.service.training.prune_missing()
        return result

    def source_set_enabled(self, data):
        result = self.service.sources.set_enabled(data.get('source_id'), data.get('enabled'))
        if data.get('enabled') is False and data.get('source_id') == self.service.meetings.state.get('source_id'):
            self.service.meetings.stop(discard=True)
        return result

    def meeting_status(self, data):
        self.service.meetings.drain()
        return self.service.meetings.status()

    def training_example_add(self, data):
        return self.service.training.add(data.get('question'), data.get('answer'), data.get('purpose'), data.get('observation_ids'))

    def source_coverage(self, data):
        service = self.service
        return {'status': 'ok', 'sources': service.sources.list()['sources'],
                'native': service.feedback_health(), 'files': list(service.config.watch_dirs),
                'paused': service.privacy.paused(), 'audio_capture': 'EXPLICIT_ON_DEVICE_ONLY',
                'meeting': service.meetings.status(),
                'hidden_application_history': 'NOT_OBSERVED',
                'model_capability_evaluation': 'NOT_RUN'}

    def pet(self, data):
        service = self.service
        from companion.runtime.pet import command
        return command(service, data)

    def ui_snapshot(self, data):
        service = self.service
        return {"status":"ok", "runtime":service.status(), "privacy":service.privacy.status(),
                "memories":service.recent_memories(),
                "observations":service.command({"command":"observations"})["observations"][:12],
                "notices":service.command({"command":"notices"})["notices"],
                "escalation":service.command({"command":"escalation_status"}), "proactive":service.policy.summary(),
                "feedback_health":service.feedback_health(), "reminders":service.store.get("explicit_reminders", []),
                "context_cards":service.visible_context(), "inference_control":service.controls.public(), "inference_options":service.controls.options(), "system_resources":service.resources.latest,"resource_alerts":service.resource_alerts}

    def inference_options(self, data):
        service = self.service
        values=service.controls.options()
        for key in ("allow_local_on_battery","allow_automatic_cloud"):
            if key in data:
                if type(data[key]) is not bool:raise ValueError("Automation switches must be boolean")
                values[key]=data[key]
        service.store.set("inference_options",values)
        return {"status":"ok","options":values}

    def inference_heartbeat(self, data):
        return self.service.controls.heartbeat(data.get("ticket_id"))

    def inference_panel_presented(self, data):
        return self.service.controls.ack(data.get("ticket_id"))

    def desktop_control_presented(self, data):
        return self.service.controls.desktop_presented(data.get('ticket_id'),data.get('pid'),data.get('routing_preferences'))

    def consult_cloud(self, data):
        service = self.service
        question=data.get('text')
        if not isinstance(question,str) or not question.strip() or len(question)>4000:raise ValueError('A bounded original question is required')
        return service.collaboration.prepare_question({'user_request':question},fallback={'reason':'user_requested_question_only_consultation','automatic_operation_replay':False},force_confirmation=True)

    def inference_start(self, data):
        return self.service.controls.start(data.get("ticket_id"),data.get("confirmed") is True)

    def prepare_cloud(self, data):
        service = self.service
        raw=service.store.get("pending_escalation")
        if not raw:raise ValueError("Prepare a question first")
        return service.collaboration.prepare_question(raw)

    def current_context(self, data):
        service = self.service
        from companion.memory.presentation import context_text
        cards = service.visible_context()
        return {"status":"ok", "text":context_text(cards), "cards":cards}

    def activity_digest(self, data):
        service = self.service
        from companion.memory.activity import activity_digest
        return activity_digest(service.observation_memory, data.get("day", "today"), data.get("limit", 30))

    def review_context(self, data):
        service = self.service
        cards = [c for c in service.visible_context() if c["text_chars"] >= 80 and time.time()-c["timestamp"] <= 1800][:3]
        if not cards:
            return {"status":"unavailable", "text":"当前只读到了少量界面标签，还不足以整理正文。近期观察页会显示实际读到的内容。", "model":{"status":"not_called"}}
        rows = []
        for card in cards:
            row = service.observation_memory.get(card["id"])
            if row and service.observation_accessible(row) and service.observation_memory.is_current(row):
                # Keep immutable source identity; a small evidence excerpt
                # fits the chat budget instead of sending the entire AX tree.
                rows.append({k:row[k] for k in ("id", "source", "source_reference", "timestamp", "kind", "object", "evidence_type", "evidence_epistemic", "evidence_digest")} |
                            {"summary":card["text"], "evidence":{"summary":card["text"], "window_title":card["title"], "read_status":card["read_status"]}})
        return service.ask("请深入分析最近获准窗口的可读文字，整理要点和明确提到的待办。将不同窗口分别列出；不把标题当作工作事实，不推断任务完成。", context_rows=rows)

    def feedback_health(self, data):
        service = self.service
        return {"status":"ok"} | service.feedback_health()

    def feedback_check(self, data):
        service = self.service
        health = service.feedback_health()
        text = "反馈链路检查：" + ("；".join(health["blockers"]) if health["blockers"] else "观察与本地提醒链路已配置") + "。这是一条状态检查，不是对工作内容的判断。"
        # This explicit check is an ordinary UI response, never an inferred
        # proactive event or a model-derived work fact.
        return {"status":"ok", "text":text, "health":health, "manual_check":True}

    def notice_presented(self, data):
        service = self.service
        if data.get("channel") != "native_banner":
            raise ValueError("Only the native banner presentation can be acknowledged here")
        row = service.store.db.execute("SELECT status,delivery FROM notices WHERE id=?", (data.get("id"),)).fetchone()
        if not row:
            raise ValueError("Unknown notice")
        if row["status"] == "pending" and row["delivery"] == "popup_available":
            service.store.db.execute("UPDATE notices SET delivery='displayed_native_banner' WHERE id=?", (data["id"],))
            service.store.db.commit()
            presented = service.store.get("notice_presented_times", {})
            presented[data["id"]] = time.time()
            service.store.set("notice_presented_times", dict(list(presented.items())[-100:]))
        return {"status":"ok"}

    def recent_memories(self, data):
        service = self.service
        return {"status":"ok", "memories":service.recent_memories(data.get("limit", 12))}

    def proactive_settings(self, data):
        service = self.service
        for field, choices in (("level", {"off", "low", "normal"}), ("delivery", {"silent", "enabled"})):
            if field in data and data[field] not in choices:
                raise ValueError("Invalid proactive setting")
        for field in ("level", "delivery"):
            if field in data:
                service.store.set("proactive_" + field, data[field])
        return {"status":"ok"} | service.policy.summary()

    def set_app_exclusions(self, data):
        service = self.service
        apps = data.get("apps")
        if (not isinstance(apps, list) or len(apps) > 100
                or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+", v) for v in apps)):
            raise ValueError("Exclusions require bounded bundle identifiers")
        service.native.stop()
        service.config.native_app_exclusions = tuple(dict.fromkeys(apps))
        from companion.observers.native import NativeObserver
        service.native = NativeObserver(service.config, service.enqueue_native)
        service.store.set("ui_app_exclusions", list(service.config.native_app_exclusions))
        service.store.set("native_observation_consent", None)
        service.store.set("pending_escalation", None)
        service.workflow.reset()
        return service.privacy.status() | {"status":"approval_required", "reason":"scope_changed"}

    def reminders(self, data):
        service = self.service
        return {"status":"ok", "reminders":service.store.get("explicit_reminders", [])}

    def set_reminder(self, data):
        service = self.service
        import math
        text, due = data.get("text"), data.get("due_at")
        if (not isinstance(text, str) or not text.strip() or len(text) > 300
                or type(due) not in (float, int) or not math.isfinite(due) or not time.time()-60 <= due <= time.time()+366*86400
                or data.get("confirmed") is not True):
            raise ValueError("A reminder requires an explicit bounded text, due time and confirmation")
        rows = service.store.get("explicit_reminders", [])
        if sum(not r.get("delivered") for r in rows) >= 32:
            raise ValueError("At most 32 pending reminders")
        item = {"id":uuid.uuid4().hex, "text":redact_text(text), "due_at":due,
                "created_at":time.time(), "evidence_type":"USER_CONFIRMED", "delivered":False}
        service.store.set("explicit_reminders", (rows+[item])[-100:])
        return {"status":"ok", "reminder":item}

    def delete_reminder(self, data):
        service = self.service
        service.store.set("explicit_reminders", [r for r in service.store.get("explicit_reminders", []) if r["id"] != data.get("id")])
        return {"status":"ok"}

    def status(self, data):
        service = self.service
        return service.status()

    def retention(self, data):
        service = self.service
        return {"status":"ok", "retention":service.retention()}

    def ask(self, data):
        service = self.service
        preferences=data.get('routing_preferences')
        if isinstance(preferences,dict) and preferences.get('source')=='cloud_only':
            return {'status':'cloud_confirmation_required','text':'完全云端会话不会调用本地轻量模型；请确认原问题的云端咨询。','model':{'status':'not_called'}}
        return service.ask(data.get("text", ""))

    def retrieve(self, data):
        service = self.service
        return {"status":"ok", "memories":service.retrieve(data.get("text", "")), "observations":service.observation_context(data.get("text", ""))}

    def observations(self, data):
        service = self.service
        return {"status":"ok", "observations":service.observation_context(data.get("text", "")) if data.get("text") else [r for r in service.observation_memory.records(limit=50, current_only=True) if service.observation_accessible(r)]}

    def forget_observation(self, data):
        service = self.service
        service.observation_memory.forget(data["id"])
        service.training.prune_missing()
        service.workflow.reset()
        service.store.set("pending_escalation", None)
        return {"status":"ok"}

    def privacy(self, data):
        service = self.service
        return service.privacy.status()

    def authorize_observation(self, data):
        service = self.service
        if data.get("confirmed") is True and data.get("expected_consent_id") is not None and data["expected_consent_id"] != service.privacy.consent_id():
            return {"status":"approval_required", "reason":"scope_changed", "scope":service.privacy.scope_description(), "consent_id":service.privacy.consent_id()}
        if data.get("confirmed") is True:
            service.observation_pause_requested.clear()
        result = service.privacy.authorize(data.get("confirmed") is True)
        if service.privacy.native_allowed():
            service.native.start()
        return result

    def pause_observation(self, data):
        service = self.service
        if type(data.get("paused")) is not bool:
            raise ValueError("Observation pause requires bool")
        service.store.set("observation_paused", data["paused"])
        service.inference_cancel_requested.clear()
        service.private.file("observation-pause-intent.json").unlink(missing_ok=True)
        if data["paused"]:
            service.observation_pause_requested.set()
        else:
            service.observation_pause_requested.clear()
        service.pending.clear()
        service.events.clear()
        service.workflow.reset()
        if data["paused"]:
            service.meetings.stop(discard=True)
            service.native.stop()
        elif service.privacy.native_allowed():
            service.native.start()
        if not data["paused"]:
            service.rescan_required = True
            service.scan()
        return service.privacy.status()

    def localpilot_health(self, data):
        service = self.service
        return service.localpilot.health(cloud_approved=data.get("cloud_approved") is True)

    def escalation_status(self, data):
        service = self.service
        pending = service.store.get("pending_escalation")
        return {"status":"ok", "pending":pending, "review_digest":service.review_digest(pending),
                "submission":service.store.get("pending_localpilot_submission"), "tasks":service.store.get("localpilot_tasks", {})}

    def task(self, data):
        service = self.service
        cmd = data["command"]
        return service.task_command(cmd, data)

    def notices(self, data):
        service = self.service
        explanations = service.store.get("notice_explanations", {})
        return {"status":"ok", "notices":[dict(r) | {"explanation":explanations.get(r["id"])} for r in service.store.db.execute("SELECT * FROM notices ORDER BY timestamp DESC LIMIT 20")]}

    def notice_action(self, data):
        service = self.service
        service.policy.respond(data["id"], data["action"])
        if data["action"] in {"ignore", "not_needed"}:
            service.count("ignored")
        elif data["action"] == "help":
            service.count("accepted_help")
        if data["action"] in {"reply", "help"}:
            ids=service.store.get("notice_explanations",{}).get(data["id"],{}).get("observation_ids",[])
            sources=[row for oid in ids if (row:=service.observation_memory.get(oid)) and service.observation_accessible(row) and service.observation_memory.is_current(row)]
            if ids and not sources:return {"status":"unavailable","text":"提醒来源已变化，未启动 Agent。"}
            result=service.ask(data.get("text") or "请帮助我排查这条提醒对应的问题，先核对可读证据。",force_help=data["action"]=="help",context_rows=sources or None)
            if data["action"]=="help" and result.get("control",{}).get("mode")=="execution":
                service.controls.grant_notice_help(data["id"]);result["control"]=service.controls.public()
            return result
        return {"status":"ok", "text":{"ignore":"已忽略。", "not_needed":"已记录，会减少同类提醒。", "useful":"谢谢反馈，会在限频范围内调整同类提醒。", "mute":"以后不再主动提醒这一类型。", "more":"会在每日上限和勿扰范围内多提醒这一类型。"}.get(data["action"], "已记录。")}

    def dnd(self, data):
        service = self.service
        if not isinstance(data.get("enabled"), bool):
            raise ValueError("DND requires bool")
        service.store.set("dnd", data["enabled"])
        return {"status":"ok", "dnd":data["enabled"]}

    def remember(self, data):
        service = self.service
        if data.get("type") not in {"user_fact", "preference"} or not isinstance(data.get("text"), str) or not data["text"].strip() or len(data["text"]) > 4000:
            raise ValueError("Only explicit bounded user facts/preferences can be saved here")
        text = redact_text(data["text"])
        key = data.get("fact_key", "")
        days = data.get("expires_days")
        import math
        if not isinstance(key, str) or len(key) > 256 or redact_text(key) != key:
            raise ValueError("Fact key must be a bounded nonsensitive label")
        if days is not None and (type(days) not in (int, float) or not math.isfinite(days) or not 0 < days <= 36500):
            raise ValueError("Fact expiry must contain finite positive days")
        if key and not 0 < len(text) <= 512:
            raise ValueError("An explicit structured fact must contain 1..512 characters")
        mid = service.store.add(data["type"], text, "explicit_user_statement", metadata={"expires_at":time.time()+days*86400 if days else None})
        normalized = ObservationEvent.create("explicit_user_statement", data["type"], {"memory_id":mid}, {"summary":text[:1200]},
                                             source_reference="user:memory:"+mid, important=True).to_dict()
        if key:
            normalized.update(claim_key=key, claim_value=text)
        if days:
            normalized["expires_at"] = time.time()+days*86400
        stored = service.observation_memory.add(normalized)
        return {"status":"ok", "id":mid, "observation_id":stored["id"]}

    def forget(self, data):
        service = self.service
        service.observation_memory.forget_source("user:memory:"+data["id"])
        record = service.store.db.execute("SELECT type, source_reference FROM memories WHERE id=?", (data["id"],)).fetchone()
        if record and record["type"] == "document":
            service.observation_memory.forget_source(record["source_reference"])
            service.store.db.execute("DELETE FROM memories WHERE source_reference=? AND type IN ('document','summary','computer_event')", (record["source_reference"],))
            service.events = deque((e for e in service.events if e.get("path") != record["source_reference"]), maxlen=200)
            service.workflow.reset()
        else:
            service.store.db.execute("DELETE FROM memories WHERE id=?", (data["id"],))
        service.store.db.commit()
        # Cached escalation excerpts must not outlive user memory deletion.
        service.store.set("pending_escalation", None)
        return {"status":"ok"}

    def clear(self, data):
        service = self.service
        if data.get("confirmation") != "DELETE_COMPANION_MEMORY":
            raise ValueError("Memory deletion confirmation missing")
        service.meetings.clear()
        service.native.stop()
        service.monitor_stop.set()
        retained_commands = []
        while True:
            try:
                queued = service.queue.get_nowait()
                if queued[0] == "command":
                    retained_commands.append(queued)
            except Empty:
                break
        for queued in retained_commands:
            service.queue.put_nowait(queued)
        observation_tables = [r[0] for r in service.store.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('observation_occurrences','observation_claims','observation_conflicts','observation_derivations','observation_versions','observation_document_links','observation_events','observation_fts','observation_occurrence_archive','connected_sources','source_import_files','training_examples')")]
        service.store.clear(extra_tables=observation_tables, state={"indexing_paused":True, "observation_paused":True,"pet_memory_enabled":service.store.get("pet_memory_enabled", True)})
        service.workflow.reset()
        service.pending.clear()
        service.events.clear()
        service.last_candidate.clear()
        service.model.wake_times.clear()
        service.model.load_times.clear()
        service.model.unload()
        service.model.last_result = None
        service.last_error = None
        return {"status":"ok", "memory_count":0, "indexing_paused":True, "text":"长期记忆已删除，文档索引已暂停。需要重新观察时运行 index。"}

    def index(self, data):
        service = self.service
        service.store.set("indexing_paused", False)
        service.store.set("observation_paused", False)
        service.scan()
        return service.status()

    def escalate(self, data):
        service = self.service
        question = data.get("text", "")
        return service.ask(question, force_help=True)

    def shutdown(self, data):
        service = self.service
        service.stopping = True
        service.monitor_stop.set()
        return {"status":"stopping"}
