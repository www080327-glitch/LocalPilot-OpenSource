"""One-click cloud routes preserve the user's selected private credential file."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.policy import DataPolicy
from localpilot_service.route_backends import build_backend
from localpilot_suite.desktop_setup import _cloud_route_additions


class CloudCredentialConfigurationTests(unittest.TestCase):
    def test_openai_routes_use_private_file_despite_inherited_default_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic-provider.key'
            path.write_text('fixture-user-selected-key\n')
            path.chmod(0o600)
            routes, reasoning, _ = _cloud_route_additions(
                {'default': {'backend': {'kind': 'unavailable', 'model': 'none'}}},
                'openai', 'gpt-6-luna', str(path), 'openai-agent')
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-inherited-key'}, clear=True):
                for name in ('openai-agent', reasoning):
                    with self.subTest(route=name):
                        spec = routes[name]['backend']
                        self.assertNotIn('api_key_env', spec)
                        self.assertEqual(spec['key_file'], str(path))
                        backend = build_backend(spec, DataPolicy())
                        self.assertEqual(backend._api_key, 'fixture-user-selected-key')


if __name__ == '__main__':
    unittest.main()
