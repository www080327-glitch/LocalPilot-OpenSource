import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from localpilot_service.cli import save
from localpilot_service.security import private_json
from localpilot_suite.desktop_setup import migrate_desktop_acceptance_route
class RouteMigrationTests(unittest.TestCase):
 def config(self,root):
  return {'routes':{'gui-cloud-approval':{'workspace':str(root/'work'),'backend':{'kind':'deepseek','model':'deepseek-flash','key_file':'/private/config/existing-key'},'permissions':'approve-mutations','capabilities':{'read':True,'write':True,'execute':False},'cloud_egress':'CLOUD_ALLOWED','cloud_egress_paths':['fixture.txt','approved.txt'],'prompt_profile':'standard','tool_profile':'full','thinking':'none','verification':{'id':'desktop-approved-file'}}},'clients':[{'subject':'http','routes':{}},{'subject':'operator','operator':True,'routes':{}}]}
 def test_exact_fixture_migration_keeps_history_scope_and_admissible_budget(self):
  with tempfile.TemporaryDirectory() as d:
   h=Path(d);original=self.config(h);save(h/'service.json',original)
   with patch('localpilot_service.cli.stop',return_value={'status':'stopped'}):result=migrate_desktop_acceptance_route(h)
   new=private_json(h/'service.json');self.assertEqual(new['routes']['gui-cloud-approval'],original['routes']['gui-cloud-approval'])
   route=new['routes'][result['route']];self.assertEqual(route['workspace'],original['routes']['gui-cloud-approval']['workspace']);self.assertFalse(route['capabilities']['execute']);self.assertEqual(route['cloud_egress_paths'],[]);self.assertNotIn('verification',route)
   self.assertLess(route['budgets']['max_output_tokens']*16+20000,131072);self.assertGreater(route['budgets']['max_token_units'],route['budgets']['max_output_tokens']*16*10)
   self.assertEqual(new['clients'][1]['routes'],{})
   self.assertEqual(migrate_desktop_acceptance_route(h)['status'],'not_applicable')
 def test_custom_or_busy_installation_is_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   h=Path(d);original=self.config(h);original['routes']['gui-cloud-approval']['verification']['id']='custom';save(h/'service.json',original)
   self.assertEqual(migrate_desktop_acceptance_route(h)['status'],'not_applicable');self.assertEqual(private_json(h/'service.json'),original)
   original=self.config(h);save(h/'service.json',original)
   with patch('localpilot_service.cli.stop',return_value={'status':'stopping'}):
    with self.assertRaises(ValueError):migrate_desktop_acceptance_route(h)
   self.assertEqual(private_json(h/'service.json'),original)
