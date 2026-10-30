"""Isolated HTTP fixtures. All credentials, platform identities and models are synthetic."""
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from uuid import uuid4
from unittest.mock import patch


def hashed(value):
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


QQ = 'qq.' + hashed('123456789')[:24]
WX = 'wechat.ilink.' + hashed('bot-1')[:24]
QA, QB = ('q_' + hashed(['123456789', peer]) for peer in ('peer-a', 'peer-b'))
WA, WB = ('s_' + hashed(peer) for peer in ('peer-a', 'peer-b'))
ENV = {name: 'FAKE_' + name + '_' + 'x' * 32 for name in ('QIN', 'WIN', 'APPROVE', 'QA', 'QB', 'WA', 'WB', 'OP')}
TOKENS = {ENV[name]: name.lower() for name in ('QA', 'QB', 'WA', 'WB', 'OP')}


def configuration(url):
    def sender(sid, name):
        return {'sender_id': sid, 'subject': name.lower(), 'token_env': name, 'model': 'localpilot'}
    return {'instance_id': 'isolated-test-v1', 'service_url': url, 'channels': [
        {'kind': 'qq', 'channel': QQ, 'ingress_key_env': 'QIN', 'senders': [sender(QA, 'QA'), sender(QB, 'QB')]},
        {'kind': 'wechat', 'channel': WX, 'ingress_key_env': 'WIN', 'senders': [sender(WA, 'WA'), sender(WB, 'WB')],
         'approval': {'key_env': 'APPROVE', 'token_env': 'OP', 'subject': 'op', 'senders': [WA]}},
    ]}


def receipt(name='list_directory', *, reused=False, content='PRIVATE_CONTENT'):
    return {'receipt_id': 'turn:1/call:synthetic/entry:0', 'name': name, 'receipt_reused': reused,
            'arguments': content, 'payload': {'ok': True, 'result': {'status': 'ok', 'content': content}},
            'read_receipt': None, 'side_effect_status': 'completed'}


def snapshot(subject, state='completed', session=None):
    return {'id': 'resp_' + uuid4().hex, 'session_id': session or 'sess_' + uuid4().hex,
            'object': 'localpilot.task', 'status': state, 'quiescent': state not in {'running', 'queued'},
            'service': {'client_subject': subject}, 'tools': [receipt()],
            'required_action': None, 'result': {'text': 'files: marker.txt'}, 'recovery': None}


class FakeOfficial:
    def __init__(self):
        self.tasks, self.keys, self.posts, self.gets, self.decisions = {}, {}, [], [], []
        self.failure, self.drop_submit, self.drop_decision, self.task_failure, self.health_subject = None, False, False, None, None
        self.submit_delay = self.query_delay = 0
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def respond(self, code, data):
                raw = json.dumps(data).encode()
                try:
                    self.send_response(code)
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

            def dispatch(self, body=None):
                subject = TOKENS.get(self.headers.get('Authorization', '').removeprefix('Bearer '))
                if subject is None:
                    return self.respond(401, {})
                if self.path == '/healthz':
                    return self.respond(200, {'client_subject': fixture.health_subject or subject, 'persistence': True,
                                              'compatibility': {'agent_service_api': '1.0'}})
                if self.path == '/localpilot/v1/tasks':
                    fixture.posts.append((subject, self.headers.get('Idempotency-Key'), deepcopy(body)))
                    if fixture.failure:
                        return self.respond(fixture.failure, {'error': {'message': 'PRIVATE_CONTENT'}})
                    if subject == 'op':
                        return self.respond(403, {})
                    key = (subject, self.headers.get('Idempotency-Key'))
                    if not key[1]:
                        return self.respond(400, {})
                    if key in fixture.keys:
                        prior, old = fixture.keys[key]
                        return self.respond(202 if old == body else 409, prior if old == body else {})
                    state = 'requires_approval' if 'approval' in body['input'] or 'reject' in body['input'] else 'completed'
                    task = snapshot(subject, state, body.get('session_id'))
                    if state == 'requires_approval':
                        task['tools'] = []
                        task['required_action'] = {'id': 'approval_' + uuid4().hex, 'requests': [{'name': 'apply_patch'}]}
                    fixture.keys[key] = task, deepcopy(body)
                    fixture.tasks[task['id']] = task
                    if fixture.drop_submit:
                        return self.connection.shutdown(2)
                    time.sleep(fixture.submit_delay)
                    return self.respond(202, task)
                parts = self.path.split('/')
                task = fixture.tasks.get(parts[4] if len(parts) > 4 else '')
                if not task or (task['service']['client_subject'] != subject and not (subject == 'op' and task['service']['client_subject'] == 'wa')):
                    return self.respond(404, {})
                if len(parts) == 5:
                    fixture.gets.append(task['id'])
                    time.sleep(fixture.query_delay)
                    if fixture.task_failure:
                        return self.respond(fixture.task_failure, {})
                    return self.respond(200, task)
                if subject != 'op':
                    return self.respond(403, {})
                if task['status'] != 'requires_approval' or body['action_id'] != task['required_action']['id']:
                    return self.respond(409, {})
                fixture.decisions.append((task['id'], parts[-1], body['action_id']))
                task.update(status='completed' if parts[-1] == 'approve' else 'incomplete', required_action=None,
                            tools=[receipt('apply_patch')] if parts[-1] == 'approve' else [], quiescent=True,
                            result={'text': 'approved' if parts[-1] == 'approve' else 'rejected'})
                if fixture.drop_decision:
                    return self.connection.shutdown(2)
                return self.respond(202, task)

            def do_GET(self):
                self.dispatch()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                self.dispatch(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()


class RealOfficial:
    """Unmodified official HTTP server/SQLite/Registry; scripted model and temporary workspace."""
    def __init__(self, root):
        from agent.registry import create_default_registry
        from agent.retry import RetryPolicy
        from agent.session import AgentSession
        from localpilot_api.service import TaskService
        from localpilot_service.security import AccessPolicy, Principal
        from localpilot_service.server import ServiceServer
        from tests.test_runtime_api import Backend, answer, call
        self.root = Path(root)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'marker.txt').write_text('PRIVATE_CONTENT', encoding='utf-8')
        self.executions = []
        self.file_locks = patch('agent.file_locks.LOCK_DIRECTORY', self.root / 'file-locks')
        self.file_locks.start()
        fixture = self

        class Model(Backend):
            def request(self, messages, **kwargs):
                # Backend.request is used only by synchronous fallbacks; streaming delegates here.
                last = next((m.content for m in reversed(messages) if m.role == 'user'), '')
                tail = messages[-1]
                if tail.role == 'tool':
                    result = json.loads(tail.content)
                    if result.get('ok') and isinstance(result.get('result'), list):
                        return answer('files: ' + ', '.join(result['result']))
                    return answer('approved' if result.get('ok') else 'rejected')
                if 'approval' in last or 'reject' in last:
                    target = 'approved.txt' if 'approval' in last else 'rejected.txt'
                    return answer(None, call('apply_patch', {'changes': [{'path': target, 'operation': 'create', 'content': 'OK'}]}, 'write-' + uuid4().hex))
                return answer(None, call('list_directory', {'path': '.'}, 'read-' + uuid4().hex))

        # Reuse the official scripted backend's response/stream implementation.
        def factory(callback):
            registry = create_default_registry(self.workspace, permission_mode='approve-mutations')
            original = registry._tools['list_directory']
            def listed(*, workspace_root, path='.'):
                fixture.executions.append('list_directory')
                return original(workspace_root=workspace_root, path=path)
            registry._tools['list_directory'] = listed
            return AgentSession(registry, backend=Model(), policy='cloud-only', event_callback=callback,
                                retry_policy=RetryPolicy(max_attempts=1))

        self.factory, self.TaskService, self.ServiceServer = factory, TaskService, ServiceServer
        self.access = AccessPolicy([Principal(name.lower(), ENV[name], scopes=frozenset({'read', 'submit'}))
                                    for name in ('QA', 'QB', 'WA', 'WB')] + [
            Principal('op', ENV['OP'], scopes=frozenset({'read', 'control'}), operator=True, approval_for=('wa',))])
        self.start()

    def start(self, port=0):
        self.service = self.TaskService({'localpilot': self.factory}, persistence=self.root / 'runtime.sqlite3')
        self.server = self.ServiceServer(('127.0.0.1', port), self.service, access=self.access)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def stop(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()
        self.service.suspend()

    def close(self):
        try:
            self.stop()
            self.access.close()
        finally:
            self.file_locks.stop()
