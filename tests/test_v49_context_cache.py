"""Safety/compatibility controls; these are not real-model outcomes."""
import json,unittest
from copy import deepcopy
from agent.backends import Message,ToolCall
from agent.context import transfer_context,ContextTooSmall,context_units
from agent.harness import HarnessPolicy
from agent.persistence import configuration
from tests.test_harness_context import fixture

class StablePrefixControls(unittest.TestCase):
    def messages(self):return [Message('system','stable host limits'),Message('user','original task'),Message('assistant',None,[ToolCall('r','read_file','{"path":"known.json"}')]),Message('tool','latest version',tool_call_id='r')]
    def test_exact_current_state_and_history_groups_survive(self):
        state=fixture();before=deepcopy(state);msgs=self.messages();orig=[m.to_dict() for m in msgs]
        old,_=transfer_context(msgs,[],30000,1000,working_state=state)
        new,_=transfer_context(msgs,[],30000,1000,working_state=state,stable_history_prefix=True)
        self.assertEqual([m.to_dict() for m in new[:-1]],orig)
        self.assertEqual(new[-1].to_dict(),old[1].to_dict());self.assertEqual(state,before)
        self.assertEqual([m.to_dict() for m in msgs],orig)
        state['generation']=2;state['approval_state']['pending_kind']='cloud_egress'
        next_view,_=transfer_context(msgs,[],30000,1000,working_state=state,stable_history_prefix=True)
        self.assertNotEqual(new[-1].content,next_view[-1].content)
        self.assertEqual(json.loads(next_view[-1].content.split('\n',1)[1]),state)
    def test_compaction_keeps_unknown_permissions_and_paired_tool_group(self):
        state=fixture();state['completed_steps']=[];msgs=self.messages();msgs.insert(2,Message('user','old '*5000))
        view,info=transfer_context(msgs,[],6000,1000,working_state=state,stable_history_prefix=True)
        self.assertIsNotNone(info);self.assertEqual(view[-1].content.split('\n',1)[1],json.dumps(state,ensure_ascii=False))
        self.assertEqual([m.role for m in view[-3:-1]],['assistant','tool']);self.assertLessEqual(context_units(view,[]),5000)
    def test_final_only_is_identical_and_critical_overflow_fails(self):
        state=fixture();a=transfer_context(self.messages(),[],30000,1000,working_state=state,final_only=True)
        b=transfer_context(self.messages(),[],30000,1000,working_state=state,final_only=True,stable_history_prefix=True)
        self.assertEqual([m.to_dict() for m in a[0]],[m.to_dict() for m in b[0]])
        with self.assertRaises(ContextTooSmall):transfer_context(self.messages(),[],100,20,working_state=state,stable_history_prefix=True)
    def test_host_boolean_and_default_legacy_fingerprint(self):
        with self.assertRaises(ValueError):HarnessPolicy(cache_stable_prefix=1)
        from agent.session import AgentSession
        from agent.registry import create_default_registry
        from agent.stabilization import HostVerification
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            r=AgentSession(create_default_registry(d),harness_policy=HarnessPolicy(),verification_callback=lambda *a:HostVerification('passed','test'))
            self.assertNotIn('cache_stable_prefix',configuration(r)['harness']['policy']);r.close()
            r=AgentSession(create_default_registry(d),harness_policy=HarnessPolicy(cache_stable_prefix=True),verification_callback=lambda *a:HostVerification('passed','test'))
            self.assertTrue(configuration(r)['harness']['policy']['cache_stable_prefix']);r.close()
if __name__=='__main__':unittest.main()
