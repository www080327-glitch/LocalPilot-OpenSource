"""Real saved configurations and Core reconstruction; no model or cloud requests."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localpilot_service.cli import environment, save
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
        save(self.home / 'companion.json', {'backend': 'disabled', 'watch_dirs': [], 'native_observation_enabled': False,
             'localpilot_client_subject': 'gui', 'localpilot_api_key_env': 'LOCALPILOT_TEST_TOKEN'})
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
        with patch.dict(os.environ, environment(self.home)):
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
        catalog = self.dispatch('model_configuration', {})
        self.assertTrue(catalog['restart_required'])
        self.assertEqual(catalog['restart_modules'], ['core', 'companion'])

    def test_cpu_endpoint_uses_explicit_power_and_thinking_with_small_context(self):
        save(self.home / 'companion.json', {'backend': 'mlx', 'model_adapter_path': '/old/mlx-adapter',
            'watch_dirs': [], 'native_observation_enabled': False, 'low_power_policy': 'always',
            'allow_local_on_battery': False, 'max_output_tokens': 4096,
            'localpilot_client_subject': 'gui', 'localpilot_api_key_env': 'LOCALPILOT_TEST_TOKEN'})
        self.dispatch('configure_local_endpoint', {'name': 'cpu-agent', 'model': 'local-model',
            'base_url': 'http://localhost:1234/v1/', 'context_budget': 4096, 'companion': True,
            'companion_power_policy': 'system', 'disable_thinking': True})
        route = private_json(self.home / 'service.json')['routes']['cpu-agent']
        self.assertEqual(route['budgets']['max_output_tokens'], 1024)
        self.assertEqual(route['budgets']['max_worker_output_tokens'], 1024)
        self.assertEqual(route['backend']['chat_template_kwargs'], {'enable_thinking': False})
        self.assertEqual(route['backend']['base_url'], 'http://127.0.0.1:1234/v1')
        companion = private_json(self.home / 'companion.json')
        self.assertEqual(companion['low_power_policy'], 'system')
        self.assertTrue(companion['http_model_disable_thinking'])
        self.assertEqual(companion['model_adapter_path'], '')
        self.assertEqual(companion['http_model_endpoint'], 'http://127.0.0.1:1234/v1')
        self.assertEqual(companion['max_output_tokens'], 1024)
        self.assertEqual(companion['localpilot_route'], 'cpu-agent')
        self.assertEqual(companion['localpilot_analysis_route'], 'cpu-agent-reasoning')
        config = private_json(self.home / 'service.json')
        analysis = config['routes']['cpu-agent-reasoning']
        self.assertTrue(analysis['reasoning_only'])
        self.assertEqual(analysis['capabilities'], {'read': False, 'write': False, 'execute': False})
        resource = next(c for c in config['clients'] if c['subject'] == 'endpoint-resource')
        self.assertEqual(resource['scopes'], ['read', 'resource_control'])
        self.assertEqual(resource['approval_for'], ['gui'])
        self.assertIn(companion['localpilot_resource_key_env'], environment(self.home))
        self.assertNotIn('localpilot_auto_local', companion)
        self.assertFalse(companion['allow_local_on_battery'])
        self.assertFalse(companion['native_observation_enabled'])
        from companion.config import Config
        self.assertEqual(Config.load(self.home / 'companion.json').backend, 'local-http')

    def test_endpoint_defaults_preserve_power_and_reject_invalid_preferences_before_save(self):
        settings = {'backend': 'disabled', 'low_power_policy': 'always', 'allow_local_on_battery': False,
                    'localpilot_client_subject': 'gui', 'localpilot_api_key_env': 'LOCALPILOT_TEST_TOKEN'}
        save(self.home / 'companion.json', settings)
        args = {'name': 'cpu-agent', 'model': 'local-model', 'base_url': 'http://127.0.0.1:1234/v1',
                'context_budget': 8192, 'companion': True}
        for invalid in [{'companion_power_policy': 'auto'}, {'disable_thinking': 'yes'},
                        {'companion': False, 'companion_power_policy': 'off'}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.dispatch('configure_local_endpoint', {**args, **invalid})
        self.assertEqual(private_json(self.home / 'companion.json'), settings)
        self.assertEqual(private_json(self.home / 'service.json'), self.config)
        self.dispatch('configure_local_endpoint', args)
        saved = private_json(self.home / 'companion.json')
        self.assertEqual(saved['low_power_policy'], 'always')
        self.assertFalse(saved['allow_local_on_battery'])
        self.assertNotIn('http_model_disable_thinking', saved)

    def test_companion_resource_identity_follows_its_client_not_the_gui(self):
        companion = private_json(self.home / 'companion.json')
        companion.update(localpilot_client_subject='other', localpilot_api_key_env='LOCALPILOT_OTHER_TOKEN')
        save(self.home / 'companion.json', companion)
        self.dispatch('configure_local_endpoint', {'name': 'cpu-agent', 'model': 'local-model',
            'base_url': 'http://127.0.0.1:1234/v1', 'context_budget': 8192, 'companion': True})
        saved = private_json(self.home / 'service.json')
        resource = next(c for c in saved['clients'] if c['subject'] == 'endpoint-resource')
        self.assertEqual(resource['approval_for'], ['other'])
        self.assertEqual(saved['clients'][1]['routes']['cpu-agent-reasoning'], 'cpu-agent-reasoning')
        actual = private_json(self.home / 'companion.json')
        self.assertEqual(actual['localpilot_client_subject'], 'other')
        self.assertEqual(actual['localpilot_api_key_env'], 'LOCALPILOT_OTHER_TOKEN')
        self.assertEqual(self.service().access.principals['endpoint-resource'].approval_for, ('other',))

    def test_existing_connection_uses_the_token_principal_for_its_catalog(self):
        save(self.home / 'connection.json', {'client_subject': 'gui', 'token_env': 'LOCALPILOT_OTHER_TOKEN'})
        self.assertEqual([m['id'] for m in self.dispatch('model_configuration', {})['models']], ['primary'])

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

    def test_explicit_openai_route_participates_in_five_modes_as_cloud(self):
        self.config['routes']['route-b'].update(cloud_egress='REQUIRES_APPROVAL',
            backend={'kind': 'openai', 'model': 'operator-selected-model',
                     'api_key_env': 'LOCALPILOT_OPENAI_FIXTURE', 'context_budget': 32768})
        save(self.home / 'service.json', self.config)
        catalog = self.dispatch('model_configuration', {})['models']
        worker = next(row for row in catalog if row['id'] == 'worker')
        self.assertTrue(worker['cooperation_supported'])
        self.assertEqual(worker['adapter'], 'openai')
        modes = ('local-only', 'local-first', 'balanced', 'cloud-first', 'cloud-only')
        for mode in modes:
            primary, partner = ('worker', 'primary') if mode == 'cloud-only' else ('primary', 'worker')
            self.dispatch('configure_cooperation', {'name': 'agent-' + mode, 'primary': primary,
                'partners': [partner], 'mode': mode, 'async_enabled': True})
        with patch.dict(os.environ, LOCALPILOT_OPENAI_FIXTURE='synthetic-openai-' + 'z' * 32):
            server = self.service()
            for mode in modes:
                name = 'agent-' + mode
                session = server.service.create_session(model=name)
                runtime = server.service.sessions[session['id']].runtime
                backends = list(runtime.hybrid.catalog.values())
                self.assertEqual(sum(not backend.is_local for backend in backends), 1)
                saved = private_json(self.home / 'service.json')['routes'][name]
                self.assertEqual(saved['cloud_egress'],
                    'LOCAL_ONLY' if mode == 'local-only' else 'REQUIRES_APPROVAL')
        self.assertEqual(private_json(self.home / 'service.json')['routes']['route-b']['backend'],
                         self.config['routes']['route-b']['backend'])
        self.assertNotIn('synthetic-openai-', json.dumps(self.dispatch('model_configuration', {})))


if __name__ == '__main__':
    unittest.main()
