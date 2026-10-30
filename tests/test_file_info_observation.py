"""Qualified filesystem observations, without rewriting historical failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent.registry import create_default_registry
from agent.tools import file_info
from agent.backends import BackendResponse,Message,ToolCall,BackendCapabilities,ModelInfo
from agent.session import AgentSession,SessionBudgets


class FileInfoObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.registry=create_default_registry(self.root,permission_mode='full-permission')

    def test_absent_builtin_is_successful_observation_without_read_coverage(self):
        result=self.registry.call('file_info',{'path':'new.txt'})
        self.assertIs(result['exists'],False)
        self.assertEqual(result['observation'],'target_not_found')
        self.assertIsNone(self.registry.last_read_receipt)
        self.assertFalse((self.root/'new.txt').exists())

    def test_later_creation_reinspects_current_state(self):
        self.assertIs(file_info(self.root,'new.txt')['exists'],False)
        (self.root/'new.txt').write_text('new')
        self.assertEqual(self.registry.call('file_info',{'path':'new.txt'}),{'path':'new.txt','type':'file','size_bytes':3})

    def test_denied_read_still_denied(self):
        from agent.safety import CapabilityPolicy
        r=create_default_registry(self.root,capabilities=CapabilityPolicy(read=False))
        self.assertEqual(r.call('file_info',{'path':'new.txt'})['status'],'denied')

    def test_absent_outside_and_sensitive_paths_still_rejected(self):
        for name in ['../outside','.git/missing','.env','.ssh/missing']:
            with self.assertRaises(ValueError):self.registry.call('file_info',{'path':name})

    def test_escaping_symlink_still_rejected(self):
        (self.root/'escape').symlink_to(self.root.parent/'outside-missing')
        with self.assertRaises(ValueError):self.registry.call('file_info',{'path':'escape'})

    def test_permission_error_does_not_become_absence(self):
        import os
        original=os.open
        def controlled(path,*args,**kw):
            if str(path)=='denied.txt':raise PermissionError('controlled permission failure')
            return original(path,*args,**kw)
        with patch('os.open',controlled):
            with self.assertRaises(PermissionError):file_info(self.root,'denied.txt')

    def test_custom_file_info_does_not_gain_missing_target_admission(self):
        self.registry._tools['file_info']=lambda **kw:{'exists':False}
        with self.assertRaises(FileNotFoundError):self.registry.call('file_info',{'path':'new.txt'})

    def test_missing_read_file_stays_failed(self):
        with self.assertRaises(FileNotFoundError):self.registry.call('read_file',{'path':'new.txt'})

    def test_cloud_metadata_requires_exact_path_allowlist_and_drops_other_fields(self):
        from agent.deepseek import DeepSeekBackend
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        cloud=DeepSeekBackend(api_key='fixture')
        messages=[Message('assistant',None,[ToolCall('info','file_info','{"path":"new.txt"}')]),
                  Message('tool',json.dumps({'ok':True,'result':{'path':'new.txt','exists':False,'observation':'target_not_found','unrelated':'PRIVATE_OTHER_BODY'}}),tool_call_id='info')]
        for paths in [(),('new.txt',)]:
            r=AgentSession(self.registry,cloud_backend=cloud,hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',paths)),
                hybrid_primary='cloud',hybrid_backends={'cloud':cloud})
            result=json.loads(r.hybrid.project_messages(messages)[-1].content)
            if paths:
                self.assertIs(result['result']['exists'],False)
                self.assertNotIn('verified',result)
            else:self.assertTrue(result['body_withheld'])
            self.assertNotIn('PRIVATE_OTHER_BODY',json.dumps(result))

    def test_project_credential_namespace_is_not_model_tool_data(self):
        from agent.tools import search_text
        secrets=self.root/'.localpilot'/'secrets';secrets.mkdir(parents=True)
        key=secrets/'deepseek.key';key.write_text('PRIVATE_FIXTURE_TOKEN')
        for tool,args in [('file_info',{'path':'.localpilot/secrets/deepseek.key'}),
                          ('read_file',{'path':'.localpilot/secrets/deepseek.key'}),
                          ('list_directory',{'path':'.localpilot/secrets'}),
                          ('file_info',{'path':'.localpilot/secrets/missing.key'}),
                          ('apply_patch',{'changes':[{'operation':'create','path':'.localpilot/secrets/new.key','content':'denied'}]})]:
            with self.assertRaises(ValueError):self.registry.call(tool,args)
        self.assertFalse(search_text(self.root,'PRIVATE_FIXTURE_TOKEN'))
        self.assertEqual(key.read_text(),'PRIVATE_FIXTURE_TOKEN')

    def test_symlink_to_project_credential_namespace_is_denied(self):
        folder=self.root/'.localpilot'/'secrets';folder.mkdir(parents=True)
        (folder/'deepseek.key').write_text('PRIVATE_FIXTURE_TOKEN')
        (self.root/'alias.txt').symlink_to(folder/'deepseek.key')
        with self.assertRaises(ValueError):self.registry.call('read_file',{'path':'alias.txt'})
