"""Independent JSON/SSE HTTP protocol faults, scoped authentication and drift."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agent.registry import create_default_registry
from localpilot_plugins.adapter import attach
from localpilot_plugins.manager import PluginManager, tool_name
from localpilot_plugins.security import digest


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.state = {'bearer': 'PUBLIC-TEST-BEARER-12345', 'version': '1', 'sse': False,
                      'description': 'echo', 'calls': 0, 'headers': [], 'huge': False}
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(405)
                self.end_headers()

            def do_DELETE(self):
                self.send_response(200)
                self.end_headers()

            def do_POST(self):
                state['headers'].append({k.lower(): v for k, v in self.headers.items() if k.lower() != 'authorization'})
                if self.headers.get('Authorization') != 'Bearer ' + state['bearer']:
                    self.send_response(401)
                    self.end_headers()
                    return
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if 'id' not in request:
                    self.send_response(202)
                    self.end_headers()
                    return
                method = request['method']
                if method == 'initialize':
                    result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                              'serverInfo': {'name': 'http-fixture', 'version': state['version']}}
                elif method == 'tools/list':
                    result = {'tools': [{'name': 'echo', 'description': state['description'],
                        'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}]}
                elif method == 'tools/call':
                    state['calls'] += 1
                    result = {'content': [{'type': 'text', 'text': 'x' * 2097152 if state['huge'] else request['params']['arguments']['text']}], 'isError': False}
                else:
                    result = {}
                data = json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream' if state['sse'] else 'application/json')
                if method == 'initialize':
                    self.send_header('Mcp-Session-Id', 'public-test-session')
                if state['sse']:
                    data = b'id: public-event\nevent: message\ndata: ' + data + b'\n\n'
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.daemon_threads = True
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.manager = PluginManager(self.root / 'plugins')
        self.manager.credential('test-key', self.state['bearer'])
        self.manager.add({'id': 'http', 'transport': 'streamable-http',
            'url': 'http://127.0.0.1:' + str(self.http.server_port) + '/mcp', 'bearer_credential': 'test-key', 'timeout': 3})
        discovered = self.manager.discover('http', source_reviewed=True, license_id='MIT-test-fixture')
        self.manager.review('http', discovered['catalog_sha256'], {'tools': {'echo': {'effect': 'observation', 'summary': 'Echo public data'}},
            'resources': [], 'prompts': [], 'plugin_egress': 'allow', 'network_access': True, 'scope': 'Synthetic loopback test only', 'allow_agent': True})
        self.manager.enable('http')
        self.registry = create_default_registry(self.workspace, permission_mode='approve-all')
        attach(self.registry, self.manager.home)

    def tearDown(self):
        self.registry.plugin_manager.close()
        self.manager.close()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def invoke(self):
        return self.registry.call(tool_name('http', 'tool', 'echo'), {'text': 'public'}, approved=True)

    def test_json_sse_session_and_protocol_headers(self):
        self.assertEqual(self.invoke()['status'], 'ok')
        self.state['sse'] = True
        self.assertEqual(self.invoke()['status'], 'ok')
        self.assertEqual(self.state['calls'], 2)
        headers = self.state['headers'][-1]
        self.assertEqual(headers['mcp-protocol-version'], '2025-11-25')
        self.assertEqual(headers['mcp-session-id'], 'public-test-session')
        self.assertIn('application/json', headers['accept'])
        self.assertIn('text/event-stream', headers['accept'])

    def test_catalog_drift_blocks_dispatch_then_version_change_requires_review(self):
        self.assertEqual(self.invoke()['status'], 'ok')
        self.state['description'] = 'New malicious capabilities'
        self.assertEqual(self.invoke()['status'], 'blocked')
        self.assertEqual(self.state['calls'], 1)
        self.state['description'] = 'echo'
        self.state['version'] = '2'
        self.registry.plugin_manager.close()
        self.assertNotEqual(self.invoke()['status'], 'ok')
        self.assertEqual(self.state['calls'], 1)

    def test_auth_expiry_and_native_rotation_no_secret_leak(self):
        self.assertEqual(self.invoke()['status'], 'ok')
        self.state['bearer'] = 'PUBLIC-ROTATED-CREDENTIAL-67890'
        rejected = self.invoke()
        self.assertEqual(rejected['status'], 'error')
        self.assertEqual(self.state['calls'], 1)
        self.assertNotIn('CREDENTIAL', json.dumps(rejected))
        self.manager.credential('test-key', self.state['bearer'])
        self.assertEqual(self.invoke()['status'], 'ok')

    def test_oversized_http_is_contained(self):
        self.state['huge'] = True
        result = self.invoke()
        self.assertEqual(result['status'], 'error')
        self.assertLess(len(json.dumps(result)), 64000)
        self.state['huge'] = False
        self.assertEqual(self.invoke()['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
