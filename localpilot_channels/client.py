"""Bounded loopback HTTP client. No proxy, redirects, automatic retries or model calls."""
import http.client
import json
import re
from urllib.parse import urlsplit


class ChannelError(Exception):
    def __init__(self, code, status=502, *, uncertain=None):
        super().__init__(code)
        self.code, self.status = code, status
        self.uncertain = status >= 500 if uncertain is None else uncertain


class ServiceClient:
    def __init__(self, origin, token, subject, *, timeout=10):
        url = urlsplit(origin)
        if (url.scheme != 'http' or url.hostname not in {'127.0.0.1', '::1'}
                or url.path not in {'', '/'} or url.username or url.password or url.query or url.fragment):
            raise ValueError('service_requires_loopback_origin')
        if not isinstance(token, str) or not re.fullmatch(r'[!-~]{24,4096}', token):
            raise ValueError('invalid_service_credential')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', subject) or not 0 < timeout <= 120:
            raise ValueError('invalid_service_identity_or_timeout')
        self.host, self.port = url.hostname, url.port or 80
        self.token, self.subject, self.timeout = token, subject, timeout

    def request(self, method, path, body=None, *, key=None):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('invalid_service_path')
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        if key is not None:
            headers['Idempotency-Key'] = key
        try:
            conn.request(method, path, None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers)
            response = conn.getresponse()
            raw = response.read(4_000_001)
            if response.status != 200 and not (method == 'POST' and response.status == 202):
                if response.status in {401, 403}:
                    raise ChannelError('service_auth_failed' if response.status == 401 else 'service_permission_denied', response.status)
                if response.status in {400, 404, 409, 413, 429, 503}:
                    # Never forward arbitrary server error bodies or error messages.
                    raise ChannelError('service_http_' + str(response.status), response.status)
                raise ChannelError('service_outcome_unknown', 504)
            if len(raw) > 4_000_000:
                raise ChannelError('service_outcome_unknown', 504)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except ChannelError:
            raise
        except (OSError, http.client.HTTPException, ValueError, RecursionError):
            raise ChannelError('service_outcome_unknown', 504) from None
        finally:
            conn.close()

    def identity(self):
        health = self.request('GET', '/healthz')
        if (health.get('client_subject') != self.subject or health.get('persistence') is not True
                or health.get('compatibility', {}).get('agent_service_api') != '1.0'):
            raise ChannelError('service_identity_or_contract_mismatch', 403)

    def submit(self, body, key):
        self.identity()
        return self.request('POST', '/localpilot/v1/tasks', body, key=key)

    def task(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r'resp_[a-f0-9]{32}', task_id):
            raise ValueError('invalid_official_task_id')
        return self.request('GET', '/localpilot/v1/tasks/' + task_id)

    def decide(self, task_id, action, action_id, reason):
        if (action not in {'approve', 'reject'} or not re.fullmatch(r'resp_[a-f0-9]{32}', task_id)
                or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,128}', action_id)):
            raise ValueError('invalid_official_decision')
        self.identity()
        return self.request('POST', '/localpilot/v1/tasks/' + task_id + '/' + action,
                            {'action_id': action_id, 'reason': reason})
