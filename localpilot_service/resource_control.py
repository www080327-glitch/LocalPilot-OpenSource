"""Scoped inference resource controls; never tool approval or UNKNOWN resume."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from localpilot_api.service import APIError, TERMINAL
from .security import private_json


class ResourceControl:
    def __init__(self, server):
        self.server=server;self.lock=threading.RLock();self.path=None
        self.state={"epochs":{},"tickets":{}}

    def set_path(self, path):
        self.path=Path(path)
        if self.path.exists():
            value=private_json(self.path)
            if set(value)!={"epochs","tickets"} or not isinstance(value["epochs"],dict) or not isinstance(value["tickets"],dict):
                raise ValueError("Invalid resource control state")
            if any(type(v) is not int or v<0 for v in value["epochs"].values()):
                raise ValueError("Invalid resource epoch")
            self.state=value

    def save(self):
        if self.path:
            temporary=self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.state)+"\n");temporary.chmod(0o600)
            temporary.replace(self.path)

    def epoch(self, principal):
        return self.state["epochs"].get(principal.subject,0)

    @contextmanager
    def creation(self, principal, expected):
        with self.lock:
            if expected is not None and expected!=self.epoch(principal):
                raise APIError("A stop invalidated this pending inference", "client_generation_stale",409)
            yield

    def memory_consent(self, principal, operator, ticket, key, scopes=("memory",)):
        if (not operator.operator or "resource_control" not in operator.scopes or
                principal.subject not in operator.approval_for):
            raise APIError("Bound resource operator required", "resource_control_forbidden",403)
        if not isinstance(ticket,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}",ticket) or not key:
            raise APIError("Memory consent needs a task-bound ticket and key", "resource_ticket_required",400)
        if not scopes or set(scopes)-{"memory","battery"}:raise APIError("Invalid resource grant scope", "resource_scope_mismatch",403)
        scopes=sorted(set(scopes))
        fingerprint=hashlib.sha256((principal.subject+"\0"+key).encode()).hexdigest()
        with self.lock:
            now=time.time()
            self.state["tickets"]={k:v for k,v in self.state["tickets"].items() if v["expires_at"]>now}
            old=self.state["tickets"].get(ticket)
            if old and (old["fingerprint"]!=fingerprint or old.get("scopes",["memory"])!=scopes):
                raise APIError("Resource ticket belongs to another task", "resource_ticket_conflict",409)
            expires=old["expires_at"] if old else now+120
            self.state["tickets"][ticket]={"fingerprint":fingerprint,"expires_at":expires,"scopes":scopes}
            self.save()
        return {"kind":"memory_override" if scopes==["memory"] else "resource_grant","allow_memory_override":"memory" in scopes,"allow_on_battery":"battery" in scopes,"client_subject":principal.subject,"operator_subject":operator.subject,
                "ticket":ticket,"expires_at":expires,"scope":"model_memory_gate_only" if scopes==["memory"] else "model_resource_exceptions_only"}

    def manager(self, task):
        session=self.server.service._session(task.session_id)
        current=getattr(session.runtime.current_backend,"manager",None)
        return current or getattr(self.server,"model_hosts",{}).get(task.model)

    def stop(self, scoped, task_id=None, *, drain=False, submission_id=None):
        scoped._scope("cancel")
        service=self.server.service
        with self.lock, service.condition:
            if task_id:
                scoped._task_access(task_id)
                tasks=[service._task(task_id)]
            else:
                digest=None
                if submission_id:
                    if not isinstance(submission_id,str) or not re.fullmatch(r"[!-~]{1,128}",submission_id):raise APIError("Invalid submission key")
                    namespace=hashlib.sha256((scoped.principal.subject+"\0"+submission_id).encode()).hexdigest()
                    digest=hashlib.sha256(namespace.encode()).hexdigest()
                tasks=[t for t in service.tasks.values() if service._session(t.session_id).owner_subject==scoped.principal.subject
                       and (t.request_key_digest==digest if digest else t.status not in TERMINAL)]
                self.state["epochs"][scoped.principal.subject]=self.epoch(scoped.principal)+1
                self.save()
            managers={self.manager(t) for t in tasks}
            for task in tasks:
                if service._session(task.session_id).owner_subject!=scoped.principal.subject:
                    raise APIError("Resource stop is limited to the calling client", "resource_owner_mismatch",403)
                service.cancel(task.id,drain_response=drain)
            selected={t.id for t in tasks}
            stopped=[];shared=[]
            if not drain:
                for manager in managers-{None}:
                    with manager.lock:
                        other=set(manager.active_tasks)-selected
                    if other:
                        shared.append(manager.status()["model"])
                    else:
                        manager.close(force=True);stopped.append(manager.status()["model"])
            return {"status":"stopping","tasks":[scoped._public(service.task_snapshot(t.id)) if "read" in scoped.principal.scopes else {"id":t.id,"status":t.status} for t in tasks],
                    "client_generation":self.epoch(scoped.principal),"request_bindings":{t.id:t.request_key_digest for t in tasks},"models_stopped":stopped,
                    "shared_models_preserved":shared,"drain_current_response":drain}

    def heartbeat(self, scoped, task_id, ticket):
        scoped._scope("read");scoped._task_access(task_id)
        service=self.server.service;task=service._task(task_id);session=service._session(task.session_id)
        if session.owner_subject!=scoped.principal.subject:
            raise APIError("Only the calling client may maintain its control surface", "resource_owner_mismatch",403)
        if task.service_metadata.get("control_ticket")!=ticket:
            raise APIError("Control ticket mismatch", "resource_ticket_conflict",409)
        manager=self.manager(task)
        if manager:manager.heartbeat(task_id,ticket)
        return {"status":"ok","task_id":task_id}

    def approve_cloud(self, scoped, task_id, action_id):
        scoped._scope("resource_control");scoped._task_access(task_id)
        owner=self.server.service._session(self.server.service._task(task_id).session_id).owner_subject
        if not scoped.principal.operator or owner not in scoped.principal.approval_for:
            raise APIError("Bound resource operator required", "resource_control_forbidden",403)
        task=self.server.service._task(task_id)
        runtime=self.server.service._session(task.session_id).runtime
        if not runtime.pending_approval or runtime.pending_approval.get("kind")!="cloud_egress":
            raise APIError("Resource operator cannot approve a tool", "resource_scope_mismatch",403)
        if getattr(runtime.current_backend,"service_reasoning_only",False) is not True:
            raise APIError("Automatic cloud grant requires reasoning-only route", "resource_scope_mismatch",403)
        result=self.server.service.act(task_id,"approve",action_id)
        self.server.access.audit(operation="resource_cloud_approve",subject=scoped.principal.subject,owner=owner,task_id=task_id,action_id=action_id)
        return scoped._public(result)
