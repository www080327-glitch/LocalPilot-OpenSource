"""Real backend construction with synthetic credentials; no network requests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.cloud_credentials import CloudCredentialError
from agent.persistence import backend_identity
from agent.policy import DataPolicy
from localpilot_service.route_backends import build_backend


class OpenAICredentialSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.key_file = Path(temporary.name) / 'synthetic-provider.key'
        self.key_file.write_text('fixture-private-file-key\n')
        self.key_file.chmod(0o600)

    def test_explicit_missing_environment_does_not_fall_back_to_defaults(self):
        for protocol in ('chat_completions', 'responses'):
            for defaults in ({'OPENAI_API_KEY': 'fixture-default-environment-key'},
                             {'OPENAI_API_KEY_FILE': str(self.key_file)}):
                for selected in ({}, {'LOCALPILOT_TEST_OPENAI_KEY': ''}):
                    with self.subTest(protocol=protocol, defaults=list(defaults), selected=list(selected)):
                        with patch.dict(os.environ, {**defaults, **selected}, clear=True):
                            with self.assertRaises(CloudCredentialError) as error:
                                build_backend({'kind': 'openai', 'protocol': protocol,
                                    'model': 'gpt-6-luna', 'api_key_env': 'LOCALPILOT_TEST_OPENAI_KEY'},
                                    DataPolicy())
                        self.assertEqual(error.exception.category, 'missing_credentials')

    def test_default_environment_and_file_preserve_chat_identity(self):
        for environment, expected in (
                ({'OPENAI_API_KEY': 'fixture-default-environment-key'}, 'fixture-default-environment-key'),
                ({'OPENAI_API_KEY_FILE': str(self.key_file)}, 'fixture-private-file-key')):
            with self.subTest(environment=list(environment)), patch.dict(os.environ, environment, clear=True):
                default = build_backend({'kind': 'openai', 'model': 'gpt-6-luna'}, DataPolicy())
                chat = build_backend({'kind': 'openai', 'model': 'gpt-6-luna',
                                      'protocol': 'chat_completions'}, DataPolicy())
                responses = build_backend({'kind': 'openai', 'model': 'gpt-6-luna',
                                           'protocol': 'responses'}, DataPolicy())
                self.assertEqual(default._api_key, expected)
                self.assertEqual(responses._api_key, expected)
                self.assertEqual(backend_identity(default), backend_identity(chat))
                self.assertNotEqual(backend_identity(default), backend_identity(responses))

    def test_explicit_environment_remains_the_selected_source(self):
        environment = {'OPENAI_API_KEY': 'fixture-default-environment-key',
                       'LOCALPILOT_TEST_OPENAI_KEY': 'fixture-selected-environment-key'}
        with patch.dict(os.environ, environment, clear=True):
            for protocol in ('chat_completions', 'responses'):
                with self.subTest(protocol=protocol):
                    backend = build_backend({'kind': 'openai', 'model': 'gpt-6-luna',
                        'protocol': protocol, 'api_key_env': 'LOCALPILOT_TEST_OPENAI_KEY',
                        'key_file': str(self.key_file)}, DataPolicy())
                    self.assertEqual(backend._api_key, 'fixture-selected-environment-key')


if __name__ == '__main__':
    unittest.main()
