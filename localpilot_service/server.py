"""Multi-client facade. All lifecycle and tool work uses the existing TaskService."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
import uuid

from localpilot_api.server import APIServer, Handler
from localpilot_api.service import APIError, TERMINAL
from . import VERSION
from .routing import select_route, routing_contract, validate_preferences


class ScopedService:
    def __init__(self, server, principal, request_id, key=None, decision=None):
        self.server, self.runtime, self.principal = server, server.service, principal
        self.request_id, self.key, self.decision = request_id, key, decision
        self.client_generation=None;self.resource_consent=None;self.control_ticket=None

    def _scope(self, scope):
        if scope not in self.principal.scopes:
            raise APIError("Client scope denied", "scope_forbidden", 403)

    def _session_access(self, sid, control=False):
        owner = self.runtime._session(sid).owner_subject
        allowed = {self.principal.subject}
        if self.principal.operator:
            allowed.update(self.principal.approval_for)
        if owner not in allowed:
            raise APIError("Session not found", "session_not_found", 404)
        if control:
            self._scope("control")

    def _task_access(self, tid, control=False):
        with self.runtime.condition:
            self._session_access(self.runtime._task(tid).session_id, control)

    def _public(self, value):
        value = deepcopy(value)
        reverse = {v:k for k,v in self.principal.routes.items()}
        # Operators may inspect a bound client's public route, never its credentials.
        for p in self.server.access.principals.values():
            if p.subject in self.principal.approval_for:
                reverse.update({v:k for k,v in p.routes.items()})
        if isinstance(value, dict) and "model" in value:
            value["model"] = reverse.get(value["model"], value["model"])
        if isinstance(value,dict) and value.get('object')=='localpilot.session':
            from dataclasses import asdict
            session=self.runtime._session(value['id']);registry=session.runtime.registry
            value['effective_scope']={'workspace':str(registry.workspace_root),'tool_capabilities':asdict(registry.gateway.capabilities),
                'permission_mode':registry.gateway.mode,'tools':[s['function']['name'] for s in registry.schemas()],
                'workspace_grant':(session.desktop_options or {}).get('workspace_grant')}
        if isinstance(value, dict) and value.get("object") == "localpilot.task":
            tools = value.get("tools", [])
            value["receipt_summary"] = {"count": len(tools), "unknown_effects": sum(t.get("side_effect_status") == "unknown" for t in tools)}
            task=self.runtime._task(value["id"])
            session=self.runtime._session(task.session_id)
            value["desktop_options"]=(task.execution_metadata or {}).get('desktop_options',session.desktop_options)
            from .workspaces import verify_operations
            grant=(session.desktop_options or {}).get('workspace_grant')
            if grant:
                try:
                    with self.server.workspace_grants.guard(grant,'inspect_file',{}):
                        value["file_operation_verification"]=verify_operations(tools,session.runtime.workspace)
                except (PermissionError,OSError):value["file_operation_verification"]={"status":"BLOCKED","reason":"folder grant revoked or identity/system access changed; no fresh reads"}
            else:value["file_operation_verification"]=verify_operations(tools,session.runtime.workspace)
            manager=self.server.resources.manager(task)
            if manager:value["model_resource"]={"managed":True,**manager.status()}
            result = value.get("result") or {}
            value["verification_summary"] = {k: result.get(k, "UNKNOWN") for k in
                ("runtime_status", "deliverable_status", "verification_status", "engineering_status", "task_outcome")}
        return value

    def models(self):
        self._scope("read")
        return sorted(self.principal.routes)

    def create_session(self, model="localpilot"):
        self._scope("submit")
        if model not in self.principal.routes:
            raise APIError("Unknown client route", "model_not_registered", 404)
        select_route(self.principal.routes, self.server.catalog, explicit=model)
        with self.runtime.condition:
            return self._public(self.runtime.create_session(self.principal.routes[model], owner_subject=self.principal.subject))

    def create_task(self, request):
        self._scope("submit")
        key = self.key or request.idempotency_key
        if self.key and request.idempotency_key and self.key != request.idempotency_key:
            raise APIError("Conflicting idempotency keys", "idempotency_conflict", 409)
        if not isinstance(key, str) or not re.fullmatch(r"[!-~]{1,128}", key):
            raise APIError("Submissions require Idempotency-Key (1-128 visible ASCII characters)", "idempotency_required", 400)
        if request.model not in self.principal.routes:
            raise APIError("Unknown client route", "model_not_registered", 404)
        namespaced = hashlib.sha256((self.principal.subject + "\0" + key).encode()).hexdigest()
        with self.server.resources.creation(self.principal,self.client_generation), self.runtime.condition:
            if request.session_id:
                self._session_access(request.session_id)
                if self.runtime._session(request.session_id).owner_subject != self.principal.subject:
                    raise APIError("Operators cannot submit into another client's session", "scope_forbidden", 403)
            prior = next((t for t in self.runtime.tasks.values() if t.request_key_digest == hashlib.sha256(namespaced.encode()).hexdigest()), None)
            if prior is None:
                from agent.stabilization import encoded
                try:
                    size = len(encoded(request.input))
                except (UnicodeError, TypeError):
                    raise APIError("Task input must be valid UTF-8 text", "invalid_input_encoding", 400) from None
                if size > 4096:
                    raise APIError("Task input exceeds the 4096-byte JSON UTF-8 contract; split the original question", "task_input_too_large", 413)
            if prior is None and request.session_id:
                session=self.runtime._session(request.session_id)
                configured=(session.desktop_options or {}).get('context_length')
                live=self.server.catalog.get(self.principal.routes[request.model],{}).get('model_state',{}).get('context_budget')
                if type(configured) is int and type(live) is int and live<configured:
                    raise APIError('Model context was reduced; start a new session. Existing history is retained','context_changed',409)
            active = sum(t.status not in TERMINAL for t in self.runtime.tasks.values()
                         if self.runtime._session(t.session_id).owner_subject == self.principal.subject)
            if prior is None and active >= self.principal.max_active_tasks:
                raise APIError("Client active task limit reached", "concurrency_limited", 429)
            request = replace(request, model=self.principal.routes[request.model], idempotency_key=namespaced)
            task = self.runtime.create_task(request, owner_subject=self.principal.subject,
                service_metadata={"request_id": self.request_id, "client_subject": self.principal.subject,
                                  "route_decision": self.decision, "origin_agent":request.origin_agent or self.principal.subject,"parent_task_id":request.parent_task_id,"external_delegation_depth":1,"external_redelegation_allowed":False, **({"control_ticket":self.control_ticket} if self.control_ticket else {}), **({"resource_consent":self.resource_consent} if self.resource_consent else {})})
            self.server.access.audit(request_id=self.request_id, subject=self.principal.subject,
                operation="submit", task_id=task["id"], replay=prior is not None, route=self.decision)
            return self._public(task)

    def session_snapshot(self, sid):
        self._scope("read"); self._session_access(sid)
        return self._public(self.runtime.session_snapshot(sid))

    def task_snapshot(self, tid):
        self._scope("read"); self._task_access(tid)
        return self._public(self.runtime.task_snapshot(tid))

    def wait(self, tid):
        self._task_access(tid)
        return self._public(self.runtime.wait(tid))

    def events(self, tid, after=0, wait_seconds=15):
        self._scope("read"); self._task_access(tid)
        events, task = self.runtime.events(tid, after, wait_seconds)
        return events, self._public(task)

    def cancel(self, tid):
        self._scope("cancel"); self._task_access(tid)
        return self._public(self.runtime.cancel(tid))

    def close_session(self, sid):
        self._scope("cancel"); self._session_access(sid)
        return self._public(self.runtime.close_session(sid))

    def act(self, tid, action, action_id, reason="User rejected the request."):
        self._task_access(tid, True)
        self.server.access.audit(request_id=self.request_id, subject=self.principal.subject,
            operation=action, task_id=tid, action_id=action_id)
        return self._public(self.runtime.act(tid, action, action_id, reason))

    def takeover(self, tid):
        self._task_access(tid, True)
        return self._public(self.runtime.takeover(tid))

    def revoke_computer(self, tid, app):
        self._task_access(tid,True)
        self.server.access.audit(request_id=self.request_id,subject=self.principal.subject,operation='computer_scope_revoke',task_id=tid,app=app)
        return self._public(self.runtime.revoke_computer(tid,app))

    def finalize(self, tid, action_id=None):
        self._task_access(tid, True)
        return self._public(self.runtime.finalize(tid, action_id))

    def children(self, tid):
        self._scope("read"); self._task_access(tid)
        return self.runtime.children(tid)

    def cancel_child(self, tid, wid):
        self._task_access(tid, True)
        return self.runtime.cancel_child(tid, wid)

    def native_recovery(self, sid, action, body, *, principal):
        self._session_access(sid, True)
        return self.runtime.native_recovery(sid, action, body, principal=self.principal.subject)


class ServiceServer(APIServer):
    request_queue_size = 16

    def refresh_models(self, principal):
        """Observe external providers only; never acquire a loading lease."""
        visible = set(principal.routes.values())
        observations, entries, health = {}, {}, []
        for route, backend in getattr(self, 'model_backends', {}).items():
            if route not in visible: continue
            identity = (backend.base_url, backend._api_key)
            if identity not in observations:
                try: observations[identity] = backend.inspect_service()
                except Exception: observations[identity] = {'status':'unavailable', 'models':[], 'evidence_kind':'LIVE_OMLX_READ_ONLY'}
                health.append({k:v for k,v in observations[identity].items() if k!='models'})
            observed = observations[identity]
            models = {m['id']:m for m in observed['models']}
            entries.update(models)
            model = models.get(backend.model)
            self.catalog[route].update(live_health=observed['status'],
                deployment_status='unavailable' if observed['status']!='ready' else
                    'not_deployed' if not model or not model.get('loaded') else model['deployment_status'],
                provenance='live_omlx_discovery_loaded_state',
                model_state=model)
            if model and type(model.get('thinking_default')) is bool:
                default=backend.chat_template_kwargs.get('enable_thinking',model['thinking_default'])
                self.catalog[route].update(reasoning_efforts=['none','high'],thinking_scope='session',
                    default_reasoning_effort='high' if default else 'none',reasoning_toggle={
                        'supported':True,'model':backend.model,'default':bool(default),'source':'omlx_models_status_thinking_default'})
                if 'reasoning' not in self.catalog[route].get('capabilities',[]):self.catalog[route].setdefault('capabilities',[]).append('reasoning')
        return {'health':health, 'models':list(entries.values())}

    def __init__(self, address, service, *, access, catalog=None, max_handlers=32):
        self.access, self.catalog = access, catalog or {}
        from .resource_control import ResourceControl
        self.resources=ResourceControl(self)
        if type(max_handlers) is not int or max_handlers < 1:
            raise ValueError("max_handlers must be positive")
        self.handler_slots = threading.BoundedSemaphore(max_handlers)
        self.handler_leases = set()
        self.handler_lease_lock = threading.Lock()
        super().__init__(address, service, api_key="unused-service-facade-key")
        self.RequestHandlerClass = ServiceHandler
        if any(set(p.routes.values()) - service.routes.keys() for p in access.principals.values()):
            self.server_close()
            raise ValueError("Client route maps refer to unconfigured factories")

    def process_request(self, request, client_address):
        if not self.handler_slots.acquire(blocking=False):
            request.close()
            return
        with self.handler_lease_lock:self.handler_leases.add(request)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.release_handler(request)
            raise

    def release_handler(self, request):
        # Thread.start may be interrupted after the worker already released its slot.
        with self.handler_lease_lock:
            if request not in self.handler_leases:return
            self.handler_leases.remove(request)
            self.handler_slots.release()

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.release_handler(request)


class ServiceHandler(Handler):
    def _json(self, body, status=200):
        self.server.access.audit(request_id=self.request_id,
            subject=getattr(getattr(self, "principal", None), "subject", None),
            operation="http_result", status=status,
            error_code=body["error"].get("code") if isinstance(body, dict) and isinstance(body.get("error"), dict) else None)
        return super()._json(body, status)

    def handle(self):
        self.request_id = "req_" + uuid.uuid4().hex
        self.connection.settimeout(15)
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            pass

    def _control_subject(self):
        return self.principal.subject

    def _service(self):
        return self.scoped

    def _authorize(self, control=False):
        if self.headers.get("Origin"):
            raise APIError("Browser origins are unsupported", "origin_forbidden", 403)
        if control and (not self.principal.operator or "control" not in self.principal.scopes):
            raise APIError("Operator control scope required", "control_forbidden", 403)

    def end_headers(self):
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("X-LocalPilot-Version", VERSION)
        super().end_headers()

    def _body(self, **kwargs):
        body = super()._body(**kwargs)
        path = urlsplit(self.path).path.rstrip("/")
        if path in {"/localpilot/v1/tasks", "/v1/responses", "/v1/chat/completions"}:
            preferences = body.pop("model_preferences", [])
            required = body.pop("required_capabilities", [])
            policy = validate_preferences(body.get('routing_preferences'))
            # A retry can only retrieve its accepted task. Availability changes
            # must not reroute the original idempotency key to another provider.
            key = self.headers.get('Idempotency-Key') or body.get('idempotency_key')
            if key:
                namespaced = hashlib.sha256((self.principal.subject+'\0'+key).encode()).hexdigest()
                digest = hashlib.sha256(namespaced.encode()).hexdigest()
                with self.server.service.condition:
                    prior = next((t for t in self.server.service.tasks.values() if t.request_key_digest==digest),None)
                    if prior:
                        self.scoped._session_access(prior.session_id)
                        public = next((k for k,v in self.principal.routes.items() if v==prior.model),None)
                        if body.get('model', public)!=public:
                            raise APIError('Idempotency route conflict','idempotency_conflict',409)
                        body['model']=public
                        self.scoped.decision=(prior.service_metadata or {}).get('route_decision')
                        return body
            self.server.refresh_models(self.principal)
            explicit = body.get("model")
            session_affinity = False
            if explicit is None:
                options = body.get("localpilot", {})
                conversation = body.get("conversation")
                sid = (body.get("session_id") or
                       (options.get("session_id") if isinstance(options, dict) else None) or
                       (conversation.get("id") if isinstance(conversation, dict) else conversation))
                if not sid and body.get("previous_response_id"):
                    sid = self.scoped.task_snapshot(body["previous_response_id"])["session_id"]
                if sid:
                    with self.server.service.condition:
                        self.scoped._session_access(sid)
                        bound = self.server.service._session(sid).model
                        explicit = next((k for k,v in self.principal.routes.items() if v == bound), None)
                    if explicit is None:
                        raise APIError("Session route is no longer configured", "model_unavailable", 409)
                    session_affinity = True
            public, decision = select_route(self.principal.routes, self.server.catalog,
                explicit=explicit, preferences=preferences, required=required, routing_preferences=policy)
            if session_affinity:
                decision["selection"] = "session_affinity"
                decision['reason']='沿用当前持久会话的模型；来源限制继续生效'
            body["model"] = public
            self.scoped.decision = decision
        return body

    def _dispatch(self):
        self.request_id = "req_" + uuid.uuid4().hex
        self._stream_started = False
        principal, admitted = None, False
        self.close_connection = True
        try:
            if self.headers.get("Origin"):
                raise APIError("Browser origins are unsupported", "origin_forbidden", 403)
            principal = self.server.access.authenticate(self.headers.get("Authorization", ""))
            self.principal = principal
            path = urlsplit(self.path).path.rstrip("/")
            urgent=self.command=="POST" and "cancel" in principal.scopes and (path=="/localpilot/v1/inference/stop" or path.endswith("/cancel-after-response"))
            self.server.access.admit(principal,urgent=urgent); admitted = True
            self.scoped = ScopedService(self.server, principal, self.request_id, self.headers.get("Idempotency-Key"))
            generation=self.headers.get("X-LocalPilot-Client-Generation")
            if generation is not None:
                if not generation.isdigit() or len(generation)>10:raise APIError("Invalid client generation")
                self.scoped.client_generation=int(generation)
            control_ticket=self.headers.get("X-LocalPilot-Control-Ticket")
            if control_ticket:
                if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}",control_ticket):raise APIError("Invalid control ticket")
                self.scoped.control_ticket=control_ticket
            resource=self.headers.get("X-LocalPilot-Resource-Consent")
            if resource:
                if path!="/localpilot/v1/tasks" or self.command!="POST":raise APIError("Resource grant path denied", "resource_scope_mismatch",403)
                operator=self.server.access.authenticate("Bearer "+resource)
                self.scoped.resource_consent=self.server.resources.memory_consent(principal,operator,self.headers.get("X-LocalPilot-Resource-Ticket"),self.headers.get("Idempotency-Key"),self.headers.get("X-LocalPilot-Resource-Scope","memory").split(","))
            if self.command=="POST" and path=="/localpilot/v1/inference/stop":
                body=self._body(allow_empty=True)
                if set(body)-{"task_id","drain_response","submission_id"}:raise APIError("Invalid inference stop body")
                return self._json(self.server.resources.stop(self.scoped,body.get("task_id"),drain=body.get("drain_response") is True,submission_id=body.get("submission_id")))
            if self.command=="POST" and path=="/localpilot/v1/inference/heartbeat":
                body=self._body()
                if set(body)!={"task_id","ticket_id"}:raise APIError("Exact heartbeat binding required")
                return self._json(self.server.resources.heartbeat(self.scoped,body["task_id"],body["ticket_id"]))
            parts=path.split("/")
            if self.command=='POST' and path=='/localpilot/v1/lifecycle/suspend':
                self._authorize(control=True)
                if self._body(allow_empty=True):raise APIError('Suspend body must be empty')
                result=self.server.service.suspend()
                self._json({'status':'suspended','tasks_preserved':True,**result})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if self.command=='POST' and len(parts)==6 and parts[1:4]==['localpilot','v1','tasks'] and parts[5]=='pause':
                self.scoped._scope('cancel');self.scoped._task_access(parts[4])
                if self._body(allow_empty=True):raise APIError('Pause body must be empty')
                return self._json(self.server.service.pause(parts[4]))
            if self.command=='POST' and path=='/localpilot/v1/workspace-grants':
                from .workspaces import handle
                return self._json(handle(self.server,principal,self._body()))
            if self.command=='POST' and path=='/localpilot/v1/desktop-sessions':
                from .desktop_sessions import create
                return self._json(create(self.server,principal,self._body(),self.headers.get("Idempotency-Key")),201)
            if self.command=='POST' and len(parts)==6 and parts[1:4]==['localpilot','v1','desktop-sessions'] and parts[5]=='profile':
                from .desktop_sessions import switch_profile
                return self._json(switch_profile(self.server,principal,parts[4],self._body()))
            if self.command=='POST' and path=='/localpilot/v1/attachments/import':
                from .attachments import ingest
                return self._json(ingest(self.server,principal,self._body()),201)
            if self.command=='POST' and path=='/localpilot/v2/attachments':
                from .documents.api import handle
                return self._json(handle(self.server,principal,self._body()))
            if self.command=='POST' and path=='/model-manager/v1/operations':
                return self._json(self.server.model_resources.operate(principal,self._body(),self.headers.get('Idempotency-Key')))
            if self.command=="POST" and len(parts)==7 and parts[1:4]==["localpilot","v1","tasks"] and parts[5:]==["cloud","approve"]:
                body=self._body()
                if set(body)!={"action_id"}:raise APIError("Exact cloud action ticket required")
                return self._json(self.server.resources.approve_cloud(self.scoped,parts[4],body["action_id"]))
            if self.command == "GET" and path == "/healthz":
                self.scoped._scope("read")
                from .protocol import manifest
                return self._json({"status": "ready" if not self.server.service.closed else "stopping",
                    "version": VERSION, "persistence": self.server.service.store is not None,
                    "compatibility": manifest(),
                    "active_task_count": sum(t.status not in TERMINAL for t in self.server.service.tasks.values()),
                    "model_health": "NOT_PROBED", "client_subject": principal.subject,"client_generation":self.server.resources.epoch(principal),"resource_control_version":1})
            if self.command == "GET" and path == "/localpilot/v1/tasks":
                self.scoped._scope("read")
                with self.server.service.condition:
                    visible = {principal.subject} | (set(principal.approval_for) if principal.operator else set())
                    tasks = [self.scoped._public(self.server.service.task_snapshot(t.id))
                             for t in self.server.service.tasks.values()
                             if self.server.service._session(t.session_id).owner_subject in visible]
                return self._json({"tasks": tasks})
            if self.command == "GET" and path == "/openapi.json":
                self.scoped._scope("read")
                return self._json(json.loads((Path(__file__).parent / "openapi.json").read_text()))
            if self.command == "GET" and path == "/localpilot/v1/model-registry":
                self.scoped._scope("read")
                self.server.refresh_models(principal)
                return self._json({"models": [{"id": k, **self.server.catalog.get(v, {}), **({"local_model_lifecycle":self.server.model_hosts[v].status()} if v in getattr(self.server,"model_hosts",{}) else {"local_model_lifecycle":{'shared_external_service':True,'request_cancel_supported':True,'control_surface_required':True,'release_after_task':False,'minimum_available_bytes':4*1024**3}} if v in getattr(self.server,'model_backends',{}) else {})} for k,v in principal.routes.items()]})
            if self.command == 'GET' and path == '/localpilot/v1/routing-capabilities':
                self.scoped._scope('read')
                return self._json(routing_contract())
            if self.command == 'GET' and path in {'/model-manager/v1/health','/model-manager/v1/models'}:
                self.scoped._scope('read')
                observed = self.server.refresh_models(principal)
                if path.endswith('/health'):
                    return self._json({'status':'ready' if observed['health'] and all(h['status']=='ready' for h in observed['health']) else 'unavailable',
                        'evidence_kind':'LIVE_OMLX_READ_ONLY', 'services':observed['health'],
                        'mutations_supported':False, 'management':'oMLX official admin'})
                return self._json({'models':observed['models']})
            return super()._dispatch()
        except APIError as exc:
            self._json(exc.body(), exc.status)
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            pass
        finally:
            self.server.access.audit(request_id=self.request_id, subject=principal.subject if principal else None,
                operation=self.command, endpoint=urlsplit(self.path).path.split("/")[:4])
            if admitted:
                self.server.access.release(principal)
