"""Minimal stdlib JSON/SSE client for the local API (no auto retries)."""
import json
import ipaddress
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Local API redirects are unsupported")


class Client:
    def __init__(self, base_url="http://127.0.0.1:8765", *, api_key, control_token=None, timeout=150):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"} or not parsed.hostname
                or not ipaddress.ip_address(parsed.hostname).is_loopback):
            raise ValueError("Client base_url must be an HTTP numeric loopback origin")
        self.base_url = base_url.rstrip("/")
        self.api_key, self.control_token, self.timeout = api_key, control_token, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _request(self, path, body=None, *, method=None, control=False, last_event_id=None):
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        if control and self.control_token:
            headers["X-LocalPilot-Control-Token"] = self.control_token
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        return Request(self.base_url + path, data=data, headers=headers, method=method)

    def request(self, path, body=None, *, method=None, control=False):
        with self.opener.open(self._request(path, body, method=method, control=control), timeout=self.timeout) as result:
            return json.load(result)

    def stream(self, path, body=None, *, last_event_id=None):
        request = self._request(path, body, last_event_id=last_event_id)
        with self.opener.open(request, timeout=self.timeout) as result:
            name, data = None, []
            for raw in result:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data:
                        joined = "\n".join(data)
                        if joined == "[DONE]":
                            return
                        yield {"event": name, "data": json.loads(joined)}
                    name, data = None, []
                elif line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
