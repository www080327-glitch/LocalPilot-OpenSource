"""Real filesystem + HTTP/SQLite controls with scripted proposals; not model E2E."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from agent.registry import create_default_registry
from agent.scope_permissions import configure, proposal
from agent.safety import CapabilityPolicy
from localpilot_service.desktop_sessions import apply_options
from tests.test_agent_service import AgentServiceTests as Base
from tests.test_runtime_api import Backend, answer, call

class ScopeFiles(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.work=self.root/'work';self.work.mkdir();self.out=self.root/'outside';self.out.mkdir()
        self.src=self.out/'source.txt';self.src.write_text('real file bytes')
        self.sha=hashlib.sha256(self.src.read_bytes()).hexdigest()
    def tearDown(self):self.tmp.cleanup()
    def registry(self, mode='workspace', **kw):
        r=create_default_registry(self.work,permission_mode={'workspace':'workspace-auto','request':'approve-mutations','isolated':'approve-all','full':'full-permission'}[mode],file_operations=True,**kw)
        configure(r,mode,[self.root/'private']);return r
    def args(self):return dict(source=str(self.src),destination=str(self.out/'moved.txt'),expected_sha256=self.sha)
    def test_exact_once_scope_does_not_persist_or_approve_another_operation(self):
        r=self.registry();args=self.args();before=self.src.stat()
        req=r.call('move_file',args);self.assertEqual(req['status'],'approval_required');self.assertTrue(self.src.exists())
        value=r.call('move_file',args,scope_approval=req['scope_request'])
        self.assertEqual(value['verification'],'passed');self.assertFalse(self.src.exists());self.assertEqual((self.out/'moved.txt').stat().st_ino,before.st_ino)
        self.assertEqual(r.workspace_root,self.work)
        self.assertEqual(r.call('read_file',{'path':str(self.out/'moved.txt')})['status'],'approval_required')
        with self.assertRaises(PermissionError):r.call('move_file',args,scope_approval=req['scope_request'])
    def test_file_or_parent_identity_and_arguments_invalidate_approval(self):
        for change in ('bytes','parent','args'):
            with self.subTest(change=change):
                r=self.registry();args=self.args();request=proposal(r,'copy_file',args)
                if change=='bytes':self.src.write_text('changed')
                elif change=='parent':self.out.rename(self.root/'old');self.out.mkdir();self.src=self.out/'source.txt';self.src.write_text('real file bytes')
                else:args['destination']=str(self.out/'other.txt')
                with self.assertRaises(PermissionError):r.call('copy_file',args,scope_approval=request)
                self.assertFalse((self.out/'moved.txt').exists())
    def test_private_symlink_capability_and_plan_cannot_be_escalated(self):
        private=self.root/'private';private.mkdir();(private/'note').write_text('secret')
        link=self.out/'link';link.symlink_to(private,target_is_directory=True)
        for path in (private/'note',link/'note'):
            with self.assertRaises(PermissionError):proposal(self.registry(),'read_file',{'path':str(path)})
        for kw in ({'capabilities':CapabilityPolicy(write=False)}, {'plan_read_only':True}):
            with self.assertRaises(PermissionError):proposal(self.registry(**kw),'move_file',self.args())
        with self.assertRaises(PermissionError):proposal(self.registry('isolated'),'read_file',{'path':str(self.src)})
    def test_workspace_and_request_differ_without_widening_shell(self):
        for mode in ('request','workspace','full'):
            r=self.registry(mode)
            value=r.call('make_directory',{'path':mode})
            self.assertEqual(value['status'],'approval_required' if mode=='request' else 'ok')
            self.assertEqual(r.call('execute',{'argv':['pwd']},approved=True)['status'],'denied')
    def test_absolute_paths_inside_workspace_are_not_extra_prompts(self):
        r=self.registry();(self.work/'note').write_text('inside')
        self.assertEqual(r.call('read_file',{'path':str(self.work/'note')}),'inside')

class ScopeHTTP(unittest.TestCase):
    setUp=Base.setUp;tearDown=Base.tearDown;start=Base.start;stop=Base.stop;done=Base.done;denied=Base.denied
    def factory(self,callback):
        runtime=Base.factory(self,callback)
        return runtime
    def prepare(self,mode='workspace'):
        self.out=(self.root/'outside').resolve();self.out.mkdir(exist_ok=True);self.target=self.out/'new.txt'
        self.backend=Backend(answer('',call('apply_patch',{'changes':[{'path':str(self.target),'operation':'create','content':'approved bytes'}]},'write')),answer('done'))
        s=self.service.create_session(owner_subject='codex',desktop_options={'permission_mode':mode,'agent_profile':'standard','scope_revision':1})
        return self.done(self.codex.submit('write an outside test file',session_id=s['id'],idempotency_key='scope-test'))
    def test_approve_continues_same_task_and_cannot_be_reused(self):
        t=self.prepare();self.assertEqual(t['status'],'requires_approval');self.assertFalse(self.target.exists())
        action=t['required_action']['id'];self.denied(403,lambda:self.codex.request('/localpilot/v1/tasks/'+t['id']+'/approve',{'action_id':action}))
        self.operator.request('/localpilot/v1/tasks/'+t['id']+'/approve',{'action_id':action})
        final=self.done(t);self.assertEqual(final['id'],t['id']);self.assertEqual(self.target.read_text(),'approved bytes')
        self.denied(409,lambda:self.operator.request('/localpilot/v1/tasks/'+t['id']+'/approve',{'action_id':action}))
    def test_reject_stops_without_an_alternate_model_request(self):
        t=self.prepare();self.operator.request('/localpilot/v1/tasks/'+t['id']+'/reject',{'action_id':t['required_action']['id']})
        final=self.done(t);self.assertEqual(final['status'],'incomplete');self.assertFalse(self.target.exists());self.assertEqual(len(self.backend.requests),1)
    def test_restart_requires_fresh_action_and_no_automatic_dispatch(self):
        t=self.prepare();old=t['required_action']['id'];self.stop();self.service.suspend();self.start()
        restored=self.codex.status(t['id']);self.assertEqual(restored['status'],'requires_approval');self.assertNotEqual(restored['required_action']['id'],old)
        self.denied(409,lambda:self.operator.request('/localpilot/v1/tasks/'+t['id']+'/approve',{'action_id':old}));self.assertFalse(self.target.exists())
        self.operator.request('/localpilot/v1/tasks/'+t['id']+'/approve',{'action_id':restored['required_action']['id']})
        self.done(t);self.assertEqual(self.target.read_text(),'approved bytes')
    def test_changed_target_does_not_dispatch_or_report_success(self):
        t=self.prepare();self.target.write_text('external change')
        self.operator.request('/localpilot/v1/tasks/'+t['id']+'/approve',{'action_id':t['required_action']['id']})
        final=self.done(t);self.assertEqual(self.target.read_text(),'external change');self.assertNotEqual(final['status'],'completed')


class ScopeHybridHTTP(ScopeHTTP):
    def factory(self, callback):
        from agent.session import AgentSession
        from agent.retry import RetryPolicy
        from agent.hybrid import HybridPolicy, CloudEgressPolicy
        return AgentSession(create_default_registry(self.workspace, permission_mode='approve-mutations'),
            cloud_backend=self.backend, policy='cloud-only', event_callback=callback,
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED', ())),
            retry_policy=RetryPolicy(max_attempts=1))

    def test_escalated_unknown_effect_is_quarantined_after_restart_without_replay(self):
        import os
        from unittest.mock import patch
        import agent.safe_files as files
        outside=(self.root/'outside-unknown').resolve();outside.mkdir();source=outside/'source.txt';source.write_text('known public bytes');target=outside/'copy.txt'
        args={'source':str(source),'destination':str(target),'expected_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        self.backend=Backend(answer('',call('copy_file',args,'copy-unknown')),answer('must remain unverified'))
        session=self.service.create_session(owner_subject='codex',desktop_options={'permission_mode':'workspace','agent_profile':'standard','scope_revision':1})
        task=self.done(self.codex.submit('copy public fixture',session_id=session['id'],idempotency_key='scope-unknown'))
        self.assertEqual(task['status'],'requires_approval');action=task['required_action']['id'];original=files.digest_fd
        def fail_after_effect(fd):
            if target.exists() and os.fstat(fd).st_ino==target.stat().st_ino:
                raise OSError('Acceptance-only failure after the copy exists')
            return original(fd)
        with patch('agent.safe_files.digest_fd',side_effect=fail_after_effect):
            self.operator.continue_task(task['id'],action,action='approve');final=self.done(task)
        self.assertEqual(target.read_bytes(),source.read_bytes());self.assertEqual(final['recovery']['class'],'UNKNOWN_BLOCKED')
        count=len(final['tools']);identity=target.stat().st_ino
        self.stop();self.service.suspend();self.start();restored=self.codex.status(task['id'])
        self.assertEqual(restored['recovery']['class'],'UNKNOWN_BLOCKED');self.assertEqual(len(restored['tools']),count)
        self.assertEqual(target.stat().st_ino,identity)
        self.denied(409,lambda:self.operator.continue_task(task['id'],action,action='approve'))
