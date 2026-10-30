import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from localpilot_suite.desktop_setup import configure_cloud_scope,discover_omlx


class DesktopSetupTests(unittest.TestCase):
    def test_invalid_egress_paths_do_not_touch_lifecycle(self):
        for paths in [[],['../secret'],['/private/file'],['a/../b'],['./a'],['a']*33]:
            with self.assertRaises(ValueError):configure_cloud_scope(Path('/unused'),paths)

    def test_scope_adds_a_new_route_without_rewriting_existing_session_route(self):
        config={'routes':{'deepseek-agent':{'backend':{'kind':'deepseek-native'},'cloud_egress':'REQUIRES_APPROVAL'}},'clients':[{'subject':'gui','routes':{'deepseek-agent':'deepseek-agent'}}]}
        saved=[]
        with patch('localpilot_service.security.private_json',return_value=config),patch('localpilot_service.cli.stop',return_value={'status':'stopped'}),patch('localpilot_service.cli.start'),patch('localpilot_service.cli.save',side_effect=lambda p,v:saved.append(v)):
            result=configure_cloud_scope(Path('/private-fixture'),['input.txt','answer.txt'])
        self.assertEqual(saved[0]['routes']['deepseek-agent']['cloud_egress'],'REQUIRES_APPROVAL')
        self.assertNotIn('cloud_egress_paths',saved[0]['routes']['deepseek-agent'])
        self.assertEqual(saved[0]['routes'][result['route']]['cloud_egress_paths'],['input.txt','answer.txt'])

if __name__=='__main__':unittest.main()
