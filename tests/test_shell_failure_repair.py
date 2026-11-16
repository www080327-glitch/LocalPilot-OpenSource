"""Known subprocess exits remain failures; timeouts retain UNKNOWN."""
from pathlib import Path
import tempfile
import unittest
import sys
from agent.registry import create_default_registry
from agent.engine_v5 import EngineV5Policy
from agent.session import AgentSession, SessionBudgets
from agent.persistence import recovery_class
from localpilot_service.desktop_sessions import apply_options
from tests.test_runtime_api import Backend, answer, call

class ShellFailureRepairTests(unittest.TestCase):
    def full_runtime(self, root, *steps):
        runtime = AgentSession(create_default_registry(root), cloud_backend=Backend(*steps), policy='cloud-only',
            engine_policy=EngineV5Policy(), budgets=SessionBudgets(max_steps=10, max_tool_calls=10, max_token_units=2000000))
        apply_options(runtime, {'permission_mode':'full', 'agent_profile':'standard', 'prompt_revision':2,
            'scope_revision':3, 'execution_budget':'standard'})
        return runtime

    @unittest.skipUnless(sys.platform in {'darwin', 'linux'}, 'NOT_RUN: requires native POSIX host Shell')
    def test_successful_timeout_only_retry_settles_rejected_proposal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            command = 'printf proof >> proof.txt'
            runtime = self.full_runtime(root,
                answer(None, call('shell', {'command':command, 'timeout':120000}, 'invalid')),
                answer(None, call('shell', {'command':command, 'timeout':120}, 'corrected')),
                answer(None, call('read_file', {'path':'proof.txt'}, 'verify')),
                answer('Wrote proof.txt and read it back.'))
            try:
                final = runtime.run_turn('Write proof.txt once and read it back.')
                self.assertEqual(final.status, 'completed')
                self.assertEqual((root/'proof.txt').read_text(), 'proof')
                rejected, successful = runtime.tool_history[:2]
                self.assertFalse(rejected['payload']['ok'])
                self.assertEqual(rejected['payload']['error']['type'], 'schema_validation')
                self.assertEqual(rejected['payload']['result']['stage'], 'not_dispatched')
                self.assertFalse(rejected['payload']['result']['action_sent'])
                self.assertFalse(rejected['payload']['result']['action_may_have_applied'])
                self.assertEqual(rejected['side_effect_status'], 'not_completed')
                self.assertTrue(successful['payload']['result']['process_completed'])
                self.assertTrue(successful['payload']['result']['action_sent'])
                self.assertFalse(successful['receipt_reused'])
                self.assertEqual(successful['repaired_proposals'], [rejected['receipt_id']])
                self.assertEqual(recovery_class(runtime), 'SAFE_TO_RESUME')
            finally:
                runtime.close()

    @unittest.skipUnless(sys.platform in {'darwin', 'linux'}, 'NOT_RUN: requires native POSIX host Shell')
    def test_unexecuted_rejected_shell_remains_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            runtime = self.full_runtime(root,
                answer(None, call('shell', {'command':'printf proof >> proof.txt', 'timeout':120000}, 'invalid')),
                answer('Wrote proof.txt.'))
            try:
                final = runtime.run_turn('Write proof.txt once.')
                self.assertEqual(final.status, 'incomplete')
                self.assertFalse((root/'proof.txt').exists())
                self.assertEqual(len(runtime.tool_history), 1)
                self.assertFalse(runtime.tool_history[0]['payload']['result']['action_sent'])
                self.assertNotIn('repaired_proposals', runtime.tool_history[0])
            finally:
                runtime.close()

    @unittest.skipUnless(sys.platform in {'darwin', 'linux'}, 'NOT_RUN: requires native POSIX host Shell')
    def test_reused_shell_success_does_not_settle_later_rejected_proposal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            command = 'printf proof >> proof.txt'
            successful = answer(None, call('shell', {'command':command, 'timeout':120}, 'original'))
            runtime = self.full_runtime(root, successful,
                answer(None, call('shell', {'command':command, 'timeout':120000}, 'invalid')),
                successful, answer('Wrote proof.txt.'))
            try:
                final = runtime.run_turn('Write proof.txt once.')
                self.assertEqual(final.status, 'incomplete')
                self.assertEqual((root/'proof.txt').read_text(), 'proof')
                reused = runtime.tool_history[2]
                self.assertTrue(reused['payload']['result']['process_completed'])
                self.assertTrue(reused['receipt_reused'])
                self.assertNotIn('repaired_proposals', reused)
            finally:
                runtime.close()

    @unittest.skipUnless(sys.platform in {'darwin', 'linux'}, 'NOT_RUN: requires native POSIX host Shell')
    def test_different_shell_command_does_not_settle_rejected_proposal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            runtime = self.full_runtime(root,
                answer(None, call('shell', {'command':'printf proof >> proof.txt', 'timeout':120000}, 'invalid')),
                answer(None, call('shell', {'command':'printf other >> other.txt', 'timeout':120}, 'different')),
                answer(None, call('read_file', {'path':'other.txt'}, 'verify')),
                answer('Wrote other.txt and read it back.'))
            try:
                final = runtime.run_turn('Write proof.txt once and read it back.')
                self.assertEqual(final.status, 'incomplete')
                self.assertFalse((root/'proof.txt').exists())
                self.assertEqual((root/'other.txt').read_text(), 'other')
                successful = runtime.tool_history[1]
                self.assertTrue(successful['payload']['result']['process_completed'])
                self.assertNotIn('repaired_proposals', successful)
            finally:
                runtime.close()

    @unittest.skipUnless(sys.platform in {'darwin', 'linux'}, 'NOT_RUN: requires native POSIX host Shell')
    def test_full_parent_recognizes_child_timeout_only_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            command = 'printf proof >> proof.txt'
            runtime = self.full_runtime(root,
                answer(None, call('delegate', {'task':'Write proof.txt once.',
                    'backend_preference':'cloud', 'read_only':False}, 'delegate')),
                answer(None, call('shell', {'command':command, 'timeout':120000}, 'invalid')),
                answer(None, call('shell', {'command':command, 'timeout':120}, 'corrected')),
                answer('Child wrote proof.txt.'),
                answer(None, call('read_file', {'path':'proof.txt'}, 'verify')),
                answer('Collected child output and read proof.txt.'))
            try:
                final = runtime.run_turn('Delegate writing proof.txt, then read it back.')
                self.assertEqual((root/'proof.txt').read_text(), 'proof')
                child = runtime.subagents[0]
                self.assertEqual(child['status'], 'completed')
                self.assertEqual(child['obligation_status'], 'resolved')
                rejected, successful = child['receipts'][:2]
                self.assertEqual(successful['repaired_proposals'], [rejected['receipt_id']])
                self.assertEqual(final.status, 'completed')
                projected = [r for r in runtime.tool_history if r.get('worker_id') == child['id']]
                self.assertEqual(projected[1]['repaired_proposals'], [projected[0]['receipt_id']])
                self.assertFalse(projected[0]['payload']['result']['action_sent'])
            finally:
                runtime.close()

    @unittest.skipUnless(sys.platform == "darwin", "NOT_RUN: requires native macOS host Shell/Seatbelt")
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
    @unittest.skipUnless(sys.platform in {"darwin", "linux"}, "NOT_RUN: requires native POSIX host Shell")
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
