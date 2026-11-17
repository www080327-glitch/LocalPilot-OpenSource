"""Durable Agent Service submission, task monitoring and outcome feedback."""
from dataclasses import asdict
import hashlib
import json
import re
from pathlib import Path
from queue import Full
import time
import uuid
import threading
from companion.escalation import EscalationRequest
from companion.observers.events import ObservationEvent, redact_text, sanitize, bounded_text

class TaskController:
    def __init__(self, service):
        self.service = service

    def context_current(self, request):
        service = self.service
        for original in request.get('relevant_memories', []):
            raw = service.store.db.execute('SELECT * FROM memories WHERE id=?', (original.get('id'),)).fetchone()
            if raw is None:
                return False
            row = dict(raw) | {'metadata':json.loads(raw['metadata'])}
            if not service.legacy_memory_accessible(row) or not service.store.is_current(row):
                return False
            if row['type'] == 'conversation' and not service.conversation_accessible(row):
                return False
            if row['type'] in {'document', 'summary', 'computer_event'}:
                indexed = service.store.db.execute('SELECT mtime_ns FROM files WHERE path=?', (row['source_reference'],)).fetchone()
                try:
                    if indexed is None or Path(row['source_reference']).stat().st_mtime_ns != indexed[0]:
                        return False
                except OSError:
                    return False
        if any(not service.scope.allowed(path) for path in request.get('relevant_files', [])):
            return False
        for row in request.get('recent_events', []):
            if row.get('observation_id'):
                if not service.observation_memory.is_current(row['observation_id']):
                    return False
            elif not service.scope.allowed(row.get('source_reference', '')):
                return False
        return True

    def session_context_current(self, session_id, before=None):
        records = [record for record in self.service.store.get('localpilot_tasks', {}).values()
                   if record.get('endpoint') == self.service.config.localpilot_endpoint
                   and (record.get('result') or record.get('last_status') or {}).get('session_id') == session_id
                   and (before is None or record.get('timestamp', 0) <= before)]
        return bool(records) and all('request' in record and self.context_current(record['request']) for record in records)

    def result_context_current(self, task_id):
        record = self.service.store.get('localpilot_tasks', {}).get(task_id)
        if not record or 'request' not in record:
            # Preserve the receipt in task history, but do not retrieve text
            # whose source permissions can no longer be reconstructed.
            return False
        session_id = (record.get('result') or record.get('last_status') or {}).get('session_id')
        return (self.session_context_current(session_id, record.get('timestamp')) if session_id
                else self.context_current(record['request']))

    def recover_submission_journal(self):
        """Repair a local crash between accepted-ID persistence and projections."""
        service = self.service
        intent = service.store.get("pending_localpilot_submission")
        if not intent or intent.get("endpoint") != service.config.localpilot_endpoint:
            return
        result = intent.get("result", {})
        task_id, session_id = result.get("task_id"), result.get("session_id")
        if not task_id or not session_id:
            return  # Lost response: retain the original key; explicit retry only.
        tasks = service.store.get("localpilot_tasks", {})
        tasks.setdefault(task_id, intent | {"last_status":result})
        service.store.set("localpilot_tasks", tasks)
        conversations = service.store.get("localpilot_conversations", {})
        conversations[intent.get("conversation_id", "local-user")] = {
            "session_id":session_id, "last_task_id":task_id, "endpoint":intent["endpoint"],
            "subject":intent.get("transport", {}).get("subject", service.config.localpilot_client_subject),
            "provider_kind":intent.get("transport", {}).get("provider_kind", "local")}
        service.store.set("localpilot_conversations", conversations)
        service.store.set("pending_localpilot_submission", None)
        service.store.set("pending_escalation", None)

    def escalation(self, question, trigger, memories):
        # Speaker recall exports only delivered speech and revocation IDs;
        # rejected citation diagnostics are not conversation content.
        service = self.service
        memories = [dict(r, metadata={k:v for k,v in r.get("metadata", {}).items()
                    if k in {"role", "memory_ids", "observation_ids", "delivery"}})
                    if r.get("type") == "conversation" else r for r in memories]
        files = list(dict.fromkeys(r["source_reference"] for r in memories if r["type"] == "document" and service.scope.allowed(r["source_reference"])))[:5]
        # Only retrieved event records are exported, not the complete activity history.
        observations = [r | {"observation_id":r["id"]} for r in service.observation_context(question)][:3]
        return EscalationRequest(question, trigger, "需要完整 Agent 的规划、操作或复杂分析能力", memories, files,
                                 ([r for r in memories if r["type"] == "computer_event"] + observations)[:5],
                                 {"local_only":not (service.config.localpilot_allow_cloud if service.localpilot.available() else service.config.agent_allow_remote),
                                  "file_content":"retrieved excerpts only", "requires_user_approval":True}, "Companion 只准备请求，没有执行任务。")

    @staticmethod
    def review_digest(raw):
        return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest() if raw else None

    def reconcile_closed_session_rejection(self):
        """Archive only a proven pre-admission rejection; never retry an unknown POST."""
        service = self.service
        intent=service.store.get("pending_localpilot_submission") or {}
        result=intent.get("result") or {};error=result.get("error") or {};transport=intent.get("transport") or {}
        if (intent.get("endpoint")!=service.config.localpilot_endpoint or result.get("task_id") or
                error.get("code")!="session_closed" or error.get("http_status")!=409 or
                result.get("task_execution")!="not_started" or not transport.get("session_id")):
            return False
        provider=service.cloud_localpilot if transport.get("provider_kind")=="cloud" else service.localpilot
        proof=provider.restore_session(transport["session_id"],cloud_approved=intent.get("cloud_approved") is True)
        if proof.get("status")!="closed":return False
        history=service.store.get("rejected_submission_history",[]);history.append(intent)
        service.store.set("rejected_submission_history",history[-20:])
        bindings=service.store.get("localpilot_conversations",{})
        service.store.set("localpilot_conversations",{k:v for k,v in bindings.items() if v.get("session_id")!=transport["session_id"]})
        service.store.set("pending_localpilot_submission",None)
        return True

    def prepare_escalation(self, request, mode="execution", automatic=False):
        service = self.service
        if getattr(service, "pet_request", False):
            from companion.runtime.pet import delegation, agent_profile
            return delegation(request.user_request, agent_profile(request.user_request) or "standard")
        service.reconcile_closed_session_rejection()
        if service.store.get("pending_localpilot_submission"):
            return {"status":"recovery_required", "text":"上一次任务提交状态不明确，请先核对升级状态；原请求已保留。"}
        service.store.set("pending_escalation", asdict(request))
        service.store.set("pending_escalation_mode", mode)
        if automatic and service.config.localpilot_auto_local and service.config.localpilot_host_local_only and service.localpilot.available():
            return service.automatic_local_task()
        result = service.localpilot.submit(request) if service.localpilot.available() else {
            "status":"unavailable", "connection_state":"LOCALPILOT_UNAVAILABLE", "task_execution":"not_started"}
        return {"status":"escalation", "text":"这个请求需要完整 Agent。当前升级状态：" + result["status"],
                "escalation":result, "review_digest":service.review_digest(asdict(request))}

    def automatic_local_task(self):
        service = self.service
        mode=service.store.get("pending_escalation_mode","reasoning")
        result=service.controls.prepare("local",mode)
        if mode=="reasoning":
            unavailable=result.get("status")=="unavailable"
            auto_resource_alternative=service.controls.options()["allow_automatic_cloud"] and bool(result.get("control",{}).get("required_confirmations"))
            if unavailable or auto_resource_alternative:
                return service.collaboration.prepare_question(service.store.get("pending_escalation"),fallback={"reason":"local_backend_unavailable" if unavailable else "local_resource_limit","automatic_operation_replay":False})
        return result

    @staticmethod
    def task_summary(result):
        keys = {"status", "phase", "task_id", "session_id", "quiescent", "task_execution", "submission_id", "context_digest",
                "automatic_retry", "automatic_resume", "cancel_requested", "last_event_id", "verification_status", "engineering_status", "evidence_level", "error", "semantic_status", "goal_verified", "unknown_mutation", "runtime_status", "deliverable_status", "retry_after_seconds", "connection_state", "progress_text", "progress_snapshot", "reason", "reasoning_help_requested"}
        summary = {k:result[k] for k in keys if k in result and (type(result[k]) in (str, int, float, bool) or result[k] is None)}
        summary = sanitize(summary)
        if isinstance(result.get("agent_response"), str):
            summary["agent_response"] = bounded_text(result["agent_response"])
        action = result.get("required_action")
        if isinstance(action, dict):
            summary["required_action"] = sanitize({k:action[k] for k in ("type", "id", "status") if k in action})
        if isinstance(result.get("model_resource"),dict):
            summary["model_resource"]=result["model_resource"]
        if isinstance(result.get("cache_usage"), dict):
            summary["cache_usage"] = result["cache_usage"]
        error = result.get("error")
        if isinstance(error, dict):
            summary["error"] = sanitize({k:error[k] for k in ("code", "http_status") if k in error})
        return summary

    def provider_for_task(self, task_id):
        service = self.service
        record=service.store.get("localpilot_tasks",{}).get(task_id,{})
        return service.cloud_localpilot if record.get("transport",{}).get("provider_kind")=="cloud" else service.localpilot

    def task_history(self, limit=30, before=None):
        tasks = self.service.store.get("localpilot_tasks", {})
        records = sorted(tasks.items(), key=lambda item:(item[1].get("timestamp", 0), item[0]), reverse=True)
        if before is not None:
            records = [item for item in records if (item[1].get("timestamp", 0), item[0]) < (before["timestamp"], before["id"])]
        page = records[:limit]
        cursor = {"timestamp":page[-1][1].get("timestamp", 0), "id":page[-1][0]} if len(records) > limit else None
        return {"tasks":{task_id:self.task_preview(task_id, record) for task_id, record in page},
                "total":len(tasks), "next_before":cursor}

    @staticmethod
    def task_preview(task_id, record):
        current = record.get("last_status") or record.get("result", {})
        keys = ("status", "phase", "task_id", "session_id", "quiescent", "task_execution", "submission_id",
                "goal_verified", "unknown_mutation", "verification_status", "engineering_status", "last_event_id",
                "cancel_requested", "required_action")
        summary = {key:current[key] for key in keys if key in current}
        for key in ("progress_text", "agent_response"):
            if key in current:
                summary[key] = bounded_text(current[key], 1200)
        if "cache_usage" in current:
            summary["cache_usage"] = {key:current["cache_usage"][key] for key in
                ("status", "cache_hit_ratio", "cache_miss_tokens", "output_tokens") if key in current["cache_usage"]}
        transport = record.get("transport", {})
        preview = {"task_id":task_id, "timestamp":record.get("timestamp", 0), "last_status":summary,
                   "transport":{key:transport[key] for key in ("provider_kind", "mode") if key in transport}}
        for key in ("phase", "submission_id", "endpoint"):
            if key in record:
                preview[key] = record[key]
        if "user_request" in record:
            preview["user_request"] = bounded_text(record["user_request"], 600)
        if "feedback" in record:
            preview["feedback"] = {"text":bounded_text(record["feedback"].get("text", ""), 1200)}
        if "connection_error" in record:
            error = record["connection_error"]
            preview["connection_error"] = {key:error[key] for key in ("status", "error") if key in error}
            if "reason" in error:
                preview["connection_error"]["reason"] = bounded_text(error["reason"], 600)
        return preview

    def task_command(self, cmd, data):
        service = self.service
        task_id = data.get("task_id", "")
        tasks = service.store.get("localpilot_tasks", {})
        record = tasks.get(task_id)
        if not record or record.get("endpoint") != service.config.localpilot_endpoint:
            raise ValueError("Only tasks submitted by this Companion at its current endpoint are accessible")
        provider=service.provider_for_task(task_id)
        cloud = data.get("cloud_approved") is True
        if cmd == "task_cancel":
            result = provider.cancel(task_id, approved=data.get("approved") is True, cloud_approved=cloud)
        elif cmd == "task_events":
            frames = []
            for frame in provider.stream(task_id, after=data.get("after", 0), cloud_approved=cloud):
                summary = service.task_summary(frame)
                summary["event"] = str(frame.get("event", ""))[:100]
                if frame.get("task_status"):
                    summary["task_status"] = service.task_summary(frame["task_status"])
                    service.receive_task_update(task_id, frame["task_status"])
                frames.append(summary)
            result = {"status":"ok", "events":frames, "last_event_id":frames[-1].get("last_event_id", data.get("after", 0)) if frames else data.get("after", 0)}
        else:
            result = provider.status(task_id, cloud_approved=cloud)
            if not result.get("quiescent") and result.get("status") not in {"unavailable", "approval_required"}:
                service.monitor_task(task_id, result.get("last_event_id", 0), cloud)
        if cmd == "task_events":
            tasks = service.store.get("localpilot_tasks", {})
            tasks[task_id]["last_event_cursor"] = result["last_event_id"]
            service.store.set("localpilot_tasks", tasks)
        else:
            service.receive_task_update(task_id, result)
        return result

    def store_task_result(self, result):
        service = self.service
        memory = service.localpilot.result_memory(result)
        if memory:
            task_id = result["task_id"]
            proof = service.task_summary(result) | {"summary":bounded_text(memory.get("text", ""))[:1200], "epistemic":"reported"}
            try:
                event = ObservationEvent.create("localpilot", "task_result", {"task_id":task_id}, proof,
                                                 source_reference="localpilot:task:"+task_id, important=True)
                service.observation_memory.add(event.to_dict() | {"occurrence_id":event.dedupe_key})
                result["memory_write"] = "stored"
            except Exception as exc:
                service.record_error("task_result_memory", exc)
                result["memory_write"] = "failed"

    def receive_task_update(self, task_id, result):
        service = self.service
        tasks = service.store.get("localpilot_tasks", {})
        record = tasks.get(task_id)
        if not record or record.get("endpoint") != service.config.localpilot_endpoint:
            return
        service.store_task_result(result)
        summary = service.task_summary(result)
        if summary.get("status") in {"unavailable", "approval_required", "submission_unknown"}:
            # A failed observation cannot replace the last service-owned state.
            tasks[task_id]["connection_error"] = summary
        else:
            previous = tasks[task_id].get("last_status", tasks[task_id].get("result", {}))
            tasks[task_id]["last_status"] = previous | summary
            tasks[task_id].pop("connection_error", None)
        if type(result.get("last_event_id")) is int:
            tasks[task_id]["last_event_cursor"] = result["last_event_id"]
        service.task_feedback(task_id, tasks[task_id], result)
        tasks[task_id]["last_checked_at"] = time.time()
        service.store.set("localpilot_tasks", tasks)
        service.controls.task_update(task_id,result)
        control=service.controls.current
        action=result.get("required_action") or {}
        if (control and control.get("task_id")==task_id and control.get("kind")=="cloud" and
                control.get("phase")=="running" and not service.controls.stop_event.is_set() and
                result.get("status")=="requires_approval" and action.get("id") and
                control.get("cloud_action_attempted")!=action["id"]):
            control["cloud_action_attempted"]=action["id"];service.controls.save()
            approved=service.cloud_localpilot.approve_cloud_egress(task_id,action["id"])
            if approved.get("task_id"):service.receive_task_update(task_id,approved)
        service.collaboration.consider(task_id,result)
        if result.get("quiescent") and result.get("status") in {"cancelled","timed_out"}:
            bindings=service.store.get("localpilot_conversations",{})
            service.store.set("localpilot_conversations",{k:v for k,v in bindings.items() if v.get("last_task_id")!=task_id})

    def task_feedback(self, task_id, record, result):
        service = self.service
        status = result.get("status")
        terminal = result.get("quiescent") and status in {"completed", "incomplete", "failed", "cancelled", "timed_out"}
        attention = status in {"requires_approval", "requires_human"}
        if not terminal and not attention:
            return
        if result.get("unknown_mutation"):
            text = "LocalPilot 的执行结果尚不确定，请查看任务收据并核对；不会自动重做。"
        elif status == "completed":
            text = ("LocalPilot 已返回结果，配置的验收已通过。" if result.get("goal_verified") is True
                    else "LocalPilot 已返回结果，任务目标尚未经独立验收，请查看回复。")
        else:
            text = {"incomplete":"LocalPilot 本轮尚未完成任务，请查看已完成部分和阻塞原因。",
                    "failed":"LocalPilot 本轮执行失败，请查看错误与已产生的收据。",
                    "cancelled":"LocalPilot 任务已停止，请查看停止前的结果与收据。",
                    "timed_out":"LocalPilot 任务已超时并停止，请查看已产生的结果。",
                    "requires_approval":"LocalPilot 正在等待已有权限流程中的批准，请查看待批准事项。",
                    "requires_human":"LocalPilot 需要你接手，请查看任务中的具体原因。"}[status]
        action = result.get("required_action") or {}
        key = f"task-feedback:{task_id}:{status}:{action.get('id', '')}:{bool(result.get('unknown_mutation'))}:{bool(result.get('goal_verified'))}"
        previous = record.get("feedback", {})
        record["feedback"] = {"event_key":key, "text":text, "status":status, "task_id":task_id, "quiescent":bool(result.get("quiescent")),
                              "goal_verified":result.get("goal_verified") is True, "unknown_mutation":bool(result.get("unknown_mutation"))}
        if previous.get("event_key") == key and previous.get("notice_id"):
            record["feedback"]["notice_id"] = previous["notice_id"]
        kind = "localpilot_completed" if terminal else "localpilot_attention"
        nid = service.emit_notice(kind, key, text)
        if nid:
            record["feedback"]["notice_id"] = nid
            explanations = service.store.get("notice_explanations", {})
            explanations[nid] = {"reason":"authoritative_task_status", "task_id":task_id,
                                 "status":status, "basis":"host_task_status", "result_quality":"UNVERIFIED"}
            service.store.set("notice_explanations", dict(list(explanations.items())[-100:]))

    def monitor_task(self, task_id, after=0, cloud_approved=False, provider=None):
        """Read-only monitoring of an already authorized task, with no tool approval."""
        service = self.service
        service.task_monitors = {k:v for k,v in service.task_monitors.items() if v.is_alive()}
        if task_id in service.task_monitors or len(service.task_monitors) >= 2:
            return
        if service.monitor_stop.is_set():
            if service.task_monitors:
                return
            service.monitor_stop = threading.Event()
        stop_event = service.monitor_stop
        provider = provider or service.provider_for_task(task_id)

        def run():
            cursor = after
            progress = ""
            def deliver(view):
                if stop_event.is_set():
                    return
                try:
                    service.queue.put_nowait(("task_update", task_id, service.task_summary(view)))
                except Full:
                    pass  # Reconnect snapshot remains authoritative.
            def reconcile(view):
                nonlocal cursor, progress
                sequence = view.get("last_event_id")
                if view.get("progress_snapshot") is True and type(sequence) is int and sequence >= cursor:
                    progress = view["progress_text"]
                    cursor = sequence
                deliver(view)
            while not stop_event.is_set():
                # Snapshot precedes each subscription, including after a disconnect.
                view = provider.status(task_id, cloud_approved=cloud_approved)
                reconcile(view)
                if view.get("quiescent") and view.get("status") in {"completed", "incomplete", "failed", "cancelled", "timed_out"}:
                    # Still replay the first subscription to preserve available events.
                    if cursor:
                        return
                unavailable = view.get("status") in {"unavailable", "approval_required"}
                delay = max(30, view.get("retry_after_seconds", 0))
                resubscribe = False
                if not unavailable:
                    for frame in provider.stream(task_id, after=cursor, cloud_approved=cloud_approved):
                        if stop_event.is_set():
                            return
                        if frame.get("status") == "event":
                            cursor = frame["last_event_id"]
                            wire = frame.get("data", {}).get("data", {})
                            if wire.get("type") == "TextDelta":
                                progress = (progress+str(wire.get("data", {}).get("text", "")))[-4000:]
                            if frame.get("task_status",{}).get("quiescent") and frame["task_status"].get("status") in {"completed","incomplete","failed","cancelled","timed_out"}:
                                final=provider.status(task_id,cloud_approved=cloud_approved)
                                if final.get("status") not in {"unavailable","approval_required"}:
                                    deliver(final);return
                            update = frame.get("task_status") or {"last_event_id":cursor, "progress_text":progress}
                            deliver(update | {"last_event_id":cursor})
                        elif frame.get("error", {}).get("http_status") == 409:
                            previous_cursor = cursor
                            fresh = provider.status(task_id, cloud_approved=cloud_approved)
                            reconcile(fresh)
                            if fresh.get("task_id") and fresh.get("status") not in {"unavailable", "approval_required"}:
                                next_cursor = fresh.get("last_event_id", cursor)
                                cursor = max(cursor, next_cursor)
                                resubscribe = cursor > previous_cursor
                                view = fresh
                                break
                        delay = max(delay, frame.get("retry_after_seconds", 0))
                if view.get("quiescent") and view.get("status") in {"completed", "incomplete", "failed", "cancelled", "timed_out"}:
                    return
                if resubscribe:
                    continue
                if stop_event.wait(delay):
                    return
        thread = threading.Thread(target=run, name="CompanionTaskMonitor", daemon=True)
        service.task_monitors[task_id] = thread
        thread.start()

    def submit(self, data):
        service = self.service
        if not service.controls._test_bypass and (not service.controls.authorized_nonce or data.get("_host_control_nonce")!=service.controls.authorized_nonce):
            return service.controls.prepare("cloud" if data.get("cloud_approved") is True else "local",service.store.get("pending_escalation_mode","execution"))
        raw = service.store.get("pending_escalation")
        if not raw:
            raise ValueError("No pending escalation")
        digest = service.review_digest(raw)
        # Direct CLI approval is also bound to a read immediately before send.
        # The UI must pass the digest from the review shown in its dialog.
        for r in raw["relevant_memories"]:
            if r["type"] in {"document", "summary"} and service.scope.within(r["source_reference"]):
                try:
                    source_bytes, _ = service.scope.read(r["source_reference"])
                    if hashlib.sha256(source_bytes).hexdigest() != r.get("provenance", {}).get("file_hash"):
                        service.process_file(r["source_reference"], "refresh")
                except Exception:
                    service.store.invalidate_source(r["source_reference"])
        if any(not service.legacy_memory_accessible(r) or (r.get("provenance", {}).get("version_id") and not service.store.db.execute("SELECT 1 FROM source_versions WHERE id=? AND current=1", (r["provenance"]["version_id"],)).fetchone()) for r in raw["relevant_memories"]):
            service.store.set("pending_escalation", None)
            return {"status":"unavailable", "reason":"Source memories changed; prepare and review a new escalation request"}
        # Revalidate current privacy scope immediately before sending, including file deletion.
        raw["relevant_memories"] = [r for r in raw["relevant_memories"] if r["type"] not in {"document", "computer_event", "project", "summary"} or service.scope.within(r["source_reference"])]
        raw["relevant_files"] = [f for f in raw["relevant_files"] if service.scope.allowed(f) and Path(f).exists()]
        for r in raw["recent_events"]:
            if r.get("observation_id"):
                current = service.observation_memory.get(r["observation_id"])
                if not current or not service.observation_accessible(current) or not service.observation_memory.is_current(current):
                    service.store.set("pending_escalation", None)
                    return {"status":"unavailable", "reason":"Observation sources changed; review a new escalation"}
        raw["recent_events"] = [r for r in raw["recent_events"] if r.get("observation_id") and service.observation_accessible(r)] + [r for r in raw["recent_events"] if not r.get("observation_id") and service.scope.within(r.get("source_reference", ""))]
        if data.get("approved") is True and (data.get("expected_digest") is not None or service.localpilot.available()) and data.get("expected_digest") != digest:
            return {"status":"approval_required", "reason":"Reviewed request changed or review digest is missing", "review_digest":digest}
        if service.store.get("pending_escalation_mode","execution")=="execution" and not service.controls._test_bypass and data.get("user_help_approved") is not True:
            return {"status":"approval_required","reason":"Standard Agent help needs explicit user confirmation"}
        provider=service.cloud_localpilot if data.get("provider_kind")=="cloud" else service.localpilot
        if provider.available():
            if data.get("approved") is not True:
                return provider.submit(EscalationRequest(**raw))
            if data.get("cloud_approved") is True:
                raw = dict(raw)
                raw["privacy_scope"] = dict(raw["privacy_scope"], classification="USER_APPROVED_CLOUD")
            mode = service.store.get("pending_escalation_mode", "execution")
            provider_kind=data.get("provider_kind","local")
            default_conversation="local-user.reasoning" if mode=="reasoning" else "local-user"
            if provider_kind=="cloud":default_conversation+=".cloud"
            conversation = data.get("conversation_id", default_conversation)
            if not isinstance(conversation, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", conversation):
                raise ValueError("Invalid conversation ID")
            sessions = service.store.get("localpilot_conversations", {})
            binding = sessions.get(conversation)
            if binding and (binding["endpoint"] != service.config.localpilot_endpoint or binding["subject"] != service.config.localpilot_client_subject):
                return {"status":"recovery_required", "reason":"Conversation identity or endpoint changed"}
            if binding and binding.get("provider_kind","local")!=provider_kind:
                return {"status":"recovery_required","reason":"Local and cloud history require separate conversations"}
            # Each question-only cloud grant covers one original question, not
            # prior consultations. Ambiguous retries keep their original intent.
            pending_intent=service.store.get("pending_localpilot_submission")
            if provider_kind=="cloud" and not pending_intent:
                if data.get("session_id"):
                    return {"status":"denied","reason":"Question-only cloud consultations require a fresh session"}
                binding=None
            session_id = (pending_intent.get("transport",{}).get("session_id") if provider_kind=="cloud" and pending_intent else
                          data.get("session_id") or (binding or {}).get("session_id"))
            known_session = any((record.get('result') or record.get('last_status') or {}).get('session_id') == session_id
                                for record in service.store.get('localpilot_tasks', {}).values()) if session_id else False
            if session_id and not pending_intent and (known_session or binding and binding.get('session_id') == session_id):
                if not self.session_context_current(session_id):
                    if data.get('session_id'):
                        return {'status':'unavailable', 'reason':'Session source access changed; use a new session'}
                    sessions.pop(conversation, None)
                    service.store.set('localpilot_conversations', sessions)
                    binding = None
                    session_id = None
            if binding and session_id and not data.get("session_id") and not service.store.get("pending_localpilot_submission"):
                restored=provider.restore_session(session_id,cloud_approved=data.get("cloud_approved") is True)
                if restored.get("status")=="closed":
                    sessions.pop(conversation,None);service.store.set("localpilot_conversations",sessions);session_id=None
                elif restored.get("status")!="ready":
                    return {"status":"recovery_required","reason":"Session state could not be confirmed; no task was resubmitted"}
            if provider_kind=="cloud" and data.get("session_id") and not binding:
                return {"status":"denied","reason":"Explicit session must belong to this bound conversation"}
            if session_id and any(k != conversation and v.get("session_id") == session_id for k,v in sessions.items()):
                return {"status":"denied", "reason":"Session belongs to another conversation"}
            previous = service.store.get("pending_localpilot_submission")
            if previous and data.get("retry") is True and previous.get("transport",{}).get("automatic_local") is True:
                data=dict(data,automatic_local=True)
            if previous and data.get("retry") is not True:
                return {"status":"recovery_required", "submission":previous,
                        "reason":"A submission intent exists; inspect its task before submitting again"}
            if previous and previous.get("endpoint") != service.config.localpilot_endpoint:
                return {"status":"recovery_required", "reason":"Pending submission belongs to another endpoint"}
            provider_config=getattr(provider,"config",service.config)
            transport = {"mode":mode, "reasoning_protocol_version":1, "user_help_approved":data.get("user_help_approved") is True, "analysis_route":provider_config.localpilot_analysis_route, "endpoint":service.config.localpilot_endpoint, "route":service.config.localpilot_route,
                         "timeout":service.config.localpilot_task_timeout_seconds, "max_context":service.config.localpilot_max_context_chars,
                         "session_id":session_id, "conversation_id":conversation, "subject":service.config.localpilot_client_subject, "credential_env":service.config.localpilot_api_key_env, "scope":service.privacy.consent_id(),
                         "host_local_only":provider_config.localpilot_host_local_only, "allow_cloud":provider_config.localpilot_allow_cloud, "automatic_local":data.get("automatic_local") is True,"provider_kind":data.get("provider_kind","local"),"memory_ticket":data.get("memory_ticket")}
            if data.get('routing_preferences') is not None:transport['routing_preferences']=data['routing_preferences']
            effective_digest = service.review_digest(raw)
            if previous and (previous.get("review_digest") != digest or previous.get("effective_digest") != effective_digest or previous.get("transport") != transport):
                return {"status":"recovery_required", "reason":"Original task context or transport changed; no resubmission performed"}
            intent = previous or {"submission_id":uuid.uuid4().hex, "endpoint":service.config.localpilot_endpoint,
                      "timestamp":time.time(), "phase":"authorized", "user_request":redact_text(raw["user_request"]),
                      "review_digest":digest, "effective_digest":effective_digest, "transport":transport, "request":raw, "conversation_id":conversation}
            intent["cloud_approved"] = data.get("cloud_approved") is True
            service.store.set("pending_localpilot_submission", intent)
            service.controls.bind_submission(intent["submission_id"])
            result = provider.submit(EscalationRequest(**raw), approved=True,
                       cloud_approved=data.get("cloud_approved") is True,
                       session_id=session_id, submission_id=intent["submission_id"], mode=mode, automatic_local=data.get("automatic_local") is True, memory_ticket=data.get("memory_ticket"),resource_scopes=data.get("resource_scopes",("memory",)),control_ticket=data.get("control_ticket"),
                       **({'routing_preferences':data['routing_preferences']} if data.get('routing_preferences') is not None else {}))
            if previous and not result.get("task_id") and result.get("submission_attempted") is False:
                result=dict(result,status="submission_unknown",phase="unknown",submission_id=intent["submission_id"])
                result["submission_attempted"]=True  # An earlier transmission is still unresolved.
            intent.update(phase="submitted" if result.get("task_id") else result.get("phase", "submission_unknown"), result=service.task_summary(result))
            service.store.set("pending_localpilot_submission", intent)
            if result.get("task_id"):
                sessions[conversation] = {"session_id":result["session_id"], "endpoint":service.config.localpilot_endpoint,
                                          "subject":service.config.localpilot_client_subject, "provider_kind":provider_kind, "last_task_id":result["task_id"]}
                service.store.set("localpilot_conversations", sessions)
                tasks = service.store.get("localpilot_tasks", {})
                intent["last_status"] = service.task_summary(result)
                tasks[result["task_id"]] = intent
                service.store.set("localpilot_tasks", tasks)
                service.store.set("pending_escalation", None)
                service.store.set("pending_localpilot_submission", None)
                if data.get("defer_monitor") is not True:
                    service.monitor_task(result["task_id"], result.get("last_event_id", 0), intent["cloud_approved"])
            elif not previous and (result.get("submission_attempted") is False or result.get("error", {}).get("code") in {"host_policy_unknown", "cloud_disabled", "cloud_approval_required", "analysis_route_unconfigured", "analysis_route_not_isolated", "local_only_context", "host_policy_mismatch", "route_policy_unknown", "low_power_local_backend_blocked","resource_control_unconfigured","client_request_stopped","task_input_too_large"}):
                service.store.set("pending_localpilot_submission", None)
            # Keep intent/key through 429, authentication and transport failures.
            # Repeated transmission may only use the original reviewed request.
            return result
        return {"status":"unavailable", "connection_state":"LOCALPILOT_UNAVAILABLE", "task_execution":"not_started",
                "reason":"Configure the native Agent Service; direct provider fallback is disabled"}
