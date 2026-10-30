import unittest
from unittest.mock import Mock,patch
from pathlib import Path
from localpilot_suite.product_control import dispatch

class ProfileControlTests(unittest.TestCase):
    def test_profile_uses_the_owned_operator_session_without_submitting_a_task(self):
        client=Mock();client.request.return_value={'id':'sess_profile'}
        with patch('localpilot_suite.product_control.operator',return_value=(client,{'client_subject':'desktop'})):
            result=dispatch(Path('/unused'),{'version':1,'operation':'desktop_profile','args':{'session_id':'sess_profile','agent_profile':'minimal','expected_profile':'standard'}})
        self.assertEqual(result,{'id':'sess_profile'})
        client.request.assert_called_once_with('/localpilot/v1/desktop-sessions/sess_profile/profile',{'client_subject':'desktop','agent_profile':'minimal','expected_profile':'standard'})
    def test_path_injection_is_refused_before_operator_access(self):
        with self.assertRaises(ValueError):dispatch(Path('/unused'),{'version':1,'operation':'desktop_profile','args':{'session_id':'../../tasks','agent_profile':'minimal','expected_profile':'standard'}})

    def test_legacy_omlx_reference_does_not_hide_missing_model_manager_backend(self):
        import tempfile
        from localpilot_service.cli import private_dir,save
        from localpilot_service.security import private_json
        from localpilot_suite.desktop_setup import attach_omlx
        with tempfile.TemporaryDirectory() as tmp:
            home=private_dir(Path(tmp)/'home')
            legacy={'backend':{'kind':'local-openai','model':'old-model'},'workspace':str(home/'work')}
            save(home/'service.json',{'routes':{'default':legacy},'clients':[{'subject':'http','routes':{'localpilot':'default'}}]})
            save(home/'connection.json',{'url':'http://127.0.0.1:1','omlx_settings_file':'/existing/omlx.json'})
            (home/'clients.env').write_text('');(home/'clients.env').chmod(0o600)
            with patch('localpilot_service.cli.stop',return_value={'status':'stopped'}),patch('localpilot_service.cli.start',return_value={'status':'running'}):
                attach_omlx(home,'http://127.0.0.1:1234/v1',Path('/existing/omlx.json'))
            config=private_json(home/'service.json')
            self.assertEqual(config['routes']['default'],legacy)
            self.assertEqual(config['routes']['omlx-bootstrap']['backend']['kind'],'omlx')
            self.assertEqual(config['routes']['omlx-bootstrap']['engine'],'v5')
