"""Small dependency-free loopback HTTP server. No model/Agent logic in handlers."""
import hmac
import ipaddress
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .openai_adapter import chat_completion, parse_request, response, stream_events
from .service import APIError, SETTLED, TaskRequest


class APIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service, *, api_key, control_token=None, max_body_bytes=1048576,
                 control_subject="trusted-host-control"):
        if not ipaddress.ip_address(address[0]).is_loopback:
            raise ValueError("API server currently supports numeric loopback binding only")
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("A nonempty API key is required")
        if control_token is not None and (not isinstance(control_token, str) or not control_token or control_token == api_key):
            raise ValueError("Host control token must be nonempty and different from the API key")
        self.service, self.api_key, self.control_token = service, api_key, control_token
        if not isinstance(control_subject, str) or not control_subject or len(control_subject) > 128:
            raise ValueError("Host control subject must be bounded nonempty text")
        self.control_subject = control_subject  # Host-configured credential principal; never request data.
        self.max_body_bytes = max_body_bytes
        if ipaddress.ip_address(address[0]).version == 6:
            self.address_family = socket.AF_INET6
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass  # No user input, UI evidence or credentials in access logs.

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def _service(self):
        return self.server.service

    def _control_subject(self):
        return self.server.control_subject

    def _authorize(self, control=False):
        # No browser origins/CORS on this privileged local endpoint.
        if self.headers.get("Origin"):
            raise APIError("Browser origins are unsupported", "origin_forbidden", 403)
        expected = self.server.control_token if control else "Bearer " + self.server.api_key
        actual = self.headers.get("X-LocalPilot-Control-Token") if control else self.headers.get("Authorization", "")
        if not expected or not actual or not hmac.compare_digest(expected.encode(), actual.encode()):
            raise APIError("Host control authorization required" if control else "Invalid API key",
                           "control_forbidden" if control else "unauthorized", 403 if control else 401)

    def _body(self, *, allow_empty=False):
        if self.headers.get("Transfer-Encoding"):
            raise APIError("Chunked request bodies are unsupported")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise APIError("Content-Length required", "length_required", 411) from None
        # Official SDK responses.cancel() sends POST with Content-Length: 0.
        # Permit this only for the bodyless cancel operation, never task input.
        if allow_empty and length == 0:
            return {}
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            raise APIError("Content-Type must be application/json", "unsupported_media_type", 415)
        if not 0 < length <= self.server.max_body_bytes:
            raise APIError("Request body exceeds limit or is empty", "body_too_large", 413)
        self.connection.settimeout(10)
        raw = self.rfile.read(length)
        self.connection.settimeout(None)
        if len(raw) != length:
            raise APIError("Incomplete request body")
        try:
            body = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON number")))
        except (ValueError, UnicodeError):
            raise APIError("Invalid JSON body") from None
        if not isinstance(body, dict):
            raise APIError("Request must be a JSON object")
        return body

    def _json(self, body, status=200):
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _sse(self, events):
        self._stream_started = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(30)  # A slow/disconnected reader cannot block Runtime callbacks.
        for name, body in events:
            if body is None:
                frame = ": heartbeat\n\n"
            else:
                data = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, allow_nan=False)
                event_id = f'id: {body["sequence"]}\n' if isinstance(body, dict) and "sequence" in body else ""
                frame = event_id + (f"event: {name}\n" if name else "") + f"data: {data}\n\n"
            self.wfile.write(frame.encode())
            self.wfile.flush()

    def _native_events(self, task_id, after):
        while True:
            events, task = self._service().events(task_id, after)
            for event in events:
                after = event["sequence"]
                yield event["type"], event
            if task["status"] in SETTLED and task["quiescent"]:
                return
            if not events:
                yield None, None

    def _dispatch(self):
        self._stream_started = False
        try:
            self._authorize()
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/")
            query = parse_qs(parsed.query)
            service = self._service()
            if self.command == "GET" and path == "/v1/models":
                return self._json({"object": "list", "data": [{"id": model, "object": "model", "created": 0, "owned_by": "localpilot"} for model in service.models()]})
            if self.command == "POST" and path in {"/v1/responses", "/v1/chat/completions"}:
                body = self._body()
                protocol = "responses" if path == "/v1/responses" else "chat"
                task = service.create_task(parse_request(body, protocol, service))
                if body.get("stream", False):
                    return self._sse(stream_events(service, task["id"], protocol,
                        include_usage=body.get("stream_options", {}).get("include_usage", False)))
                if not body.get("background", False):
                    task = service.wait(task["id"])
                return self._json(response(task) if protocol == "responses" else chat_completion(task))
            parts = path.split("/")
            if len(parts) == 4 and parts[1:3] == ["v1", "responses"] and self.command == "GET":
                return self._json(response(service.task_snapshot(parts[3])))
            if len(parts) == 5 and parts[1:3] == ["v1", "responses"] and parts[4] == "cancel" and self.command == "POST":
                body = self._body(allow_empty=True)
                if body:
                    raise APIError("cancel body must be {}")
                return self._json(response(service.cancel(parts[3])))
            root = "/localpilot/v1"
            if path == root + "/sessions" and self.command == "POST":
                body = self._body()
                if set(body) - {"model"}:
                    raise APIError("Session creation accepts only model")
                return self._json(service.create_session(body.get("model", "localpilot")), 201)
            if path == root + "/tasks" and self.command == "POST":
                body = self._body()
                if set(body) - {"input", "model", "session_id", "instructions", "timeout_seconds", "max_output_tokens", "idempotency_key", "routing_preferences", "reasoning_effort", "origin_agent", "parent_task_id", "low_power_consent"}:
                    raise APIError("Unsupported task parameters")
                if "input" not in body:
                    raise APIError("input is required")
                return self._json(service.create_task(TaskRequest(**body)), 202)
            if path.startswith(root + "/"):
                tail = path[len(root) + 1:].split("/")
                if len(tail) in {4, 5} and tail[0] == "sessions" and tail[2:4] == ["computer", "recovery"]:
                    self._authorize(control=True)
                    action = tail[4] if len(tail) == 5 else "inspect"
                    if self.command == "GET" and action == "inspect":
                        if set(query) != {"app"} or len(query["app"]) != 1:
                            raise APIError("Specify one app")
                        return self._json(service.native_recovery(tail[1], action, {"app": query["app"][0]},
                            principal=self._control_subject()))
                    if self.command == "POST" and action in {"request", "authorize", "revalidate", "reject"}:
                        return self._json(service.native_recovery(tail[1], action, self._body(),
                            principal=self._control_subject()))
                    raise APIError("Recovery endpoint not found", "not_found", 404)
                if len(tail) == 2 and tail[0] == "sessions":
                    if self.command == "GET":
                        return self._json(service.session_snapshot(tail[1]))
                    if self.command == "DELETE":
                        return self._json(service.close_session(tail[1]))
                if len(tail) >= 2 and tail[0] == "tasks":
                    task_id = tail[1]
                    if len(tail) == 2 and self.command == "GET":
                        return self._json(service.task_snapshot(task_id))
                    if len(tail) == 3 and tail[2] == 'children' and self.command == 'GET':
                        return self._json(service.children(task_id))
                    if len(tail) == 5 and tail[2] == 'children' and tail[4] == 'cancel' and self.command == 'POST':
                        self._authorize(control=True)
                        if self._body():
                            raise APIError('child cancel body must be {}')
                        return self._json(service.cancel_child(task_id, tail[3]))
                    if len(tail) == 3 and tail[2] == "events" and self.command == "GET":
                        raw_cursor = query.get("after", [self.headers.get("Last-Event-ID", "0")])
                        if len(raw_cursor) != 1:
                            raise APIError("Specify one after cursor")
                        try:
                            cursor = int(raw_cursor[0])
                        except ValueError:
                            raise APIError("Invalid event cursor") from None
                        service.events(task_id, cursor, wait_seconds=0)  # Validate before sending 200.
                        return self._sse(self._native_events(task_id, cursor))
                    if self.command == "POST" and len(tail) >= 3:
                        action = "/".join(tail[2:])
                        if action in {"approve", "reject", "continue", "finalize", "computer/resume", "computer/takeover", "computer/revoke"}:
                            self._authorize(control=True)
                        body = self._body()
                        if action == 'finalize':
                            if set(body) - {'action_id'} or body.get('action_id') is not None and not isinstance(body['action_id'], str):
                                raise APIError('finalize accepts optional action_id')
                            return self._json(service.finalize(task_id, body.get('action_id')), 202)
                        if action == "cancel":
                            if body:
                                raise APIError("cancel body must be {}")
                            return self._json(service.cancel(task_id))
                        if action == "computer/revoke":
                            if set(body)!={'app'} or not isinstance(body['app'],str):
                                raise APIError('revoke accepts one exact app')
                            return self._json(service.revoke_computer(task_id,body['app']))
                        if action == "computer/takeover":
                            if body:
                                raise APIError("takeover body must be {}")
                            return self._json(service.takeover(task_id))
                        if action in {"approve", "reject", "continue", "computer/resume"}:
                            if set(body) - {"action_id", "reason"} or not isinstance(body.get("action_id"), str) or not isinstance(body.get("reason", ""), str):
                                raise APIError("Host action requires action_id and optional text reason")
                            return self._json(service.act(task_id, "resume" if action == "computer/resume" else action,
                                body["action_id"], body.get("reason", "User rejected the request.")), 202)
            raise APIError("Endpoint not found", "not_found", 404)
        except APIError as exc:
            self.close_connection = True  # Reject unread POST data safely.
            if self._stream_started:
                self.wfile.write(("event: error\ndata: " + json.dumps(exc.body()) + "\n\n").encode())
                self.wfile.flush()
            else:
                self._json(exc.body(), exc.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # Disconnect detaches only; explicit cancellation controls the task.
            self.close_connection = True
        except Exception:
            self.close_connection = True
            error = APIError("Internal server error", "server_error", 500).body()
            if self._stream_started:
                self.wfile.write(("event: error\ndata: " + json.dumps(error) + "\n\n").encode())
                self.wfile.flush()
            else:
                self._json(error, 500)
