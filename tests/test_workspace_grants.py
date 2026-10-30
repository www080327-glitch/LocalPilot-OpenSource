"""Deterministic controls on real files; these are not model or GUI acceptance."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent.registry import create_default_registry, ToolRegistry
from agent.safety import CapabilityPolicy
from agent.permissions import ToolRiskMetadata
from agent.safe_files import inspect_file
from localpilot_service.workspaces import WorkspaceGrants
from localpilot_api.service import APIError

class FolderControls(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.work=self.root/'work';self.work.mkdir();self.private=self.root/'private';self.private.mkdir(mode=0o700)
  self.store=WorkspaceGrants(self.private/'grants.json',[self.private]);self.file=self.work/'source.txt';self.file.write_text('real bytes');self.sha=hashlib.sha256(b'real bytes').hexdigest()
 def tearDown(self):self.tmp.cleanup()
 def registry(self,mode='assist-high-risk',**kwargs):return create_default_registry(self.work,permission_mode=mode,file_operations=True,**kwargs)
 def test_four_modes_and_hard_ceiling(self):
  for mode,expected in [('approve-all',['approval_required']*3),('assist-low-risk',['allowed','approval_required','approval_required']),('assist-high-risk',['allowed','allowed','approval_required']),('full-permission',['allowed']*3)]:
   g=self.registry(mode).gateway
   self.assertEqual([g.decide('read_file' if risk=='low' else 'apply_patch',risk,[],{})['status'] for risk in ['low','medium','high']],expected)
   self.assertEqual(g.decide('apply_patch','unavailable',[],{})['status'],'approval_required')
   self.assertEqual(g.decide('execute','low',[],{})['status'],'denied')
 def test_mkdir_move_rename_copy_and_identity(self):
  r=self.registry();self.assertEqual(r.call('make_directory',{'path':'documents'})['verification'],'passed')
  before=r.call('inspect_file',{'path':'source.txt'})
  moved=r.call('move_file',{'source':'source.txt','destination':'documents/renamed.txt','expected_sha256':self.sha})
  self.assertEqual(moved['status'],'ok');self.assertEqual(moved['before']['inode'],before['inode']);self.assertEqual(moved['before']['inode'],moved['after']['inode'])
  copied=r.call('copy_file',{'source':'documents/renamed.txt','destination':'copy.txt','expected_sha256':self.sha})
  self.assertEqual(copied['verification'],'passed');self.assertNotEqual(copied['before']['inode'],copied['after']['inode']);self.assertEqual((self.work/'copy.txt').read_bytes(),b'real bytes')
 def test_wrong_hash_no_overwrite_and_outside(self):
  r=self.registry();args={'source':'source.txt','destination':'copy.txt','expected_sha256':'0'*64}
  self.assertFalse(r.call('move_file',args)['action_sent']);(self.work/'copy.txt').write_text('keep')
  args['expected_sha256']=self.sha;self.assertFalse(r.call('copy_file',args)['action_sent']);self.assertEqual((self.work/'copy.txt').read_text(),'keep')
  for path in ['../private','/tmp','link/file.txt']:
   (self.work/'link').symlink_to(self.private) if not (self.work/'link').exists() else None
   with self.assertRaises((ValueError,OSError)):r.call('inspect_file',{'path':path})
 def test_unknown_after_dispatched_effect(self):
  from agent.safe_files import transfer
  with patch('agent.safe_files.digest_fd',side_effect=[{'device':self.file.stat().st_dev,'inode':self.file.stat().st_ino,'size_bytes':10,'modified_ns':self.file.stat().st_mtime_ns,'type':'file','sha256':self.sha},ValueError('verification failure')]):
   value=transfer(self.work,'source.txt','copied.txt',self.sha,moving=False)
  self.assertEqual(value['status'],'unknown');self.assertTrue(value['action_may_have_applied']);self.assertFalse(value['replay_allowed'])
 def test_grant_persistence_revocation_identity_and_scope(self):
  grant=self.store.create('desktop',str(self.work),'organize',[]);again=WorkspaceGrants(self.private/'grants.json',[self.private]);self.assertEqual(again.validate(grant['id'])['inode'],self.work.stat().st_ino)
  with self.store.guard(grant['id'],'move_file',{}):pass
  with self.assertRaises(PermissionError):
   with self.store.guard(grant['id'],'apply_patch',{}):pass
  self.store.revoke(grant['id'],'desktop')
  with self.assertRaises(PermissionError):
   with self.store.guard(grant['id'],'read_file',{}):pass
  grant=self.store.create('desktop',str(self.work),'read',[]);self.work.rename(self.root/'old');self.work.mkdir()
  with self.assertRaises(PermissionError):self.store.validate(grant['id'])
 def test_scope_operator_and_private_roots(self):
  for path in [self.private,Path.home(),Path('/')]:
   with self.assertRaises(APIError):self.store.create('desktop',str(path),'modify',[])
  grant=self.store.create('desktop',str(self.work),'read',[])
  with self.assertRaises(APIError):self.store.get(grant['id'],'dsh')
  with self.assertRaises(PermissionError):
   with self.store.guard(grant['id'],'make_directory',{}):pass
 def test_unknown_extension_and_reserved_names(self):
  r=ToolRegistry(self.work,permission_mode='assist-high-risk');r.register('unknown',lambda workspace_root:'ran')
  self.assertEqual(r.call('unknown',{})['status'],'approval_required')
  with self.assertRaises(ValueError):r.register('read_file',lambda workspace_root,path:'bypass',ToolRiskMetadata(read_only=True,mutating=False))
 def test_judge_receives_patch_and_command_without_audit_bodies(self):
  observed=[]
  from agent.permissions import RiskAssessment
  judge=lambda *args:(observed.append(args) or RiskAssessment('LOW','bounded','local','allow'))
  r=self.registry('local-judge-permissive',judge=judge,capabilities=CapabilityPolicy(execute=True))
  r.call('apply_patch',{'changes':[{'path':'created','operation':'create','content':'judge-must-see-content'}]})
  self.assertIn('judge-must-see-content',json.dumps(observed));self.assertNotIn('judge-must-see-content',json.dumps(r.gateway.audit))
