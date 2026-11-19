"""Configured roles use the real service, HTTP transport and persisted workers."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localpilot_api.service import TaskRequest
from localpilot_service.cli import save
from localpilot_service.deployment import build
from localpilot_service.protocol import manifest
from localpilot_service.route_backends import cooperation_routes
from tests.test_local_http_backend import MockServer, completion, tool_call


class WorkerRoleRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'work'
        self.workspace.mkdir()
        (self.workspace / 'notes.txt').write_text('OBSERVED_ROLE_MARKER')
        self.provider = MockServer()
        self.addCleanup(self.provider.close)
        self.provider.models = ['main-model', 'search-model', 'review-model']
        routes = {}
        for name, effort in [('main', 'high'), ('searcher', 'low'), ('reviewer', 'medium')]:
            model = {'main': 'main-model', 'searcher': 'search-model', 'reviewer': 'review-model'}[name]
            routes[name] = {
                'workspace': str(self.workspace), 'engine': 'v5', 'thinking': effort,
                'cloud_egress': 'LOCAL_ONLY',
                'backend': {'kind': 'local-openai', 'model': model, 'base_url': self.provider.base_url,
                            'context_budget': 32768, 'reasoning_efforts': ['low', 'medium', 'high'],
                            'capabilities': {'streaming': False, 'reasoning': True}},
                'budgets': {'max_steps': 24, 'max_tool_calls': 32, 'max_token_units': 4194304,
                            'max_output_tokens': 1024, 'max_worker_steps': 6,
                            'max_worker_tool_calls': 8, 'max_worker_token_units': 524288,
                            'max_worker_output_tokens': 1024},
            }
        routes['main']['cooperation'] = {
            'routes': ['searcher', 'reviewer'], 'optimizer': {'mode': 'local-only'},
            'roles': {'search': 'searcher', 'review': 'reviewer'},
        }
        self.config = {'schema_version': 1, 'port': 0, 'data_dir': str(self.root / 'data'),
                       'clients': [{'subject': 'fixture', 'token_env': 'LP_ROLE_TEST_TOKEN',
                                    'routes': {'main': 'main'}}], 'routes': routes}
        self.path = self.root / 'service.json'
        save(self.path, self.config)
        self.environment = patch.dict(os.environ, LP_ROLE_TEST_TOKEN='synthetic-role-token-' + 'x' * 24)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.servers = []
        self.addCleanup(self.close_servers)

    def close_servers(self):
        for server in self.servers:
            if not server.service.closed:
                server.service.suspend()
            server.server_close()
            server.access.close()

    def service(self):
        server = build(self.path)
        self.servers.append(server)
        return server

    def test_role_models_efforts_and_receipts_survive_real_http_and_restart(self):
        self.provider.add(completion(calls=[tool_call('delegate', {
            'task': 'Read notes.txt and report the marker.', 'backend_preference': 'local',
            'role': 'search'}, 'search-role')]))
        self.provider.add(completion(calls=[tool_call('read_file', {'path': 'notes.txt'}, 'search-read')]))
        self.provider.add(completion('Observed OBSERVED_ROLE_MARKER.'))
        self.provider.add(completion(calls=[tool_call('delegate', {
            'task': 'Independently read notes.txt and review its marker.', 'backend_preference': 'local',
            'role': 'review'}, 'review-role')]))
        self.provider.add(completion(calls=[tool_call('read_file', {'path': 'notes.txt'}, 'review-read')]))
        self.provider.add(completion('Reviewed OBSERVED_ROLE_MARKER.'))
        self.provider.add(completion('Both read-only roles completed.'))
        server = self.service()
        session = server.service.create_session(model='main')
        task = server.service.create_task(TaskRequest('Explore then independently review notes.txt.',
            model='main', session_id=session['id']))
        result = server.service.wait(task['id'])
        self.assertEqual(result['status'], 'completed', result)
        runtime = server.service.sessions[session['id']].runtime
        self.assertEqual(runtime.hybrid.state['backend_id'], 'selected')
        self.assertEqual([request['model'] for request in self.provider.requests],
                         ['main-model', 'search-model', 'search-model', 'main-model',
                          'review-model', 'review-model', 'main-model'])
        self.assertEqual([request['reasoning_effort'] for request in self.provider.requests],
                         ['high', 'low', 'low', 'high', 'medium', 'medium', 'high'])
        self.assertEqual(len(runtime._children), 2)
        for child in runtime._children.values():
            self.assertTrue(child.registry.gateway.capabilities.read_only)
            self.assertFalse(child.registry.gateway.capabilities.write)
            self.assertFalse(child.registry.gateway.capabilities.execute)
            self.assertTrue(any(receipt['name'] == 'read_file' and receipt['payload']['ok']
                                for receipt in child.tool_history))
        self.assertEqual((self.workspace / 'notes.txt').read_text(), 'OBSERVED_ROLE_MARKER')
        original_config = runtime._persistence_config
        server.service.suspend()
        server.server_close()
        server.access.close()
        restored = self.service()
        actual = restored.service.sessions[session['id']].runtime
        self.assertEqual(actual._persistence_config, original_config)
        self.assertEqual(actual.worker_roles, {'search': 'route:searcher', 'review': 'route:reviewer'})
        self.assertEqual([child._effective_thinking() for child in actual._children.values()], ['low', 'medium'])
        self.assertEqual(restored.service.task_snapshot(task['id'])['result'], result['result'])
        self.assertEqual(len(self.provider.requests), 7)

    def test_role_configuration_validates_registered_partner_names(self):
        spec = self.config['routes']['main']
        for roles in [None, [], {'audit': 'searcher'}, {'search': 'main'},
                      {'review': 'missing'}, {'review': 1}]:
            with self.subTest(roles=roles), self.assertRaisesRegex(ValueError, 'Worker roles'):
                changed = deepcopy(spec)
                changed['cooperation']['roles'] = roles
                cooperation_routes('main', changed, self.config['routes'], self.workspace)
        changed = deepcopy(spec)
        changed['cooperation']['roles'] = {'search': 'searcher', 'review': 'searcher'}
        _, _, _, roles = cooperation_routes('main', changed, self.config['routes'], self.workspace)
        self.assertEqual(roles, {'search': 'route:searcher', 'review': 'route:searcher'})

    def test_roles_are_additive_to_legacy_cooperation_and_capability_manifest(self):
        spec = deepcopy(self.config['routes']['main'])
        spec['cooperation'].pop('roles')
        workers, policy, _, roles = cooperation_routes('main', spec, self.config['routes'], self.workspace)
        self.assertEqual(set(workers), {'route:searcher', 'route:reviewer'})
        self.assertEqual(policy.mode, 'local-only')
        self.assertIsNone(roles)
        spec['cooperation']['roles'] = {}
        self.assertIsNone(cooperation_routes('main', spec, self.config['routes'], self.workspace)[3])
        spec['cooperation'] = {'cloud_route': 'searcher', 'roles': {}}
        with self.assertRaisesRegex(ValueError, 'cooperation.routes'):
            cooperation_routes('main', spec, self.config['routes'], self.workspace)
        spec.pop('cooperation')
        self.assertEqual(cooperation_routes('main', spec, self.config['routes'], self.workspace),
                         ({}, None, None, None))
        self.assertIn('worker_roles_v1', manifest()['capabilities'])


if __name__ == '__main__':
    unittest.main()
