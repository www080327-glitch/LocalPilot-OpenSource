import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from localpilot_suite.integrations import install,uninstall,main

class IntegrationInstallTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.home=self.root/'service';self.home.mkdir(mode=0o700);self.project=self.root/'project';self.project.mkdir()
  self.client=type('C',(),{'base_url':'http://127.0.0.1:8765','token':'test-ordinary-token-not-operator'})()
 def tearDown(self):self.tmp.cleanup()
 def test_project_install_preserves_other_mcp_and_shared_uninstall(self):
  config=self.project/'.codex/config.toml';config.parent.mkdir();original='[mcp_servers.other]\ncommand="other"\n';config.write_text(original)
  with patch('localpilot_suite.integrations.principal',return_value=(self.client,{'token_env':'LOCALPILOT_CODEX_TOKEN'})):
   install(self.home,'codex',self.project);install(self.home,'dsh',self.project)
  self.assertTrue(config.read_text().startswith(original));uninstall('codex',self.project,self.home)
  self.assertEqual(config.read_text(),original);self.assertTrue((self.project/'.agents/skills/localpilot-agent/SKILL.md').exists())
  uninstall('dsh',self.project,self.home);self.assertFalse((self.project/'.agents/skills/localpilot-agent').exists())
 def test_existing_mcp_is_never_overwritten(self):
  config=self.project/'.codex/config.toml';config.parent.mkdir();config.write_text('[mcp_servers.localpilot]\ncommand="owned"\n')
  with patch('localpilot_suite.integrations.principal',return_value=(self.client,{'token_env':'LOCALPILOT_CODEX_TOKEN'})):
   with self.assertRaises(ValueError):install(self.home,'codex',self.project)
  self.assertIn('owned',config.read_text());self.assertFalse((self.project/'.agents/skills/localpilot-agent').exists())
 def test_modified_configuration_and_skill_are_preserved(self):
  with patch('localpilot_suite.integrations.principal',return_value=(self.client,{'token_env':'LOCALPILOT_CODEX_TOKEN'})):install(self.home,'codex',self.project)
  config=self.project/'.codex/config.toml';config.write_text(config.read_text()+'# user edit\n')
  with self.assertRaises(ValueError):uninstall('codex',self.project,self.home)
  self.assertIn('user edit',config.read_text())
 def test_user_scope_requires_explicit_flag(self):
  with self.assertRaises(ValueError):main(['install','codex','--scope','user'],self.home)

 def test_symlink_cannot_turn_project_install_into_global_write(self):
  outside=self.root/'outside.toml';outside.write_text('# untouched')
  config=self.project/'.codex/config.toml';config.parent.mkdir();config.symlink_to(outside)
  with patch('localpilot_suite.integrations.principal',return_value=(self.client,{'token_env':'LOCALPILOT_CODEX_TOKEN'})):
   with self.assertRaises(ValueError):install(self.home,'codex',self.project)
  self.assertEqual(outside.read_text(),'# untouched')
 def test_tampered_record_cannot_remove_an_outside_file(self):
  with patch('localpilot_suite.integrations.principal',return_value=(self.client,{'token_env':'LOCALPILOT_CODEX_TOKEN'})):install(self.home,'codex',self.project)
  record=self.project/'.localpilot/integration-codex.json';value=json.loads(record.read_text());outside=self.root/'outside';outside.write_text('keep');value['credential']=str(outside);record.write_text(json.dumps(value))
  with self.assertRaises(ValueError):uninstall('codex',self.project,self.home)
  self.assertEqual(outside.read_text(),'keep')

 def test_precompiled_skill_cache_is_not_source_authority(self):
  import shutil
  from localpilot_suite.integrations import skill_source
  assets=self.root/'assets';shutil.copytree(skill_source(),assets,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  cache=assets/'scripts/__pycache__';cache.mkdir();(cache/'sdk.cpython-314.pyc').write_bytes(b'generated-cache-not-authority')
  with patch('localpilot_suite.integrations.skill_source',return_value=assets),patch('localpilot_suite.integrations.principal',return_value=(self.client,{'token_env':'LOCALPILOT_CODEX_TOKEN'})):
   install(self.home,'codex',self.project);install(self.home,'dsh',self.project)
  self.assertFalse((self.project/'.agents/skills/localpilot-agent/scripts/__pycache__').exists())
