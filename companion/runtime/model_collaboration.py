"""Host policy for a new, consent-gated cloud consultation after local reasoning.

This observes native Tasks; it never replays Agent operations or implements an
Agent runtime. Model capability claims can suggest a consultation, not grant it.
"""
from dataclasses import asdict
import time

from companion.escalation.provider import EscalationRequest


class ModelCollaboration:
    def __init__(self, app):self.app=app

    def prepare_question(self, raw, *, fallback=None, force_confirmation=False):
        if not raw or not isinstance(raw.get("user_request"),str):
            return {"status":"unavailable","text":"没有可供核对的原问题。"}
        if self.app.store.get("pending_localpilot_submission"):
            return {"status":"recovery_required","text":"原提交尚不明确，先恢复原任务；没有向云端重放。"}
        # The local answer and all local observations/receipts stay on this Mac.
        question=EscalationRequest(raw["user_request"],"local_to_cloud_consultation",
            "仅咨询原问题，不执行或重放 Agent 操作",[],[],[],
            {"local_only":False,"classification":"PUBLIC","context_policy":"explicit_request_only"},"")
        self.app.store.set("pending_escalation",asdict(question))
        self.app.store.set("pending_escalation_mode","reasoning")
        return self.app.controls.prepare("cloud","reasoning",force_cloud_confirmation=force_confirmation,fallback=fallback)

    def consider(self, task_id, result):
        tasks=self.app.store.get("localpilot_tasks",{});record=tasks.get(task_id)
        if not record or record.get("cloud_fallback"):return None
        transport=record.get("transport",{})
        if transport.get("provider_kind","local")!="local" or transport.get("mode")!="reasoning":return None
        current=self.app.controls.current
        if (not current or current.get("task_id")!=task_id or current.get("phase")!="finished"
                or self.app.controls.stop_event.is_set()):return None
        if record.get("endpoint")!=self.app.config.localpilot_endpoint or transport.get("scope")!=self.app.privacy.consent_id():return None
        if result.get("quiescent") is not True or result.get("status") in {"cancelled","requires_approval","requires_human"}:return None
        resource=result.get("model_resource") or {}
        if resource.get("managed") is True and resource.get("model_process_alive") is not False:return None
        task=result.get("task") or {}
        if (result.get("unknown_mutation") or result.get("recovery") or task.get("tools")
                or (task.get("receipt_summary") or {}).get("count",0)):
            return None
        hard_failure=result.get("status") in {"failed","incomplete","timed_out"}
        capability_hint=result.get("status")=="completed" and result.get("reasoning_help_requested") is True
        if not hard_failure and not capability_hint:return None
        pending=self.app.store.get("pending_escalation")
        if pending and self.app.review_digest(pending)!=record.get("review_digest"):return None
        fallback={"from_task_id":task_id,"reason":"local_task_not_completed" if hard_failure else "local_model_requested_help",
            "purpose":"question_only_cloud_consultation","automatic_operation_replay":False}
        # Persist before notification/network preflight so duplicate terminal SSE
        # events cannot open repeated cloud requests or prompts.
        record["cloud_fallback"]={"status":"offered","at":time.time(),**fallback}
        self.app.store.set("localpilot_tasks",tasks)
        prepared=self.prepare_question(record.get("request"),fallback=fallback,
            force_confirmation=capability_hint)
        tasks=self.app.store.get("localpilot_tasks",{})
        tasks[task_id]["cloud_fallback"].update(status=prepared.get("status"),control_id=(prepared.get("control") or {}).get("id"))
        self.app.store.set("localpilot_tasks",tasks)
        return prepared
