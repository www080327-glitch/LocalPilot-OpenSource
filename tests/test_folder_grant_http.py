"""Real API/persistence controls using a scripted backend, not GUI/model acceptance."""
import hashlib
from pathlib import Path
import unittest
from tests import test_agent_service as fixture
from tests.test_runtime_api import answer,call,Backend
from localpilot_service.workspaces import WorkspaceGrants

class FolderGrantHTTPTests(unittest.TestCase):
 def setUp(self):fixture.AgentServiceTests.setUp(self)
 def tearDown(self):fixture.AgentServiceTests.tearDown(self)
 def stop(self):fixture.AgentServiceTests.stop(self)
 def factory(self,callback):
  runtime=fixture.AgentServiceTests.factory(self,callback);runtime._workspace_grants=self.grants;return runtime
 def start(self):
  self.grants=WorkspaceGrants(self.root/'grants.json',[self.root/'runtime.db',self.root/'audit.jsonl'])
  fixture.AgentServiceTests.start(self);self.server.workspace_grants=self.grants
  self.server.catalog={'localpilot':{'deployment_status':'ready','adapter':'deepseek','capabilities':['tool_calling'],'cloud_egress':'CLOUD_ALLOWED','tool_capabilities':{'read':True,'write':True,'execute':False}}}
 def grant(self,scope='organize'):
  selected=self.root/'selected';selected.mkdir(exist_ok=True);(selected/'public.txt').write_text('selected folder only')
  g=self.operator.request('/localpilot/v1/workspace-grants',{'client_subject':'codex','operation':'grant','folder':str(selected),'scope':scope,'cloud_paths':[]})
  s=self.operator.request('/localpilot/v1/desktop-sessions',{'client_subject':'codex','model':'localpilot','source':'cloud_only','options':{'permission_mode':'uncertain','agent_profile':'standard','workspace_grant':g['id']}},key='folder-'+scope)
  return g,s,selected.resolve()
 def test_authorized_session_real_file_read_and_restart(self):
  g,s,selected=self.grant();runtime=self.service.sessions[s['id']].runtime
  self.assertEqual(runtime.workspace,selected);self.assertIn('move_file',runtime.registry._tools);self.assertFalse(runtime.registry.gateway.capabilities.execute)
  self.backend.steps=[answer(None,call('read_file',{'path':'public.txt'},'real-read')),answer('selected folder only')]
  task=self.codex.submit('Read the selected public file',session_id=s['id'],idempotency_key='selected-read');self.service.wait(task['id']);done=self.codex.status(task['id'])
  self.assertEqual(done['status'],'completed');self.assertEqual(done['tools'][0]['payload']['result'],'selected folder only')
  self.stop();self.service.suspend();self.start();restored=self.codex.status(task['id']);self.assertEqual(restored['id'],task['id'])
  self.assertEqual(self.service.sessions[s['id']].runtime.workspace,selected)
  self.operator.request('/localpilot/v1/workspace-grants',{'client_subject':'codex','operation':'revoke','grant_id':g['id']})
  with self.assertRaises(PermissionError):self.service.sessions[s['id']].runtime.registry.call('read_file',{'path':'public.txt'})
  self.assertEqual(self.codex.status(task['id'])['file_operation_verification']['status'],'BLOCKED')
  self.stop();self.service.suspend();self.start()
  with self.assertRaises(PermissionError):self.service.sessions[s['id']].runtime.registry.call('read_file',{'path':'public.txt'})
 def test_ordinary_parent_cannot_grant_or_approve(self):
  body={'client_subject':'codex','operation':'grant','folder':str(self.workspace),'scope':'modify','cloud_paths':[]}
  fixture.AgentServiceTests.denied(self,403,lambda:self.codex.request('/localpilot/v1/workspace-grants',body))
  fixture.AgentServiceTests.denied(self,403,lambda:self.operator.request('/localpilot/v1/workspace-grants',{**body,'client_subject':'dsh'}))
 def test_read_scope_and_no_scope_escape_even_full_permission(self):
  g,s,selected=self.grant('read');r=self.service.sessions[s['id']].runtime.registry
  r.gateway.mode='full-permission'
  for name,args in [('make_directory',{'path':'no'}),('execute',{'argv':['echo','no']})]:
   with self.assertRaises(PermissionError):r.call(name,args,approved=True)
  with self.assertRaises(ValueError):r.call('read_file',{'path':'../outside.txt'},approved=True)
 def test_write_disabled_route_cannot_gain_scope(self):
  self.server.catalog['localpilot']['tool_capabilities']['write']=False
  from urllib.error import HTTPError
  with self.assertRaises(HTTPError) as e:self.grant('organize')
  self.assertEqual(e.exception.code,409);e.exception.close()
