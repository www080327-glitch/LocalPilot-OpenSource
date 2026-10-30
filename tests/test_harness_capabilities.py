"""Proposed V4.8 controls; move into tests only with the product patch."""
from pathlib import Path
import tempfile
import unittest
from agent.harness import HarnessPolicy
from agent.registry import create_default_registry
from agent.session import AgentSession
from agent.safety import CapabilityPolicy
from agent.hybrid import HybridPolicy,CloudEgressPolicy
from tests.test_runtime_api import Backend

class HarnessCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def session(self,caps,harness=True,hybrid=False):
        backend=Backend()
        kwargs={"hybrid_policy":HybridPolicy(CloudEgressPolicy("CLOUD_ALLOWED")),"hybrid_backends":{"cloud":backend},"hybrid_primary":"cloud"} if hybrid else {}
        return AgentSession(create_default_registry(self.root,capabilities=caps),cloud_backend=backend,
            harness_policy=HarnessPolicy() if harness else None,**kwargs)
    def names(self,s):return {v["function"]["name"] for v in s._schemas()}
    def test_disabled_execution_not_advertised(self):
        s=self.session(CapabilityPolicy(execute=False));self.assertNotIn("execute",self.names(s));s.close()
    def test_hybrid_execute_stays_unqualified_even_with_execute_capability(self):
        s=self.session(CapabilityPolicy(execute=True),hybrid=True);self.assertNotIn("execute",self.names(s));s.close()
    def test_readonly_retains_reads_and_hides_writes(self):
        s=self.session(CapabilityPolicy(read_only=True,execute=True));names=self.names(s)
        self.assertIn("read_file",names);self.assertNotIn("apply_patch",names);self.assertNotIn("execute",names);s.close()
    def test_approval_does_not_hide_permitted_mutation(self):
        s=self.session(CapabilityPolicy(write=True));self.assertIn("apply_patch",self.names(s));s.close()
    def test_execute_permission_is_independent_of_write_permission(self):
        s=self.session(CapabilityPolicy(write=False,execute=True));self.assertIn("execute",self.names(s));self.assertNotIn("apply_patch",self.names(s));s.close()
    def test_final_only_does_not_advertise_any_tool(self):
        s=self.session(CapabilityPolicy(execute=True));s._finalizing=True;self.assertEqual(self.names(s),set());s.close()
    def test_nonoptin_legacy_advertisement_unchanged(self):
        s=self.session(CapabilityPolicy(execute=False),harness=False);self.assertIn("execute",self.names(s));s.close()
    def test_host_read_capability_is_respected(self):
        s=self.session(CapabilityPolicy(read=False));self.assertNotIn("read_file",self.names(s));s.close()

if __name__=="__main__":unittest.main()
