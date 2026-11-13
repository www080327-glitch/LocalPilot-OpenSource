"""Cloud-primary LocalPilot routes can reuse existing Hybrid delegation to local workers.

Construct actual configured service/runtime, without model inference or external I/O.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from localpilot_service.deployment import build


class CloudLocalPartnershipTests(unittest.TestCase):
    def test_cloud_primary_has_local_child_backend_without_new_router(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / 'work'
            workspace.mkdir()
            config = {
                'schema_version': 1, 'port': 0, 'data_dir': str(root / 'data'),
                'clients': [{'subject': 'test', 'token_env': 'LP_LOCAL_PARTNER_TOKEN',
                             'routes': {'cloud': 'cloud', 'local': 'local'}}],
                'routes': {
                    'local': {
                        'workspace': str(workspace),
                        'backend': {'kind': 'local-openai', 'base_url': 'http://127.0.0.1:1234/v1',
                                    'model': 'local-fixture', 'context_budget': 32768},
                        'cloud_egress': 'LOCAL_ONLY',
                    },
                    'cloud': {
                        'workspace': str(workspace),
                        'backend': {'kind': 'deepseek-native', 'model': 'deepseek-flash',
                                    'api_key_env': 'LP_LOCAL_PARTNER_CLOUD_KEY', 'context_budget': 131072},
                        'cloud_egress': 'REQUIRES_APPROVAL',
                        'cooperation': {'local_route': 'local', 'optimizer': {'mode': 'cloud-first'}},
                    },
                },
            }
            path = root / 'service.json'
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            with patch.dict(os.environ, {'LP_LOCAL_PARTNER_TOKEN': 't' * 32,
                                          'LP_LOCAL_PARTNER_CLOUD_KEY': 'example-token'}):
                server = build(path)
                try:
                    created = server.service.create_session('cloud')
                    session = server.service.sessions[created['id']].runtime
                    self.assertEqual(session.primary, 'cloud')
                    self.assertEqual(session.routing_policy.value, 'cloud-first')
                    self.assertTrue(session.hybrid.catalog['local'].is_local)
                    self.assertEqual(session.hybrid.kind('selected'), 'cloud')
                    self.assertIs(session.hybrid.resolve('local')[1], session.local_backend)
                finally:
                    server.service.shutdown()
                    server.server_close()
                    server.access.close()

    def test_cloud_primary_requires_explicit_registered_local_partner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / 'work'
            workspace.mkdir()
            config = {
                'schema_version': 1, 'port': 0, 'data_dir': str(root / 'data'),
                'clients': [{'subject': 'test', 'token_env': 'LP_LOCAL_PARTNER_TOKEN',
                             'routes': {'cloud': 'cloud'}}],
                'routes': {
                    'cloud': {
                        'workspace': str(workspace),
                        'backend': {'kind': 'deepseek-native', 'model': 'deepseek-flash',
                                    'api_key_env': 'LP_LOCAL_PARTNER_CLOUD_KEY'},
                        'cooperation': {'local_route': 'missing', 'optimizer': {'mode': 'cloud-first'}},
                    },
                },
            }
            path = root / 'service.json'
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            with patch.dict(os.environ, {'LP_LOCAL_PARTNER_TOKEN': 't' * 32,
                                          'LP_LOCAL_PARTNER_CLOUD_KEY': 'example-token'}):
                with self.assertRaisesRegex(ValueError, 'registered unmanaged local'):
                    build(path)


if __name__ == '__main__':
    unittest.main()
