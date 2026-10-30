"""Known subprocess exits remain failures; timeouts retain UNKNOWN."""
from pathlib import Path
import tempfile
import unittest
from agent.registry import create_default_registry
from agent.session import AgentSession
from agent.persistence import recovery_class
from localpilot_service.desktop_sessions import apply_options
from tests.test_runtime_api import Backend, answer, call

class ShellFailureRepairTests(unittest.TestCase):
    def test_invalid_macos_flag_can_be_inspected_and_corrected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            backend=Backend(
                answer(None,call('shell',{'command':'mkdir -p work && touch -n work/note.md'},'bad')),
                answer(None,call('list_entries',{'path':'work'},'inspect')),
                answer(None,call('apply_patch',{'changes':[{'path':'work/note.md','operation':'create','content':'real output'}]},'repair')),
                answer(None,call('read_file',{'path':'work/note.md'},'verify')),
                answer('Created and read back work/note.md.'))
            runtime=AgentSession(create_default_registry(root),cloud_backend=backend,policy='cloud-only')
            apply_options(runtime,{'permission_mode':'full','agent_profile':'standard','prompt_revision':2,'scope_revision':3})
            try:
                final=runtime.run_turn('Create work/note.md and read it back.')
                self.assertEqual(final.status,'completed')
                self.assertEqual((root/'work/note.md').read_text(),'real output')
                failed=runtime.tool_history[0]
                self.assertEqual(failed['payload']['result']['exit_code'],1)
                self.assertEqual(failed['side_effect_status'],'failed_process')
                self.assertTrue(failed['payload']['result']['partial_effects_possible'])
                self.assertEqual(recovery_class(runtime),'SAFE_TO_RESUME')
                self.assertEqual(sum(r['name']=='shell' for r in runtime.tool_history),1)
            finally:runtime.close()
    def test_timeout_still_preserves_uncertain_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            backend=Backend(answer(None,call('shell',{'command':'printf partial > partial.txt; sleep 2','timeout':0.05},'timeout')),answer('Operation timed out.'))
            runtime=AgentSession(create_default_registry(root),cloud_backend=backend,policy='cloud-only')
            apply_options(runtime,{'permission_mode':'full','agent_profile':'standard','prompt_revision':2,'scope_revision':3})
            try:
                runtime.run_turn('Run the scoped timeout fixture.')
                self.assertEqual(recovery_class(runtime),'UNKNOWN_BLOCKED')
                self.assertTrue(runtime.tool_history[0]['payload']['result']['action_may_have_applied'])
            finally:runtime.close()

if __name__=='__main__':unittest.main()
