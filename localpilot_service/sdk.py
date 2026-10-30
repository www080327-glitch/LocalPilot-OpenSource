"""Portable standard-library SDK; explicit keys make retries reviewable."""
import ipaddress
import json
from urllib.parse import urlsplit, quote
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Agent service redirects are forbidden")


class Client:
    def __init__(self, base_url="http://127.0.0.1:8765", *, token, timeout=30):
        p = urlsplit(base_url)
        try:
            loopback = ipaddress.ip_address(p.hostname).is_loopback
        except ValueError:
            loopback = False
        if (p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password or
                p.path not in {"", "/"} or p.query or p.fragment or (p.scheme == "http" and not loopback)):
            raise ValueError("Use loopback HTTP or authenticated HTTPS origin")
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, path, body=None, method=None, key=None, after=None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("API path must be relative to configured origin")
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        if key is not None:
            headers["Idempotency-Key"] = key
            if getattr(self,"control_ticket",None):headers["X-LocalPilot-Control-Ticket"]=self.control_ticket
            if getattr(self,"client_generation",None) is not None:headers["X-LocalPilot-Client-Generation"]=str(self.client_generation)
        if after is not None:
            headers["Last-Event-ID"] = str(after)
        return Request(self.base_url + path, data=None if body is None else json.dumps(body, allow_nan=False).encode(), headers=headers, method=method)

    def request(self, path, body=None, *, method=None, key=None):
        with self.opener.open(self._request(path, body, method, key), timeout=self.timeout) as response:
            return json.load(response)

    def submit(self, input, *, idempotency_key, **options):
        return self.request("/localpilot/v1/tasks", {"input": input, **options}, key=idempotency_key)

    def status(self, task_id):
        return self.request("/localpilot/v1/tasks/" + quote(task_id, safe=""))

    def continue_task(self, task_id, action_id, *, action="continue"):
        if action not in {"continue", "approve", "reject", "computer/resume"}:
            raise ValueError("Unknown continuation action")
        return self.request("/localpilot/v1/tasks/" + quote(task_id, safe="") + "/" + action, {"action_id": action_id})

    def cancel(self, task_id):
        return self.request("/localpilot/v1/tasks/" + quote(task_id, safe="") + "/cancel", {})

    def events(self, task_id, *, after=0):
        with self.opener.open(self._request("/localpilot/v1/tasks/" + quote(task_id, safe="") + "/events", after=after), timeout=self.timeout) as response:
            event, data = None, []
            for line in response:
                line = line.decode().rstrip("\r\n")
                if not line:
                    if data:
                        yield {"event": event, "data": json.loads("\n".join(data))}
                    event, data = None, []
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
