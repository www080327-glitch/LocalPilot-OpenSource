"""Parent ownership enforcement before approval/intent, never model evidence."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from agent.session import AgentSession
from agent.registry import create_default_registry
from agent.harness import HarnessPolicy,TaskContract
from agent.finalization import FinalizationPolicy
from agent.stabilization import HostVerification
from tests.test_runtime_api import Backend,call
class ParentRoleGuard(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'owned.txt').write_text('original')
        self.s=AgentSession(create_default_registry(self.root,permission_mode='approve-mutations'),backend=Backend(),policy='cloud-only',streaming=False,harness_policy=HarnessPolicy(),task_contract=TaskContract(output_paths=('owned.txt','parent.txt'),child_output_groups=(('owned.txt',),),parent_output_paths=('parent.txt',)),finalization_policy=FinalizationPolicy(),completion_check=lambda *a:HostVerification('failed','control'),verification_callback=lambda *a:HostVerification('failed','control'))
    def tearDown(self):self.s.close();self.temp.cleanup()
    def test_child_owned_update_rejected_before_approval_or_dispatch(self):
        with patch.object(self.s.registry,'call',wraps=self.s.registry.call) as dispatch:
            r=self.s._dispatch(call('apply_patch',{'changes':[{'operation':'update','path':'owned.txt','old_text':'original','new_text':'tainted'}]},'bad'))
        self.assertFalse(r['ok']);self.assertFalse(r['result']['action_sent']);self.assertFalse(r['result']['action_may_have_applied']);self.assertEqual(r['result']['stage'],'not_dispatched');dispatch.assert_not_called();self.assertIsNone(self.s.pending_approval);self.assertIsNone(self.s._durable_intent);self.assertEqual((self.root/'owned.txt').read_text(),'original')
    def test_alias_and_mixed_batch_cannot_bypass_role_guard(self):
        r=self.s._dispatch(call('apply_patch',{'changes':[{'operation':'create','path':'parent.txt','content':'allowed'},{'operation':'update','path':'./owned.txt','old_text':'original','new_text':'tainted'}]},'batch'))
        self.assertFalse(r['result']['action_sent']);self.assertFalse((self.root/'parent.txt').exists());self.assertEqual((self.root/'owned.txt').read_text(),'original')
    def test_parent_owned_patch_still_requires_approval(self):
        r=self.s._dispatch(call('apply_patch',{'changes':[{'operation':'create','path':'parent.txt','content':'allowed'}]},'parent'))
        self.assertEqual(r['result']['status'],'approval_required');self.assertIsNotNone(self.s.pending_approval);self.assertFalse((self.root/'parent.txt').exists())
    def test_undeclared_spelling_does_not_create_an_ownership_escape(self):
        r=self.s._dispatch(call('apply_patch',{'changes':[{'operation':'create','path':'OWNED.txt','content':'escape'}]},'alias'))
        self.assertFalse(r['result']['action_sent']);self.assertIsNone(self.s.pending_approval);self.assertEqual((self.root/'owned.txt').read_text(),'original')
    def test_child_actor_is_not_treated_as_parent(self):
        self.s._worker_id='1.1'
        r=self.s._dispatch(call('apply_patch',{'changes':[{'operation':'update','path':'owned.txt','old_text':'original','new_text':'changed'}]},'child'))
        self.assertEqual(r['result']['status'],'approval_required');self.assertEqual((self.root/'owned.txt').read_text(),'original')
if __name__=='__main__':unittest.main()
