"""Real saved configurations and Core reconstruction; no model or cloud requests."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localpilot_service.cli import save
from localpilot_service.deployment import build
from localpilot_service.security import private_json
from localpilot_suite.product_control import dispatch


class ModelConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o700)
        self.work = self.root / 'work'
        self.work.mkdir()
        route = {'workspace': str(self.work), 'engine': 'v5', 'cloud_egress': 'LOCAL_ONLY',
                 'backend': {'kind': 'local-openai', 'model': 'fixture-a', 'base_url': 'http://127.0.0.1:1/v1',
                             'context_budget': 32768}, 'budgets': {'max_subagents_per_turn': 0}}
        self.config = {'schema_version': 1, 'host': '127.0.0.1', 'port': 0,
                       'data_dir': str(self.home / 'state'), 'log_dir': str(self.home / 'logs'),
                       'clients': [{'subject': 'gui', 'token_env': 'LOCALPILOT_TEST_TOKEN',
                                    'routes': {'primary': 'route-a', 'worker': 'route-b'}},
                                   {'subject': 'other', 'token_env': 'LOCALPILOT_OTHER_TOKEN',
                                    'routes': {'primary': 'route-a'}}],
                       'routes': {'route-a': route, 'route-b': deepcopy(route)}}
        self.config['routes']['route-b']['backend']['model'] = 'fixture-b'
        save(self.home / 'service.json', self.config)
        save(self.home / 'connection.json', {'client_subject': 'gui'})
        save(self.home / 'companion.json', {'backend': 'disabled', 'watch_dirs': [], 'native_observation_enabled': False})
        self.env = patch.dict(os.environ, LOCALPILOT_TEST_TOKEN='synthetic-gui-token-'+'x'*24,
                              LOCALPILOT_OTHER_TOKEN='synthetic-other-token-'+'y'*24)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.services = []
        self.addCleanup(self.close_services)

    def close_services(self):
        for server in self.services:
            if not server.service.closed:
                server.service.suspend()
            server.server_close()
            server.access.close()

    def service(self):
        server = build(self.home / 'service.json')
        self.services.append(server)
        return server

    def dispatch(self, operation, args):
        return dispatch(self.home, {'version': 1, 'operation': operation, 'args': args})

    def cooperate(self, **changes):
        return self.dispatch('configure_cooperation', dict(name='personal-agent', primary='primary',
            partners=['worker'], mode='local-first', async_enabled=True, **changes))

    def test_new_async_route_preserves_real_existing_session_and_original_budgets(self):
        initial = self.service()
        session = initial.service.create_session(model='route-a')
        original = initial.service.sessions[session['id']].runtime._persistence_config
        result = self.cooperate()
        self.assertTrue(result['restart_required'])
        self.assertNotIn('personal-agent', initial.catalog)
        saved = private_json(self.home / 'service.json')
        self.assertEqual(saved['routes']['route-a'], dict(self.config['routes']['route-a'], orchestration_mode='sync'))
        self.assertEqual(saved['routes']['personal-agent']['cooperation']['routes'], ['route-b'])
        self.assertEqual(saved['routes']['personal-agent']['budgets']['max_worker_token_units'], 524288)
        self.assertNotIn('personal-agent', saved['clients'][1]['routes'])
        initial.service.suspend()
        restored = self.service()
        self.assertEqual(restored.service.sessions[session['id']].runtime._persistence_config, original)
        new = restored.service.create_session(model='personal-agent')
        runtime = restored.service.sessions[new['id']].runtime
        self.assertTrue(runtime._async_enabled)
        self.assertEqual(set(runtime.hybrid.catalog), {'selected', 'route:route-b'})
        self.assertEqual(private_json(Path(result['backup'])), self.config)

    def test_local_endpoint_and_companion_config_do_not_start_or_modify_privacy_scope(self):
        result = self.dispatch('configure_local_endpoint', {'name': 'cpu-agent', 'model': 'local-model',
            'base_url': 'http://127.0.0.1:1234/v1', 'context_budget': 16384, 'companion': True})
        self.assertEqual(result['inference'], 'NOT_RUN')
        self.assertEqual(result['connection'], 'NOT_PROBED')
        self.assertEqual(result['restart_modules'], ['core', 'companion'])
        saved = private_json(self.home / 'service.json')
        self.assertEqual(saved['routes']['route-a'], self.config['routes']['route-a'])
        self.assertEqual(saved['routes']['cpu-agent']['backend']['kind'], 'local-openai')
        companion = private_json(self.home / 'companion.json')
        self.assertEqual(companion['backend'], 'local-http')
        self.assertEqual(companion['watch_dirs'], [])
        self.assertFalse(companion['native_observation_enabled'])
        server = self.service()
        self.assertEqual(server.catalog['cpu-agent']['model'], 'local-model')
        self.assertFalse(server.service.sessions)

    def test_wrong_endpoint_and_cross_workspace_are_rejected_without_writing(self):
        for endpoint in ['https://example.test/v1', 'http://127.0.0.1:1234/v1?x=1', 'http://127.0.0.1:1234/other']:
            with self.assertRaises(ValueError):
                self.dispatch('configure_local_endpoint', {'name': 'cpu-agent', 'model': 'model',
                    'base_url': endpoint, 'context_budget': 16384, 'companion': False})
        self.assertEqual(private_json(self.home / 'service.json'), self.config)
        other = self.root / 'other'
        other.mkdir()
        self.config['routes']['route-b']['workspace'] = str(other)
        save(self.home / 'service.json', self.config)
        with self.assertRaisesRegex(ValueError, 'same authorized workspace'):
            self.cooperate()
        self.assertEqual(private_json(self.home / 'service.json'), self.config)

    def test_old_core_capability_manifest_rejects_configuration_before_writing(self):
        with patch('localpilot_service.protocol.manifest',return_value={'capabilities':[]}):
            with self.assertRaisesRegex(ValueError,'route_orchestration_v1'):
                self.cooperate()
        self.assertEqual(private_json(self.home/'service.json'),self.config)
        self.assertFalse(list(self.home.glob('service.before-model-*.json')))

    def test_public_catalog_and_duplicate_route_do_not_expose_or_replace_credentials(self):
        self.config['routes']['route-a']['backend']['api_key_env'] = 'SECRET_REFERENCE_ONLY'
        save(self.home / 'service.json', self.config)
        catalog = self.dispatch('model_configuration', {})
        self.assertEqual({row['id'] for row in catalog['models']}, {'primary', 'worker'})
        self.assertNotIn('SECRET_REFERENCE_ONLY', json.dumps(catalog))
        self.cooperate()
        after = (self.home / 'service.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.cooperate()
        self.assertEqual((self.home / 'service.json').read_bytes(), after)


if __name__ == '__main__':
    unittest.main()
