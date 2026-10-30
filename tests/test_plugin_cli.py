"""Suite lifecycle and service opt-in, with no user configuration mutation."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'suite'))
from localpilot_suite.cli import main
from localpilot_plugins.adapter import attach, configure_session
from localpilot_plugins.security import save_json
from agent.registry import create_default_registry
from agent.session import AgentSession
from tests.test_runtime_session import ScriptBackend, response


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'native'
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            rc = main(['--home', str(self.home), '--json', *args])
        return rc, json.loads(output.getvalue())

    def test_plugin_lifecycle_install_is_not_enable(self):
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'id': 'public-test', 'transport': 'stdio', 'command': sys.executable, 'args': ['--version']}))
        rc, result = self.run_cli('plugins', 'add', str(manifest))
        self.assertEqual(rc, 0)
        self.assertEqual(result['status'], 'installed_disabled')
        self.assertEqual(self.run_cli('plugins', 'enable', 'public-test')[0], 2)
        self.assertEqual(self.run_cli('plugins', 'doctor', 'public-test')[0], 4)
        self.assertFalse(self.run_cli('plugins', 'list')[1]['plugins'][0]['enabled'])
        self.assertEqual(self.run_cli('plugins', 'add', str(manifest))[0], 2)
        self.assertEqual(self.run_cli('plugins', 'remove', 'public-test')[0], 0)
        self.assertEqual(self.run_cli('plugins', 'list')[1]['plugins'], [])

    def test_skill_cli_explicit_enable_and_disable(self):
        bundle = Path(__file__).resolve().parents[1] / 'examples/skills/public-notes'
        rc, installed = self.run_cli('skills', 'add', str(bundle))
        self.assertEqual(rc, 0)
        rc, _ = self.run_cli('skills', 'enable', 'public-notes', '--reviewed-sha256', installed['bundle_sha256'])
        self.assertEqual(rc, 0)
        self.assertEqual(self.run_cli('skills', 'doctor', 'public-notes', '--tools', 'read_file')[0], 0)
        self.assertEqual(self.run_cli('skills', 'disable', 'public-notes')[0], 0)
        self.assertEqual(self.run_cli('skills', 'doctor', 'public-notes', '--tools', 'read_file')[0], 4)

    def test_native_credential_home_must_not_overlap_model_workspace(self):
        registry = create_default_registry(self.workspace)
        with self.assertRaises(ValueError):
            attach(registry, self.workspace / '.private-native')

    def test_service_route_opt_in_constructs_existing_session_without_connecting(self):
        from localpilot_service.deployment import build
        path = self.root / 'service.json'
        value = {'schema_version': 1, 'host': '127.0.0.1', 'port': 0,
            'data_dir': str(self.root / 'data'), 'clients': [{'subject': 'test', 'token_env': 'PLUGIN_TEST_NATIVE_TOKEN'}],
            'routes': {'localpilot': {'workspace': str(self.workspace), 'backend': {'kind': 'local-openai', 'model': 'public-fixture', 'base_url': 'http://127.0.0.1:1/v1', 'context_budget': 65536},
                'plugins': {'home': str(self.home / 'plugins')}}}}
        save_json(path, value)
        with patch.dict(os.environ, PLUGIN_TEST_NATIVE_TOKEN='public-test-token-' + 'x' * 32):
            server = build(path)
        try:
            session = server.service.create_session()
            runtime = server.service.sessions[session['id']].runtime
            self.assertIsInstance(runtime, AgentSession)
            self.assertEqual(runtime.registry.plugin_manager.clients, {})
            self.assertIn('read_file', runtime.registry._tools)
        finally:
            server.service.shutdown(timeout=3)
            server.access.close()
            server.server_close()

    def test_corrupt_plugin_record_is_quarantined(self):
        from localpilot_plugins.manager import PluginManager
        manager = PluginManager(self.home / 'plugins')
        save_json(manager.home / 'broken.json', {})
        registry = create_default_registry(self.workspace)
        attach(registry, manager.home)
        try:
            self.assertEqual(manager.list()[0]['status'], 'invalid_record')
            self.assertIn('read_file', registry._tools)
        finally:
            registry.plugin_manager.close()

    def test_core_without_plugin_imports_keeps_builtin_agent_tools(self):
        from tests.test_runtime_session import call
        registry = create_default_registry(self.workspace, permission_mode='full-permission')
        runtime = AgentSession(registry, backend=ScriptBackend(response(None, call('list_directory', {'path': '.'})), response('Read public directory')))
        try:
            with patch.dict(sys.modules, {'localpilot_plugins.adapter': None}):
                runtime.run_turn('Inspect the public workspace')
            self.assertTrue(runtime.tool_history[0]['payload']['ok'])
        finally:
            runtime.close()


if __name__ == '__main__':
    unittest.main()
