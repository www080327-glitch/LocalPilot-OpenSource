"""Real OS/files with scripted model/host. No model or DSH GUI claim."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
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
    def test_full_writes_outside_and_reads_as_current_os_user(self):
        r=self.registry('full');p=self.out/'created'
        self.assertEqual(r.call('apply_patch',{'changes':[{'operation':'create','path':str(p),'content':'real'}]})['status'],'ok')
        self.assertEqual(p.read_text(),'real')
        self.assertIn('PRIVATE_FIXTURE',json.dumps(r.call('read_file',{'path':str(self.secret/'token')})))
    def test_workspace_shell_executes_within_scope_without_extra_approval(self):
        r=self.registry();args={'command':'printf real > created.txt'}
        result=r.call('shell',args)
        self.assertEqual(result['exit_code'],0,result)
        self.assertEqual((self.work/'created.txt').read_text(),'real')
        self.assertEqual(result['verification'],'NOT_RUN')
    def test_shell_unicode_workspace_has_the_same_real_write_scope(self):
        dest=self.root/'工作区';self.work.rename(dest);self.work=dest
        result=self.registry().call('shell',{'command':'printf unicode-ok > created.txt'},approved=True)
        self.assertEqual(result['exit_code'],0,result);self.assertEqual((self.work/'created.txt').read_text(),'unicode-ok')
    def test_shell_OS_write_scope_and_full(self):
        # macOS allows a dedicated OS temp root in workspace mode. An outside
        # fixture under the same temp root cannot test the workspace boundary.
        with tempfile.TemporaryDirectory(dir=Path.home()) as separate:
            target=Path(separate)/'created'
            args={'command':"printf forbidden > '"+str(target)+"'"}
            denied=self.registry().call('shell',args,approved=True)
            self.assertNotEqual(denied['exit_code'],0);self.assertFalse(target.exists())
            allowed=self.registry('full').call('shell',args)
            self.assertEqual(allowed['exit_code'],0,allowed);self.assertEqual(target.read_text(),'forbidden')
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
    def test_full_shell_reads_with_os_rights_and_reports_network_mode(self):
        r=self.registry('full')
        result=r.call('shell',{'command':"cat '"+str(self.secret/'token')+"'"})
        self.assertEqual(result['exit_code'],0,result)
        self.assertIn('PRIVATE_FIXTURE',result['stdout'])
        self.assertEqual(result['network'],'available')
        # External DNS/network availability is an integration concern, not a
        # deterministic permission assertion.
    def test_timeout_retains_uncertain_effect_and_no_replay(self):
        result=self.registry('full').call('shell',{'command':'printf partial > partial.txt; sleep 3','timeout':.1})
        self.assertEqual(result['status'],'timeout');self.assertTrue(result['action_may_have_applied']);self.assertFalse(result['replay_allowed'])
        self.assertEqual((self.work/'partial.txt').read_text(),'partial')
    def test_full_network_permission_and_public_url_validation(self):
        r=self.registry('full',revision=3)
        self.assertIn('http_get',r._tools)
        self.assertEqual(r.gateway.mode,'full-permission')
        # An external DNS response can be rewritten by a corporate resolver.
        # Exercise the real validation path without requiring a network call.
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
    def test_cancel_running_shell_retains_unknown_receipt(self):
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        from agent.persistence import recovery_class
        b=Backend(answer('',call('shell',{'command':'printf partial > shell.txt; exec >/dev/null 2>&1; sleep 30'})))
        s=AgentSession(self.registry('full',revision=3),cloud_backend=b,policy='cloud-only',hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',())))
        worker=threading.Thread(target=lambda:s.run_turn('Run the fixture'))
        worker.start();deadline=time.monotonic()+5
        while not (self.work/'shell.txt').exists() and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue((self.work/'shell.txt').exists())
        s.request_cancel();worker.join(3)
        self.assertFalse(worker.is_alive())
        receipt=next(r for r in s.tool_history if r['name']=='shell')
        self.assertEqual(receipt['payload']['result']['status'],'cancelled')
        self.assertEqual(receipt['side_effect_status'],'unknown')
        self.assertEqual(recovery_class(s),'UNKNOWN_BLOCKED')
        s.close()

    def test_observed_nonzero_shell_does_not_become_unknown(self):
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        from agent.persistence import recovery_class
        b=Backend(answer('',call('shell',{'command':'exit 3'})),answer('The command failed.'))
        s=AgentSession(self.registry('full',revision=3),cloud_backend=b,policy='cloud-only',hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',())))
        s.run_turn('Run the fixture')
        receipt=next(r for r in s.tool_history if r['name']=='shell')
        self.assertEqual(receipt['side_effect_status'],'failed_process')
        self.assertNotEqual(recovery_class(s),'UNKNOWN_BLOCKED')
        s.close()
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
