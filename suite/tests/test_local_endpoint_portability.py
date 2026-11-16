"""Local endpoint setup against real HTTP and independently managed service processes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from localpilot_service.security import private_json
from localpilot_suite.product_control import dispatch


ROOT = Path(__file__).resolve().parents[2]


class LocalEndpointDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.seen = []
        self.response = {'data': [{'id': 'cpu-model-b'}, {'id': 'cpu-model-a'}, {'id': 'cpu-model-a'}]}
        self.http_status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.seen.append(self.path)
                self.send_response(owner.http_status)
                if owner.http_status == 302:
                    self.send_header('Location', '/unexpected')
                self.end_headers()
                self.wfile.write(json.dumps(owner.response).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.02))
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/v1'

    def command(self, operation, args):
        return dispatch(self.home, {'version': 1, 'operation': operation, 'args': args})

    def test_first_run_catalog_and_discovery_do_not_initialize_or_infer(self):
        self.assertFalse(self.command('model_configuration', {})['configured'])
        result = self.command('discover_local_endpoint', {'base_url': self.endpoint})
        self.assertEqual(result['models'], [{'id': 'cpu-model-a'}, {'id': 'cpu-model-b'}])
        self.assertEqual(result['inference'], 'NOT_RUN')
        self.assertEqual(result['context_budget'], 'USER_REQUIRED')
        self.assertEqual(self.seen, ['/v1/models'])
        self.assertFalse(self.home.exists())

    def test_invalid_models_and_redirect_are_reported_without_inference(self):
        for payload in [[], {'data': [{}]}, {'data': [{'id': 42}]}, {'models': ['cpu-model']}]:
            self.response = payload
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, 'model catalog'):
                self.command('discover_local_endpoint', {'base_url': self.endpoint})
        self.http_status = 302
        with self.assertRaisesRegex(ValueError, 'HTTP 302'):
            self.command('discover_local_endpoint', {'base_url': self.endpoint})
        self.assertEqual(self.seen, ['/v1/models'] * 5)

    def test_wrong_urls_are_rejected_before_network_or_files(self):
        for url in ['http://example.test:8080/v1', 'http://127.0.0.1:0/v1',
                    'http://user:secret@127.0.0.1:8080/v1', self.endpoint + '?key=secret']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.command('discover_local_endpoint', {'base_url': url})
        self.assertEqual(self.seen, [])
        self.assertFalse(self.home.exists())

    def test_pasted_server_origin_is_normalized_before_catalog_request(self):
        for value in [self.endpoint.removesuffix('/v1'), self.endpoint.removesuffix('v1'),
                      '  ' + self.endpoint + '/  ']:
            result = self.command('discover_local_endpoint', {'base_url': value})
            self.assertEqual(result['models'][0]['id'], 'cpu-model-a')
        self.assertEqual(self.seen, ['/v1/models'] * 3)

    def test_default_http_port_is_a_valid_local_endpoint(self):
        from localpilot_suite.model_configuration import local_endpoint_url
        self.assertEqual(local_endpoint_url('http://localhost'), 'http://127.0.0.1:80/v1')
        self.assertEqual(local_endpoint_url('http://[::1]/v1/'), 'http://[::1]:80/v1')


@unittest.skipUnless(platform.system() == 'Linux', 'real detached lifecycle test runs on Linux')
class PortableSetupProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.workspace = self.root / 'workspace'
        self.env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / 'suite')]))
        self.env.pop('LOCALPILOT_DISABLE_LOCAL_MODELS', None)
        self.addCleanup(self.cleanup)

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, '-m', 'localpilot_suite.cli', '--home', str(self.home),
            '--json', *args], cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def control(self, operation, args, expected=0):
        return self.cli('product-control', '--request-json',
            json.dumps({'version': 1, 'operation': operation, 'args': args}), expected=expected)

    def cleanup(self):
        if (self.home / 'connection.json').exists():
            for module in ('core', 'companion'):
                result = subprocess.run([sys.executable, '-m', 'localpilot_suite.cli', '--home', str(self.home),
                    '--json', 'product-control', '--request-json', json.dumps({'version': 1,
                    'operation': 'service_control', 'args': {'module': module, 'action': 'stop', 'confirmed': True}})],
                    cwd=self.root, env=self.env, capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.tmp.cleanup()

    def test_first_run_save_activate_and_reopen_keep_existing_session(self):
        setup = self.cli('desktop-init', '--workspace', str(self.workspace))
        self.assertEqual(setup['status'], 'ready')
        self.assertFalse(setup['local_inference']['mlx_supported'])
        self.assertFalse(setup['model_downloaded'])
        self.assertFalse(setup['omlx_service_reused'])
        from localpilot_service.cli import connection
        client = connection(self.home)
        original = private_json(self.home / 'service.json')
        self.control('configure_local_endpoint', {'name': 'cpu-before', 'model': 'previous-cpu-model',
            'base_url': 'http://127.0.0.1:1234/v1', 'context_budget': 8192, 'companion': False})
        self.assertEqual(self.control('activate_model_configuration', {'confirmed': True})['status'], 'activated')
        old_session = client.request('/localpilot/v1/sessions', {'model': 'cpu-before'}, key='portable-old-session')
        saved = self.control('configure_local_endpoint', {'name': 'cpu-agent', 'model': 'existing-cpu-model',
            'base_url': 'http://127.0.0.1:1234/v1', 'context_budget': 8192, 'companion': True,
            'companion_power_policy': 'off', 'disable_thinking': True})
        self.assertEqual(saved['connection'], 'NOT_PROBED')
        self.assertTrue(self.control('model_configuration', {})['restart_required'])
        self.assertNotIn('cpu-agent', [row['id'] for row in client.request('/v1/models')['data']])
        active = self.control('activate_model_configuration', {'confirmed': True})
        self.assertEqual(active['status'], 'activated')
        self.assertEqual(active['services']['core']['status'], 'ready')
        self.assertEqual(active['services']['companion']['status'], 'running')
        self.assertFalse(self.control('model_configuration', {})['restart_required'])
        self.assertIn('cpu-agent', [row['id'] for row in client.request('/v1/models')['data']])
        restored = client.request('/localpilot/v1/sessions/' + old_session['id'])
        self.assertEqual(restored['id'], old_session['id'])
        after = private_json(self.home / 'service.json')
        self.assertEqual(after['routes']['default'], original['routes']['default'])
        self.assertEqual(self.control('activate_model_configuration', {'confirmed': True})['status'], 'unchanged')
        reopened = self.cli('desktop-init', '--workspace', str(self.workspace))
        self.assertEqual(reopened['status'], 'ready')
        self.assertIn('cpu-agent', private_json(self.home / 'service.json')['routes'])
        self.assertEqual(client.request('/localpilot/v1/sessions/' + old_session['id'])['id'], old_session['id'])

    def test_cloud_provider_setup_preserves_local_routes_and_existing_sessions(self):
        self.cli('desktop-init', '--workspace', str(self.workspace))
        original = private_json(self.home / 'service.json')
        key_file = self.root / 'synthetic-provider.key'
        key_file.write_text('synthetic-provider-key-not-for-network\n')
        key_file.chmod(0o600)
        configured = self.cli('cloud-configure', '--provider', 'openai', '--key-file', str(key_file))
        self.assertEqual(configured['provider'], 'openai')
        self.assertEqual(configured['model'], 'gpt-6-luna')
        self.assertEqual(configured['api_connection'], 'NOT_PROBED')
        self.assertFalse(configured['credential_copied'])
        self.assertIsNone(configured['cooperative_route'])
        config = private_json(self.home / 'service.json')
        self.assertEqual(config['routes']['default'], original['routes']['default'])
        backend = config['routes']['openai-agent']['backend']
        self.assertEqual(backend['protocol'], 'responses')
        self.assertEqual(backend['key_file'], str(key_file))
        self.assertNotIn('synthetic-provider-key-not-for-network', (self.home / 'clients.env').read_text())
        from localpilot_service.cli import connection
        client = connection(self.home)
        session = client.request('/localpilot/v1/sessions', {'model': 'openai-agent'}, key='cloud-provider-fixture')
        deepseek = self.cli('cloud-configure', '--key-file', str(key_file))
        self.assertEqual(deepseek['provider'], 'deepseek')
        after = private_json(self.home / 'service.json')
        self.assertEqual(after['routes']['openai-agent'], config['routes']['openai-agent'])
        self.assertEqual(client.request('/localpilot/v1/sessions/' + session['id'])['id'], session['id'])
        self.assertEqual(self.cli('cloud-configure', '--provider', 'openai', '--key-file', str(key_file))['status'], 'already_configured')

    def test_cloud_setup_failure_restores_both_configs_and_services(self):
        self.cli('desktop-init', '--workspace', str(self.workspace))
        paths = [self.home / name for name in ('service.json', 'companion.json', 'clients.env')]
        originals = {path.name: path.read_bytes() for path in paths}
        key_file = self.root / 'synthetic-provider.key'
        key_file.write_text('synthetic-provider-key-not-for-network\n')
        key_file.chmod(0o600)
        from localpilot_suite import installation
        from localpilot_suite.desktop_setup import configure_cloud
        original_service = installation.service
        failed = False

        def fail_companion_recovery_once(home, module, action):
            nonlocal failed
            if module == 'companion' and action == 'recover' and not failed:
                failed = True
                raise ValueError('synthetic Companion recovery failure')
            return original_service(home, module, action)

        with patch.dict(os.environ, self.env), patch.object(
                installation, 'service', side_effect=fail_companion_recovery_once):
            with self.assertRaisesRegex(ValueError, 'synthetic Companion'):
                configure_cloud(self.home, str(key_file), provider='openai')
        for path in paths:
            self.assertTrue(path.read_bytes() == originals[path.name], path.name + ' was not restored')
        self.assertEqual(original_service(self.home, 'core', 'status')['status'], 'ready')
        self.assertEqual(original_service(self.home, 'companion', 'status')['status'], 'running')


if __name__ == '__main__':
    unittest.main()
