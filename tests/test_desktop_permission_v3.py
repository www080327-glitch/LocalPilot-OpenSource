"""Permission behavior on real files/processes, scripted model only."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_service.desktop_sessions import apply_options
from tests.test_runtime_api import Backend, answer, call


class PermissionV3Tests(unittest.TestCase):
    def setUp(self):
        cache=Path.home()/'.cache/localpilot-permission-checks'
        cache.mkdir(parents=True,exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=cache)
        self.root = Path(self.tmp.name).resolve()
        self.workspace = self.root/'workspace'
        self.workspace.mkdir()
        self.sessions = []
    def tearDown(self):
        for s in self.sessions: s.close()
        self.tmp.cleanup()
    def runtime(self, mode, backend=None):
        runtime = AgentSession(create_default_registry(self.workspace), cloud_backend=backend or Backend(answer('done')), policy='cloud-only')
        self.sessions.append(runtime)
        apply_options(runtime, {'permission_mode':mode,'agent_profile':'standard','prompt_revision':2,'scope_revision':3})
        return runtime
    def patch(self, path, text='proof'):
        return {'changes':[{'path':str(path),'operation':'create','content':text}]}
    def test_full_writes_and_reads_outside_workspace_without_approval(self):
        registry=self.runtime('full').registry
        target=self.root/'outside.txt'
        result=registry.call('apply_patch', self.patch(target))
        self.assertNotEqual(result.get('status'),'approval_required')
        self.assertEqual(target.read_text(),'proof')
        self.assertEqual(registry.call('read_file',{'path':str(target)}),'proof')
    def test_full_reads_dotfiles_and_tool_body_reaches_cloud(self):
        (self.workspace/'.env').write_text('DEMO_PLACEHOLDER=not-a-real-secret')
        backend=Backend(answer(None,call('read_file',{'path':'.env'},'read')),answer('read complete'))
        runtime=self.runtime('full',backend)
        result=runtime.run_turn('Read the demo file')
        self.assertNotEqual(result.status,'requires_approval')
        payload=[m.content for m in backend.requests[-1]['messages'] if m.role=='tool']
        self.assertTrue(any('DEMO_PLACEHOLDER' in str(value) for value in payload))
        self.assertFalse(any('body_withheld' in str(value) for value in payload))
    def test_workspace_writes_inside_and_asks_outside(self):
        registry=self.runtime('workspace').registry
        registry.call('apply_patch', self.patch('inside.txt'))
        self.assertEqual((self.workspace/'inside.txt').read_text(),'proof')
        outside=self.root/'outside.txt'
        self.assertEqual(registry.call('apply_patch', self.patch(outside))['status'],'approval_required')
        self.assertFalse(outside.exists())
    def test_request_mode_reads_without_prompt_and_asks_before_write(self):
        registry=self.runtime('request').registry
        target=self.root/'outside.txt';target.write_text('readable')
        self.assertEqual(registry.call('read_file',{'path':str(target)}),'readable')
        self.assertEqual(registry.call('apply_patch',self.patch('inside.txt'))['status'],'approval_required')
        self.assertFalse((self.workspace/'inside.txt').exists())
    def test_read_only_lists_files_but_cannot_write(self):
        registry=self.runtime('isolated').registry
        (self.workspace/'hello.csv').write_text('x\n1')
        self.assertTrue(any(x['name']=='hello.csv' for x in registry.call('list_entries',{'path':'.'})))
        with self.assertRaises(PermissionError):registry.call('apply_patch',self.patch('blocked.txt'))
    def test_full_shell_runs_and_writes_a_real_file(self):
        registry=self.runtime('full').registry
        import shlex
        target=self.root/'shell-output.txt'
        result=registry.call('shell',{'command':'printf LOCALPILOT_FULL > '+shlex.quote(str(target))})
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(target.read_text(),'LOCALPILOT_FULL')
        self.assertEqual(result['network'],'available')
    def test_workspace_cannot_select_unconfined_shell_without_approval(self):
        registry=self.runtime('workspace').registry
        result=registry.call('shell',{'command':'printf test','access':'full'})
        self.assertEqual(result['status'],'approval_required')
    def test_workspace_allows_platform_temporary_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp).resolve()/'authorized-temp.txt'
            self.runtime('workspace').registry.call('apply_patch',self.patch(target))
            self.assertEqual(target.read_text(),'proof')
    def test_read_only_shell_can_read_but_os_denies_writes(self):
        registry=self.runtime('isolated').registry
        result=registry.call('shell',{'command':'pwd'})
        self.assertEqual(result['exit_code'],0)
        denied=registry.call('shell',{'command':'printf blocked > cannot-write.txt'})
        self.assertNotEqual(denied['exit_code'],0)
        self.assertFalse((self.workspace/'cannot-write.txt').exists())
    def test_permission_switch_preserves_original_conversation_and_context(self):
        from tests.test_desktop_product import DesktopProductTests
        case=DesktopProductTests('test_four_modes_persist_and_minimal_is_a_real_agent');case.setUp()
        try:
            session=case.session('request')
            first=case.done(case.codex.submit('Original task: remember ORBIT.',session_id=session['id'],idempotency_key='permission-first'))
            runtime=case.service.sessions[session['id']].runtime
            before=[m.to_dict() for m in runtime.messages if m.role!='system']
            updated=case.operator.request('/localpilot/v1/desktop-sessions/'+session['id']+'/profile',{'client_subject':'codex','agent_profile':'standard','expected_profile':'standard','permission_mode':'full','expected_permission_mode':'request'})
            self.assertEqual(updated['id'],session['id'])
            self.assertEqual([m.to_dict() for m in runtime.messages if m.role!='system'],before)
            second=case.done(case.codex.submit('Continue the original task.',session_id=session['id'],idempotency_key='permission-second'))
            self.assertEqual(first['session_id'],second['session_id'])
            self.assertTrue(any('ORBIT' in str(m.content) for m in case.backend.requests[-1]['messages']))
        finally:case.tearDown()

if __name__=='__main__':unittest.main()
