"""Real OS/files with scripted model/host. No model or DSH GUI claim."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent.registry import create_default_registry
from agent.scope_permissions import configure
from agent.host_tools import register, public_get
from agent.session import AgentSession
from tests.test_runtime_api import Backend,answer,call


class HostToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.work=self.root/'work';self.work.mkdir();self.out=self.root/'outside';self.out.mkdir()
        self.secret=self.root/'private';self.secret.mkdir();(self.secret/'token').write_text('PRIVATE_FIXTURE')
        (self.out/'source').write_text('PUBLIC_FIXTURE')
    def tearDown(self):self.temp.cleanup()
    def registry(self,mode='workspace',revision=2):
        r=create_default_registry(self.work,permission_mode={'request':'approve-mutations','workspace':'workspace-auto','full':'full-permission','isolated':'approve-all'}[mode],file_operations=True)
        configure(r,mode,[self.secret],revision);register(r,mode,[self.secret]);return r
    def test_new_read_scope_and_legacy_preserved(self):
        args={'path':str(self.out/'source')}
        self.assertEqual(self.registry(revision=1).call('read_file',args)['status'],'approval_required')
        for mode in ['request','workspace','full']:
            self.assertIn('PUBLIC_FIXTURE',json.dumps(self.registry(mode).call('read_file',args)))
    def test_full_writes_outside_and_private_remains_forbidden(self):
        r=self.registry('full');p=self.out/'created'
        self.assertEqual(r.call('apply_patch',{'changes':[{'operation':'create','path':str(p),'content':'real'}]})['status'],'ok')
        self.assertEqual(p.read_text(),'real')
        with self.assertRaises(PermissionError):r.call('read_file',{'path':str(self.secret/'token')})
    def test_shell_approval_then_actual_effect(self):
        r=self.registry();args={'command':'printf real > created.txt'}
        self.assertEqual(r.call('shell',args)['status'],'approval_required');self.assertFalse((self.work/'created.txt').exists())
        result=r.call('shell',args,approved=True)
        self.assertEqual(result['exit_code'],0,result);self.assertEqual((self.work/'created.txt').read_text(),'real')
        self.assertEqual(result['verification'],'NOT_RUN')
    def test_shell_unicode_workspace_has_the_same_real_write_scope(self):
        dest=self.root/'工作区';self.work.rename(dest);self.work=dest
        result=self.registry().call('shell',{'command':'printf unicode-ok > created.txt'},approved=True)
        self.assertEqual(result['exit_code'],0,result);self.assertEqual((self.work/'created.txt').read_text(),'unicode-ok')
    def test_shell_OS_write_scope_and_full(self):
        args={'command':"printf forbidden > '"+str(self.out/'created')+"'"}
        denied=self.registry().call('shell',args,approved=True)
        self.assertNotEqual(denied['exit_code'],0);self.assertFalse((self.out/'created').exists())
        allowed=self.registry('full').call('shell',args)
        self.assertEqual(allowed['exit_code'],0,allowed);self.assertEqual((self.out/'created').read_text(),'forbidden')
    def test_shell_one_action_scope_escalation(self):
        r=self.registry('request');target=self.out/'escalated'
        args={'command':"printf approved > '"+str(target)+"'",'access':'full'}
        self.assertEqual(r.call('shell',args)['status'],'approval_required');self.assertFalse(target.exists())
        result=r.call('shell',args,approved=True)
        self.assertEqual(result['exit_code'],0,result);self.assertEqual(target.read_text(),'approved')
        self.assertEqual(r.call('shell',{'command':'printf next'})['status'],'approval_required')
    def test_strict_shell_cannot_escalate_or_mutate(self):
        r=self.registry('isolated')
        with self.assertRaises(PermissionError):r.call('shell',{'command':'printf no','access':'full'},approved=True)
        result=r.call('shell',{'command':'printf no > denied'},approved=True)
        self.assertNotEqual(result['exit_code'],0);self.assertFalse((self.work/'denied').exists())
    def test_shell_protected_reads_and_network(self):
        r=self.registry('full')
        result=r.call('shell',{'command':"cat '"+str(self.secret/'token')+"'"})
        self.assertNotEqual(result['exit_code'],0);self.assertNotIn('PRIVATE_FIXTURE',result['stdout'])
        result=r.call('shell',{'command':'/usr/bin/curl --connect-timeout 1 https://example.com'})
        self.assertNotEqual(result['exit_code'],0)
    def test_timeout_retains_uncertain_effect_and_no_replay(self):
        result=self.registry('full').call('shell',{'command':'printf partial > partial.txt; sleep 3','timeout':.1})
        self.assertEqual(result['status'],'timeout');self.assertTrue(result['action_may_have_applied']);self.assertFalse(result['replay_allowed'])
        self.assertEqual((self.work/'partial.txt').read_text(),'partial')
    def test_network_separate_exact_approval_and_no_local_network(self):
        r=self.registry('full')
        result=r.call('http_get',{'url':'https://example.com/'})
        self.assertEqual(result['status'],'approval_required');self.assertFalse(result.get('action_sent',False))
        for url in ['http://example.com','https://127.0.0.1/','https://user:password@example.com/']:
            with self.assertRaises(ValueError):public_get(self.work,url)
    def test_model_text_cannot_bypass_rejected_shell(self):
        p=self.work/'created.txt'
        b=Backend(answer('',call('shell',{'command':'printf real > created.txt'})),answer('All done successfully'))
        s=AgentSession(self.registry(),backend=b,policy='cloud-only')
        first=s.run_turn('Create the fixture');self.assertEqual(first.status,'approval_required')
        final=s.reject()
        self.assertNotEqual(final.status,'completed');self.assertFalse(p.exists());self.assertEqual(len(b.requests),1)
    def test_hybrid_shell_uses_one_approval_and_the_actual_receipt(self):
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        b=Backend(answer('',call('shell',{'command':'printf hybrid-ok > shell.txt'})),answer('Done'))
        s=AgentSession(self.registry('request'),cloud_backend=b,policy='cloud-only',hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',())))
        self.assertEqual(s.run_turn('Create the public fixture').status,'approval_required')
        self.assertFalse((self.work/'shell.txt').exists())
        result=s.approve();self.assertEqual(result.status,'completed');self.assertEqual((self.work/'shell.txt').read_text(),'hybrid-ok')
        self.assertEqual(len([r for r in s.tool_history if r['name']=='shell']),1)
    def test_hybrid_uncertain_shell_never_becomes_completed(self):
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        from agent.persistence import recovery_class
        b=Backend(answer('',call('shell',{'command':'printf partial > shell.txt; sleep 2','timeout':.05})),answer('Everything is successfully completed'))
        s=AgentSession(self.registry('full'),cloud_backend=b,policy='cloud-only',hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',())))
        result=s.run_turn('Create the public fixture')
        self.assertNotEqual(result.status,'completed');self.assertEqual((self.work/'shell.txt').read_text(),'partial')
        self.assertEqual(recovery_class(s),'UNKNOWN_BLOCKED')
    def test_outside_read_keeps_version_receipt_without_cloud_body_disclosure(self):
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        from agent.finalization import FinalizationPolicy
        secret='PRIVATE_GENERATED_BODY_NEVER_IN_CLOUD'
        p=self.out/'private-body';p.write_text(secret)
        b=Backend(answer('',call('read_file',{'path':str(p)})),answer('Read operation finished; body withheld'))
        s=AgentSession(self.registry('full'),cloud_backend=b,policy='cloud-only',hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',())),finalization_policy=FinalizationPolicy())
        result=s.run_turn('Read the specified outside file without disclosing its body')
        self.assertEqual(result.status,'completed')
        read=s.tool_history[0]['read_receipt'];self.assertEqual(read['version']['path'],str(p));self.assertEqual(read['coverage']['kind'],'full_file')
        self.assertEqual(s._completion['obligations']['unknown_receipts'],0)
        sent=json.dumps([[m.to_dict() for m in r['messages']] for r in b.requests])
        self.assertNotIn(secret,sent)
