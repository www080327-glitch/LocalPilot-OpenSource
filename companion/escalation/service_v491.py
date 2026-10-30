"""V4.9.1 client over the native Task API, with scoped identity and backoff.

No provider credential, runtime or model-manager endpoints belong here.
"""
import email.utils
import json
import math
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .localpilot import LocalPilotProvider as NativeTransport, TransportFailure, task_view, REASONING_INSTRUCTIONS
from .egress import cloud_context
from .provider import EscalationRequest


class LocalPilotProvider(NativeTransport):
    def __init__(self, config):
        super().__init__(config)
        self.subject = getattr(config, "localpilot_client_subject", "companion")
        self.retry_at = 0.0
        self.failures = 0
        self.network_calls = 0
        self.identity = None
        self.connection = "LOCALPILOT_UNAVAILABLE"
        self.last_route = None
        self.client_generation=0;self.resource_control_version=0
        self.cancelled_submissions=set();self.request_context=threading.local()
        self._state_lock = threading.RLock()

    def connection_state(self):
        with self._state_lock:
            return {"status": self.connection, "client_subject": self.identity,
                    "network_calls": self.network_calls,
                    "retry_after_seconds": max(0, self.retry_at-time.monotonic()),
                    "route_decision": self.last_route}

    def _open(self, path, body=None, *, cloud_approved=False, last_event_id=None, timeout=None):
        headers = self._authorize(cloud_approved)
        with self._state_lock:
            if time.monotonic() < self.retry_at:
                error = TransportFailure("backoff_active", 429)
                error.retry_after = self.retry_at-time.monotonic()
                raise error
            self.network_calls += 1
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        if body and "idempotency_key" in body:
            if body["idempotency_key"] in self.cancelled_submissions:
                raise TransportFailure("client_request_stopped")
            headers["Idempotency-Key"] = body["idempotency_key"]
            headers["X-LocalPilot-Client-Generation"]=str(self.client_generation)
            ticket=getattr(self.request_context,"memory_ticket",None)
            if ticket:
                import os
                credential=os.environ.get(self.config.localpilot_resource_key_env)
                if not credential:raise TransportFailure("resource_control_unconfigured")
                headers["X-LocalPilot-Resource-Consent"]=credential
                headers["X-LocalPilot-Resource-Ticket"]=ticket
                headers["X-LocalPilot-Resource-Scope"]=",".join(getattr(self.request_context,"resource_scopes",["memory"]))
            control=getattr(self.request_context,"control_ticket",None)
            if control:headers["X-LocalPilot-Control-Ticket"]=control
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if body is not None else None
        req = Request(self.origin+path, data=data, headers=headers)
        try:
            response = self.opener.open(req, timeout=self.timeout if timeout is None else timeout)
            with self._state_lock:
                self.failures = 0
            return response
        except HTTPError as exc:
            status = exc.code
            code = {401:"unauthorized", 403:"forbidden", 429:"rate_limited"}.get(status, "http_error")
            retry = exc.headers.get("Retry-After")
            with exc:
                try:
                    candidate = json.loads(exc.read(65537)).get("error", {}).get("code")
                    import re
                    if isinstance(candidate, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", candidate):
                        code = candidate
                except (ValueError, TypeError, AttributeError):
                    pass
            if status == 429 or status >= 500:
                self._backoff(retry)
            if status in {401, 403}:
                self.identity = None
                self.connection = "AUTH_REJECTED"
                self._backoff("60")
            error = TransportFailure(code, status)
            error.retry_after = max(0, self.retry_at-time.monotonic())
            raise error from None
        except (URLError, OSError, ValueError):
            self.connection = "LOCALPILOT_UNAVAILABLE"
            self._backoff(None)
            raise TransportFailure("connection_unavailable") from None

    def _backoff(self, value):
        self.failures += 1
        delay = min(300, 5*2**min(self.failures-1, 6))
        if value:
            try:
                seconds = float(value)
            except ValueError:
                try:
                    seconds = email.utils.parsedate_to_datetime(value).timestamp()-time.time()
                except (ValueError, TypeError, OverflowError):
                    seconds = delay
            if math.isfinite(seconds):
                delay = max(delay, seconds)
        with self._state_lock:
            self.retry_at = max(self.retry_at, time.monotonic()+delay)

    @staticmethod
    def _failure(error, **kwargs):
        return NativeTransport._failure(error, **kwargs) | {
            "retry_after_seconds": getattr(error, "retry_after", 0),
            "connection_state": "AUTH_REJECTED" if error.http_status in {401,403} else "LOCALPILOT_UNAVAILABLE"}

    def health(self, *, cloud_approved=False):
        try:
            health = self._request("/healthz", cloud_approved=cloud_approved)
            from .compatibility import incompatibility
            incompatible = incompatibility(health)
            if incompatible:
                self.identity = None
                self.connection = "INCOMPATIBLE"
                return self._failure(TransportFailure(incompatible, 409)) | {"connection_state":"INCOMPATIBLE", "minimum_compatible_core":"4.9.1rc2", "required_api":"1.0"}
            if (health.get("client_subject") != self.subject or
                    health.get("persistence") is not True or health.get("status") != "ready"):
                self.identity = None
                self.connection = "AUTH_REJECTED"
                return self._failure(TransportFailure("service_identity_mismatch", 403))
            limit=((health.get("compatibility") or {}).get("limits") or {}).get("task_input_json_utf8_bytes",4096)
            if type(limit) is not int or not 512 <= limit <= 1048576:
                return self._failure(TransportFailure("invalid_input_limit_contract",409))
            self.max_input_bytes=min(4096,limit)
            self.identity = self.subject
            self.client_generation=health.get("client_generation",0)
            self.resource_control_version=health.get("resource_control_version",0)
            self.connection = "CONNECTED"
            return {"status":"available", "service":health, "backend_execution":"unknown",
                    "identity_verified":True, "control_authority":False}
        except TransportFailure as exc:
            return self._failure(exc)

    def submit(self, request, approved=False, *, cloud_approved=False, mode="execution", automatic_local=False, memory_ticket=None, resource_scopes=("memory",), control_ticket=None, **kwargs):
        def refused(error):
            return self._failure(error) | {"submission_attempted":False}
        if automatic_local and (not self.local or not self.host_local_only or not getattr(self.config,"localpilot_auto_local",False)):
            return refused(TransportFailure("automatic_local_policy_denied"))
        if mode not in {"execution", "reasoning"}:
            raise ValueError("Invalid delegation mode")
        route = getattr(self.config, "localpilot_analysis_route", "") if mode == "reasoning" else self.route
        if approved is True and not route:
            return refused(TransportFailure("analysis_route_unconfigured"))
        kwargs["route"] = route or self.route
        if approved is not True:
            return super().submit(request, approved=False, **kwargs)
        if not self.host_local_only:
            if not self.allow_cloud:
                return refused(TransportFailure("cloud_disabled"))
            try:
                request = EscalationRequest(**cloud_context(request, cloud_approved))
            except PermissionError:
                return refused(TransportFailure("cloud_approval_required"))
        # Recheck identity before any new context crosses the service boundary.
        health = self.health(cloud_approved=cloud_approved)
        if health.get("status") != "available":
            return health | {"submission_attempted":False}
        try:
            registry = self._request("/localpilot/v1/model-registry", cloud_approved=cloud_approved)
            entry = next((m for m in registry.get("models", []) if m.get("id") == kwargs["route"]), None)
            if not entry or entry.get("adapter") not in {"omlx","local-openai", "deepseek", "deepseek-native","remote-openai"}:
                return refused(TransportFailure("route_policy_unknown"))
            if entry.get('deployment_status','ready')!='ready':return refused(TransportFailure('model_not_deployed',409))
            if mode == "reasoning" and (entry.get("reasoning_only") is not True or entry.get("prompt_profile") not in {"minimal_0", "minimal_1"}):
                return refused(TransportFailure("analysis_route_not_isolated"))
            if not self.host_local_only and entry.get("adapter") not in {"deepseek","deepseek-native"}:
                return refused(TransportFailure("cloud_backend_not_deepseek"))
            if mode=="execution" and (entry.get("prompt_profile")!="standard" or entry.get("reasoning_only") is True):
                return refused(TransportFailure("standard_execution_route_required"))
            if mode=="reasoning" and self.host_local_only:kwargs["instructions"]=REASONING_INSTRUCTIONS
            if self.host_local_only and (entry.get("adapter") not in {"local-openai","omlx"} or entry.get("cloud_egress") != "LOCAL_ONLY"):
                return refused(TransportFailure("host_policy_mismatch"))
            expected=getattr(self.config,"localpilot_expected_local_model","")
            if automatic_local and (entry.get("adapter") not in {"local-openai","omlx"} or entry.get("cloud_egress")!="LOCAL_ONLY" or expected and entry.get("model")!=expected):
                return refused(TransportFailure("automatic_local_model_mismatch"))
            from companion.runtime.power import LowPowerPolicy
            if LowPowerPolicy(self.config).active() and entry.get("adapter") in {"local-openai","omlx"} and not automatic_local:
                return refused(TransportFailure("low_power_local_backend_blocked"))
        except TransportFailure as exc:
            return refused(exc)
        self.request_context.memory_ticket=memory_ticket
        self.request_context.resource_scopes=resource_scopes
        self.request_context.control_ticket=control_ticket
        try:result = super().submit(request, approved=True, cloud_approved=cloud_approved, **kwargs)
        finally:
            self.request_context.memory_ticket=None;self.request_context.control_ticket=None
        result.setdefault("submission_attempted",True)
        task = result.get("task", {})
        if task and task.get("service", {}).get("client_subject") != self.subject:
            return self._failure(TransportFailure("task_owner_mismatch"), mutation=True)
        if task:
            self.last_route = task.get("service", {}).get("route_decision")
        return result

    def status(self, task_id, **kwargs):
        view = super().status(task_id, **kwargs)
        if view.get("task") and view["task"].get("service", {}).get("client_subject") != self.subject:
            return self._failure(TransportFailure("task_owner_mismatch"), task_id=task_id)
        if view.get("task"):
            self.connection = "CONNECTED"
            self.last_route = view["task"].get("service", {}).get("route_decision")
        return view

    def emergency_stop(self, task_id=None, *, drain=False, submission_id=None):
        import os
        from urllib.request import Request
        body={"drain_response":drain}
        if submission_id:body["submission_id"]=submission_id
        if task_id is not None:
            from .localpilot import _identifier
            body["task_id"]=_identifier(task_id)
        try:
            headers=self._authorize(True)
            request=Request(self.origin+"/localpilot/v1/inference/stop",data=json.dumps(body).encode(),headers=headers)
            with self.opener.open(request,timeout=20) as response:
                result=json.load(response)
            self.client_generation=result.get("client_generation",self.client_generation)
            return result
        except Exception as exc:
            return {"status":"stop_unconfirmed","error":{"code":"resource_stop_unconfirmed","http_status":getattr(exc,"code",None)}}

    def approve_cloud_egress(self, task_id, action_id):
        import os
        from .localpilot import _identifier
        credential=os.environ.get(self.config.localpilot_resource_key_env)
        if not credential:return {"status":"unavailable","error":{"code":"resource_control_unconfigured"}}
        try:
            request=Request(self.origin+"/localpilot/v1/tasks/"+_identifier(task_id)+"/cloud/approve",
                data=json.dumps({"action_id":action_id}).encode(),headers={"Authorization":"Bearer "+credential,"Content-Type":"application/json"})
            with self.opener.open(request,timeout=self.timeout) as response:return task_view(json.load(response))
        except Exception as exc:
            return {"status":"unavailable","error":{"code":"cloud_resource_approval_refused","http_status":getattr(exc,"code",None)}}

    def control_heartbeat(self, task_id, ticket):
        try:return self._request("/localpilot/v1/inference/heartbeat",{"task_id":task_id,"ticket_id":ticket},cloud_approved=True)
        except TransportFailure:return {"status":"unavailable"}
