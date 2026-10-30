"""Authenticated channel ingress only. No models, tools or platform gateway connections."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import os
import threading

from .client import ChannelError


def make_server(adapter, *, port=8003):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_args):
            pass

        def send_json(self, status, data):
            raw = json.dumps(adapter.redact(data), ensure_ascii=True).encode('ascii')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                if self.path != '/healthz' or self.headers.get('Origin'):
                    raise ChannelError('not_found', 404)
                adapter.authenticate(self.headers.get('Authorization', ''))
                self.send_json(200, {'status': 'ready', 'component': 'localpilot_channels',
                                    'instance_id': adapter.namespace, 'pid': os.getpid()})
            except ChannelError as exc:
                self.send_json(exc.status, {'status': 'error', 'error': {'code': exc.code}})

        def do_POST(self):
            try:
                if self.headers.get('Origin'):
                    raise ChannelError('browser_origin_forbidden', 403)
                channel = adapter.authenticate(self.headers.get('Authorization', ''), self.path == '/tasks/decision')
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                    raise ChannelError('invalid_framing', 400)
                try:
                    size = int(self.headers.get('Content-Length', ''))
                    if not 0 < size <= 32000:
                        raise ValueError()
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError()
                    body = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    raise ChannelError('invalid_json_or_body_size', 400) from None
                self.send_json(*adapter.dispatch(self.path, body, channel))
            except ChannelError as exc:
                self.send_json(exc.status, {'status': 'unknown' if exc.uncertain else 'error', 'error': {'code': exc.code}})
            except (sqlite3.Error, OSError, ValueError):
                self.send_json(503, {'status': 'unknown', 'error': {'code': 'channel_state_or_audit_write_failed'}})
            except Exception:
                self.send_json(500, {'status': 'unknown', 'error': {'code': 'channel_outcome_unknown'}})

    class Server(ThreadingHTTPServer):
        daemon_threads = False  # Persist bounded in-flight requests before closing SQLite.

        def __init__(self, *args, **kwargs):
            self.admission = threading.BoundedSemaphore(16)
            super().__init__(*args, **kwargs)

        def process_request(self, request, client_address):
            if not self.admission.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except Exception:
                self.admission.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.admission.release()

        def handle_error(self, *_args):
            pass

    return Server(('127.0.0.1', port), Handler)
