"""Independent V3.1 fixture: OS-free input; actual files, flocks, HTTP, processes."""
from copy import deepcopy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent.registry import create_default_registry
from agent.session import AgentSession
from computer.human_recovery import CONFIRMATIONS, HumanRecovery, read_json, durable_json
from computer.local_native import LocalNativeBackend, NativeOutcomeUnknown
from computer.runtime import ComputerRuntime
from localpilot_api.client import Client
from localpilot_api.server import APIServer
from localpilot_api.service import APIError, TaskRequest, TaskService
from tests.test_local_native_backend import APP, target
from tests.test_native_recovery_v3 import RecoveryTransport
from tests.test_runtime_api import Backend, answer
from tests.test_computer_runtime import condition
from urllib.error import HTTPError


class RecoveryFixture(RecoveryTransport):
    def __init__(self, mode="normal"):
        super().__init__(mode)
        self.old_alive = False
        self.helper_alive = False
        self.exit_unknown = False

    def request(self, **r):
        if r['op'] == 'native_process_status':
            alive = self.old_alive if r['pid'] == 1234567 else self.helper_alive
            return {'status': 'error' if self.exit_unknown else 'ok', 'pid': r['pid'],
                    'process_birth': r['process_birth'], 'old_generation_exited': not alive,
                    'evidence': 'kill_zero_ESRCH'}
        result = super().request(**r)
        if r['op'] == 'native_context' and result.get('status') == 'ok':
            result['recovery_readiness'] = {'event_access': True, 'secure_event_input': False}
        return result


def crash_request(directory, record):
    with patch('computer.local_native.BUILD', Path(directory)/'build'):
        t = RecoveryFixture(); t.pid += 1; t.birth = 'new'; t.window_id += 1
        t.controller = {**t.controller, 'instance': 'new-controller'}
        b = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=t)
        m = HumanRecovery(b)
        result = m.operate('request', APP, binding={'session_id':'crashed','task_generation':0},
                           principal='host-A', request_id=record['request_id'], idempotency_key='crash')
        assert result['state'] == 'AWAITING_HUMAN', result
        os._exit(43)


class HumanRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.p = patch('computer.local_native.BUILD', self.root/'build'); self.p.start(); self.addCleanup(self.p.stop)
        self.backends = []; self.addCleanup(lambda: [b.close() for b in self.backends])
        self.binding = {'session_id':'new-session', 'task_generation':0}; self.principal = 'host-A'
        self.now = 1000.

    def native(self, transport):
        b = LocalNativeBackend([APP], enabled=True, targets=[target()], transport=transport)
        self.backends.append(b); return b

    def setup_unknown(self, mode='after-pair', close=True):
        t = RecoveryFixture(mode); old = self.native(t)
        old.task_context = {'task_id':'original-task','session_id':'original-session','task_generation':7}
        old.inspect_tree(APP)
        try: old.action(APP,'input','type_text',text='OLD')
        except NativeOutcomeUnknown: pass
        record = old._lease_record(next(iter(old._leases.values())))
        if close: old.close()
        t = RecoveryFixture(); t.pid += 1; t.birth = 'new'; t.window_id += 1
        t.controller = {**t.controller, 'instance':'new-controller', 'pid':9876544, 'process_birth':'10.1'}
        b = self.native(t); m = HumanRecovery(b, clock=lambda: self.now)
        return old, record, b, t, m

    def op(self, m, action, **body):
        result = m.operate(action, APP, binding=self.binding, principal=self.principal, **body)
        sink = os.environ.get('LOCALPILOT_HUMAN_RECOVERY_EVIDENCE')
        if sink:
            with Path(sink).open('a') as out:
                out.write(json.dumps({'test':self.id(), 'action':action, 'classification':'scripted', 'input':body, 'result':result})+'\n')
        return result

    def request(self,m,record,key='request'):
        return self.op(m,'request',request_id=record['request_id'],idempotency_key=key)

    def auth_body(self, result):
        a = result['recovery']
        return {'recovery_id':a['id'], 'generation':a['generation'], 'target_fingerprint':a['target_fingerprint'],
                'confirmations':{k:True for k in CONFIRMATIONS}}

    def reval_body(self,result):
        return {k:self.auth_body(result)[k] for k in ('recovery_id','generation')}

    def recover(self,m,record):
        req = self.request(m,record); self.assertEqual(req['state'],'AWAITING_HUMAN')
        auth = self.op(m,'authorize',**self.auth_body(req)); self.assertEqual(auth['state'],'REVALIDATING')
        final = self.op(m,'revalidate',**self.reval_body(req))
        return req, auth, final

    def blocked(self,b,t):
        b.inspect_tree(APP)
        result = b.qualify_action('type_text',APP,{'handle':'input'})
        self.assertNotEqual(result['status'],'ok'); self.assertEqual(t.sent,0)
        b.quiesce()

    def test_recovery_preserves_unknown_audit_and_requires_fresh_gateway(self):
        old, record, b, t, m = self.setup_unknown()
        inspected = m.inspect(APP); self.assertEqual(inspected['obligations'][0]['intent'],record)
        self.assertIsNone(inspected['obligations'][0]['receipts']['dispatch_release_cleanup']['action_sent'])
        req, auth, final = self.recover(m,record)
        self.assertEqual(final['state'],'RECOVERED'); self.assertEqual(final['physical_release'],'UNKNOWN')
        self.assertIsNone(final['verified']); self.assertFalse(final['original_task_success'])
        self.assertEqual(final['recovery']['original'], record)
        self.assertEqual(final['recovery']['original']['task_context']['task_generation'],7)
        self.assertEqual([e['state'] for e in final['recovery']['events']],
                         ['RECOVERY_REQUESTED','AWAITING_HUMAN','REVALIDATING','RECOVERED'])
        self.assertEqual(old._cleanup['cleanup'],'UNKNOWN')
        runtime = ComputerRuntime(b,allowed_apps=[APP],verification_timeout=0)
        reg = create_default_registry(self.root,permission_mode='approve-mutations');runtime.register_tools(reg)
        self.assertFalse(any('recovery' in tool['function']['name'] for tool in reg.schemas()))
        tree = runtime.inspect_tree(APP)
        args = {'app':APP,'element':'input','observation':tree['observation'],'text':'NEW','postcondition':condition(value='oldNEW')}
        self.assertEqual(reg.call('type_text',args)['status'],'approval_required');self.assertEqual(t.sent,0)
        self.assertTrue(reg.call('type_text',args,approved=True)['verified']);self.assertEqual(t.sent,1)
        self.assertEqual(t.nodes[0]['value'],'oldNEW')

    def test_simulated_unreleased_input_is_not_converted_to_release_proof(self):
        old,record,b,t,m=self.setup_unknown(mode='down-only')
        self.assertEqual(old._cleanup['keys'],[0]);self.assertEqual(old._cleanup['cleanup'],'UNKNOWN')
        req,auth,final=self.recover(m,record)
        self.assertEqual(final['state'],'RECOVERED');self.assertEqual(final['physical_release'],'UNKNOWN')
        self.assertEqual(final['recovery']['receipts']['dispatch_release_cleanup']['posted_events'],1)
        self.assertEqual(final['recovery']['receipts']['dispatch_release_cleanup']['input_cleanup']['keys'],[0])
        self.assertIsNone(final['verified']);self.assertEqual(old._cleanup['keys'],[0]);self.assertEqual(t.sent,0)

    def test_recovered_native_writes_require_approval_even_in_full_permission(self):
        _,record,b,t,m=self.setup_unknown();self.recover(m,record)
        runtime=ComputerRuntime(b,allowed_apps=[APP],verification_timeout=0)
        reg=create_default_registry(self.root,permission_mode='full-permission');runtime.register_tools(reg)
        tree=runtime.inspect_tree(APP)
        args={'app':APP,'element':'input','observation':tree['observation'],'text':'NEW','postcondition':condition(value='oldNEW')}
        self.assertEqual(reg.call('type_text',args)['status'],'approval_required');self.assertEqual(t.sent,0)
        self.assertTrue(reg.call('type_text',args,approved=True)['verified']);self.assertEqual(t.sent,1)

    def test_recovery_approval_constraint_survives_successor_backend_recreation(self):
        _,record,b,t,m=self.setup_unknown();self.recover(m,record);b.close()
        fresh=self.native(RecoveryFixture());runtime=ComputerRuntime(fresh,allowed_apps=[APP],verification_timeout=0)
        registry=create_default_registry(self.root,permission_mode='full-permission');runtime.register_tools(registry)
        tree=runtime.inspect_tree(APP)
        args={'app':APP,'element':'input','observation':tree['observation'],'text':'NEW','postcondition':condition(value='oldNEW')}
        self.assertEqual(registry.call('type_text',args)['status'],'approval_required');self.assertEqual(fresh.transport.sent,0)

    def test_request_authorization_revalidation_are_idempotent(self):
        _,record,b,t,m=self.setup_unknown();req=self.request(m,record)
        self.assertTrue(self.request(m,record)['idempotent'])
        auth=self.op(m,'authorize',**self.auth_body(req));self.assertTrue(self.op(m,'authorize',**self.auth_body(req))['idempotent'])
        final=self.op(m,'revalidate',**self.reval_body(req));self.assertEqual(final['state'],'RECOVERED')
        self.assertTrue(self.op(m,'revalidate',**self.reval_body(req))['idempotent']);self.assertEqual(t.sent,0)

    def test_incomplete_or_forged_confirmation_cannot_admit(self):
        for value in (False,1,'true',None):
            with self.subTest(value=value),patch('computer.local_native.BUILD',self.root/str(value)/'build'):
                _,record,b,t,m=self.setup_unknown();req=self.request(m,record);body=self.auth_body(req)
                body['confirmations']['physical_release_unverified']=value
                self.assertEqual(self.op(m,'authorize',**body)['state'],'STILL_QUARANTINED');self.blocked(b,t)

    def test_live_old_app_or_helper_and_unknown_exit_refuse(self):
        for field in ('old_alive','helper_alive','exit_unknown'):
            with self.subTest(field=field),patch('computer.local_native.BUILD',self.root/field/'build'):
                _,record,b,t,m=self.setup_unknown();setattr(t,field,True);req=self.request(m,record)
                self.assertEqual(self.op(m,'authorize',**self.auth_body(req))['state'],'STILL_QUARANTINED');self.blocked(b,t)

    def test_initial_target_qualification_failure_is_durably_terminal(self):
        _,record,b,t,m=self.setup_unknown();t.context_error=True
        result=self.request(m,record);self.assertEqual(result['state'],'STILL_QUARANTINED')
        self.assertEqual(m.journal(APP)['attempts'][-1]['state'],'STILL_QUARANTINED');self.blocked(b,t)
        t.context_error=False;self.assertEqual(self.request(m,record,key='retry-new-attempt')['state'],'AWAITING_HUMAN')

    def test_identity_changes_between_each_phase_refuse(self):
        for phase in ('authorize','revalidate'):
            for field in ('pid','birth','window_id','control_generation','controller','responder'):
                with self.subTest(phase=phase,field=field),patch('computer.local_native.BUILD',self.root/phase/field/'build'):
                    _,record,b,t,m=self.setup_unknown();req=self.request(m,record)
                    if phase=='revalidate':self.assertEqual(self.op(m,'authorize',**self.auth_body(req))['state'],'REVALIDATING')
                    if field=='birth':t.birth='again'
                    elif field=='controller':t.controller={**t.controller,'instance':'again'}
                    elif field=='responder':t.context_error=True
                    else:setattr(t,field,getattr(t,field)+1)
                    self.assertEqual(self.op(m,phase,**(self.auth_body(req) if phase=='authorize' else self.reval_body(req)))['state'],'STILL_QUARANTINED');self.blocked(b,t)

    def test_expired_authorization_and_clock_rollback_refuse(self):
        for now in (999,1121):
            with self.subTest(now=now),patch('computer.local_native.BUILD',self.root/str(now)/'build'):
                self.now=1000;_,record,b,t,m=self.setup_unknown();req=self.request(m,record);self.now=now
                self.assertEqual(self.op(m,'authorize',**self.auth_body(req))['state'],'STILL_QUARANTINED');self.blocked(b,t)

    def test_revalidation_requires_explicit_authorization(self):
        _,record,b,t,m=self.setup_unknown();req=self.request(m,record)
        self.assertEqual(self.op(m,'revalidate',**self.reval_body(req))['state'],'STILL_QUARANTINED');self.blocked(b,t)

    def test_fencing_generation_session_and_principal(self):
        _,record,b,t,m=self.setup_unknown();req=self.request(m,record);body=self.auth_body(req)
        for key,value in [('generation',True),('generation',2),('recovery_id','0'*32)]:
            self.assertEqual(self.op(m,'authorize',**{**body,key:value})['state'],'STILL_QUARANTINED')
        for binding,principal in [({'session_id':'other','task_generation':0},self.principal),(self.binding,'host-B'),({'session_id':'new-session','task_generation':1},self.principal)]:
            result=m.operate('authorize',APP,binding=binding,principal=principal,**body)
            self.assertEqual(result['state'],'STILL_QUARANTINED')
        self.assertEqual(m.journal(APP)['attempts'][-1]['state'],'AWAITING_HUMAN');self.blocked(b,t)

    def test_old_owner_and_new_owner_cannot_dispatch_during_recovery(self):
        old,record,b,t,m=self.setup_unknown(close=False)
        snapshot=m.inspect(APP);self.assertEqual(snapshot['state'],'QUARANTINED')
        self.assertEqual(snapshot['obligations'][0]['intent']['owner'],old.owner)
        self.assertTrue(snapshot['snapshot_only'])
        self.assertEqual(self.request(m,record)['state'],'STILL_QUARANTINED')
        old.quiesce();req=self.request(m,record)
        self.assertEqual(req['state'],'AWAITING_HUMAN');self.blocked(b,t)
        self.assertFalse(old.action(APP,'input','type_text',text='OLD')['action_sent'])
        self.assertNotEqual(b.recover_input(APP,request_id=record['request_id'],authorized=True)['status'],'ok')

    def test_two_sessions_requests_conflict(self):
        _,record,b,t,m=self.setup_unknown();b2=self.native(RecoveryFixture());m2=HumanRecovery(b2,clock=lambda:self.now)
        gate=threading.Barrier(2);results=[]
        def run(manager,session):
            gate.wait(2);results.append(manager.operate('request',APP,binding={'session_id':session,'task_generation':0},principal='host-A',request_id=record['request_id'],idempotency_key=session))
        threads=[threading.Thread(target=run,args=(manager,str(i))) for i,manager in enumerate((m,m2))]
        for thread in threads:thread.start()
        for thread in threads:thread.join(4);self.assertFalse(thread.is_alive())
        self.assertEqual(sum(r['state']=='AWAITING_HUMAN' for r in results),1)
        self.assertEqual(t.sent,0)

    def test_reject_and_abandon_orphan_after_process_crash(self):
        _,record,b,t,m=self.setup_unknown()
        proc=multiprocessing.get_context('spawn').Process(target=crash_request,args=(str(self.root),record));proc.start();proc.join(8)
        self.assertEqual(proc.exitcode,43)
        a=m.journal(APP)['attempts'][-1];self.assertEqual(a['state'],'AWAITING_HUMAN')
        self.assertEqual(self.request(m,record)['reason'],'recovery_conflict')
        body={'recovery_id':a['id'],'generation':a['generation']}
        self.assertEqual(self.op(m,'reject',**body)['state'],'STILL_QUARANTINED')
        self.assertTrue(self.op(m,'reject',**body)['idempotent']);self.blocked(b,t)
        self.assertEqual(self.request(m,record,key='new')['state'],'AWAITING_HUMAN')

    def test_revalidation_persists_across_manager_restart(self):
        _,record,b,t,m=self.setup_unknown();req=self.request(m,record);self.op(m,'authorize',**self.auth_body(req))
        restarted=HumanRecovery(b,clock=lambda:self.now)
        self.assertEqual(self.op(restarted,'revalidate',**self.reval_body(req))['state'],'RECOVERED')

    def test_corrupt_audit_cannot_admit_even_with_clean_sidecar(self):
        _,record,b,t,m=self.setup_unknown();self.recover(m,record)
        m.path(APP).write_text('{')
        self.blocked(b,t)

    def test_changed_obligation_or_multiple_pending_refuse(self):
        for multiple in (False,True):
            with self.subTest(multiple=multiple),patch('computer.local_native.BUILD',self.root/str(multiple)/'build'):
                _,record,b,t,m=self.setup_unknown();req=self.request(m,record)
                directory=b._lease_directory(); changed={**record,'request_id':'f'*32}
                if multiple:changed['pid']+=5
                (directory/f'{changed["pid"]}.lock.state').write_text(json.dumps(changed))
                self.assertEqual(self.op(m,'authorize',**self.auth_body(req))['state'],'STILL_QUARANTINED');self.blocked(b,t)

    def test_durability_failures_never_publish_admission(self):
        for stage in ('journal-file','journal-dir','journal-rename','clean-file','clean-dir','clean-rename'):
            with self.subTest(stage=stage),patch('computer.local_native.BUILD',self.root/stage/'build'):
                _,record,b,t,m=self.setup_unknown();req=self.request(m,record);self.op(m,'authorize',**self.auth_body(req))
                real_sync=os.fsync;real_replace=os.replace;calls=0
                def sync(fd):
                    nonlocal calls
                    calls+=1
                    # revalidate: journal file, journal directory, journal fence file,
                    # clean file, clean directory. Remaining writes are failure audit.
                    if calls=={'journal-file':1,'journal-dir':2,'clean-file':4,'clean-dir':5}.get(stage,-1):raise OSError('injected durability failure')
                    return real_sync(fd)
                def replace(src,dst):
                    if stage=='journal-rename' and str(dst).endswith('.human-recovery.json'):raise OSError('journal rename failed')
                    if stage=='clean-rename' and str(dst).endswith('.lock.state'):raise OSError('clean rename failed')
                    return real_replace(src,dst)
                with patch('computer.human_recovery.os.fsync',side_effect=sync),patch('computer.human_recovery.os.replace',side_effect=replace):
                    result=self.op(m,'revalidate',**self.reval_body(req))
                self.assertNotEqual(result['status'],'ok');self.blocked(b,t)
                self.assertEqual(read_json(b._lease_directory()/f'{record["pid"]}.lock.state')['status'],'uncertain')

    def test_admission_publication_has_no_fallible_temporary_cleanup(self):
        _,record,b,t,m=self.setup_unknown();req=self.request(m,record);self.op(m,'authorize',**self.auth_body(req))
        calls=[]
        def fail(path,*args,**kwargs):
            calls.append(str(path));raise OSError('post-publication cleanup unavailable')
        with patch.object(Path,'unlink',fail):
            result=self.op(m,'revalidate',**self.reval_body(req))
        self.assertEqual(result['state'],'RECOVERED');self.assertEqual(calls,[]);self.assertEqual(t.sent,0)

    def test_native_lease_publication_has_no_fallible_temporary_cleanup(self):
        t=RecoveryFixture();b=self.native(t);b.inspect_tree(APP);calls=[]
        def fail(path,*args,**kwargs):
            calls.append(str(path));raise OSError('temporary cleanup unavailable')
        with patch.object(Path,'unlink',fail):
            result=b.action(APP,'input','type_text',text='NEW')
        self.assertEqual(result['input_cleanup']['status'],'ok');self.assertEqual(t.sent,1);self.assertEqual(calls,[])
        self.assertEqual(b._lease_record(next(iter(b._leases.values())))['status'],'clean')

    def test_journal_commit_without_clean_after_crash_is_still_isolated(self):
        _,record,b,t,m=self.setup_unknown();req=self.request(m,record);self.op(m,'authorize',**self.auth_body(req))
        real_replace=os.replace
        def stop(src,dst):
            if str(dst).endswith('.lock.state'):raise KeyboardInterrupt('crash at admission commit')
            return real_replace(src,dst)
        with patch('computer.human_recovery.os.replace',side_effect=stop),self.assertRaises(KeyboardInterrupt):
            self.op(m,'revalidate',**self.reval_body(req))
        self.assertEqual(m.journal(APP)['attempts'][-1]['state'],'RECOVERED')
        self.assertEqual(self.op(m,'revalidate',**self.reval_body(req))['state'],'STILL_QUARANTINED');self.blocked(b,t)

    def test_old_idempotency_key_cannot_mask_new_unknown(self):
        _,record,b,t,m=self.setup_unknown();req,auth,final=self.recover(m,record)
        self.assertEqual(final['state'],'RECOVERED')
        t.mode='after-pair';b.inspect_tree(APP)
        with self.assertRaises(NativeOutcomeUnknown):b.action(APP,'input','type_text',text='SECOND')
        second=b._lease_record(next(iter(b._leases.values())));b.quiesce()
        self.assertNotEqual(second['request_id'],record['request_id'])
        self.assertEqual(self.request(m,record)['state'],'STILL_QUARANTINED')
        self.assertEqual(self.op(m,'revalidate',**self.reval_body(req))['state'],'STILL_QUARANTINED')
        self.assertEqual(second['status'],'uncertain')

    def test_stop_or_locked_environment_during_recovery_keeps_isolation(self):
        for change in ('stop','locked','frontmost'):
            with self.subTest(change=change),patch('computer.local_native.BUILD',self.root/change/'build'):
                _,record,b,t,m=self.setup_unknown();req=self.request(m,record);self.op(m,'authorize',**self.auth_body(req))
                if change=='stop':b.request_stop()
                if change=='locked':t.env['locked']=True
                if change=='frontmost':t.env['frontmost_app']=APP;t.env['frontmost_pid']=t.pid
                self.assertEqual(self.op(m,'revalidate',**self.reval_body(req))['state'],'STILL_QUARANTINED')
                self.assertEqual(read_json(b._lease_directory()/f'{record["pid"]}.lock.state')['status'],'uncertain');self.assertEqual(t.sent,0)

    def test_recovery_competes_with_owner_close_without_leaking_lease(self):
        _,record,b,t,m=self.setup_unknown();req=self.request(m,record);self.op(m,'authorize',**self.auth_body(req))
        gate=threading.Barrier(2);results=[]
        def recover():gate.wait(2);results.append(self.op(m,'revalidate',**self.reval_body(req)))
        def close():gate.wait(2);b.close()
        threads=[threading.Thread(target=recover),threading.Thread(target=close)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(4);self.assertFalse(thread.is_alive())
        self.assertIn(results[0]['state'],{'RECOVERED','STILL_QUARANTINED'});self.assertEqual(t.sent,0);self.assertFalse(b._leases)


class RecoveryAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture=HumanRecoveryTests();self.fixture.setUp()
        self.old,self.record,self.b,self.t,self.m=self.fixture.setup_unknown()
        self.sessions=[]
        def factory(callback):
            runtime=ComputerRuntime(self.b,allowed_apps=[APP],verification_timeout=0)
            session=AgentSession(create_default_registry(self.fixture.root,permission_mode='approve-mutations'),
                backend=Backend(answer()),policy='cloud-only',event_callback=callback,computer_runtime=runtime)
            self.sessions.append(session);return session
        self.service=TaskService({'localpilot':factory})
        self.server=APIServer(('127.0.0.1',0),self.service,api_key='model-key',control_token='host-key',control_subject='fixture-host-user')
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.client=Client(f'http://127.0.0.1:{self.server.server_port}',api_key='model-key',control_token='host-key')
        self.sid=self.service.create_session()['id'];self.base=f'/localpilot/v1/sessions/{self.sid}/computer/recovery'

    def tearDown(self):
        self.service.shutdown();self.server.shutdown();self.server.server_close();self.thread.join(2)
        self.fixture.doCleanups()

    def request(self):
        return self.client.request(self.base+'/request',{'app':APP,'request_id':self.record['request_id'],'idempotency_key':'http'},control=True)

    def test_model_key_cannot_inspect_or_authorize(self):
        for path,body in [(self.base+'?app='+APP,None),(self.base+'/request',{'app':APP}),
                          (self.base+'/authorize',{'app':APP}), (self.base+'/revalidate',{'app':APP})]:
            with self.assertRaises(HTTPError) as exc:self.client.request(path,body)
            self.assertEqual(exc.exception.code,403)
        self.assertEqual(self.t.sent,0)

    def test_full_http_authorization_principal_and_no_automatic_task(self):
        inspected=self.client.request(self.base+'?app='+APP,control=True);self.assertEqual(inspected['state'],'QUARANTINED')
        req=self.request();body=self.fixture.auth_body(req)
        auth=self.client.request(self.base+'/authorize',{'app':APP,**body},control=True)
        self.assertEqual(auth['recovery']['authorization']['principal'],'fixture-host-user')
        final=self.client.request(self.base+'/revalidate',{'app':APP,**self.fixture.reval_body(req)},control=True)
        self.assertEqual(final['state'],'RECOVERED');self.assertFalse(self.service.tasks);self.assertEqual(self.t.sent,0)

    def test_task_generation_fences_pending_recovery_and_cancel(self):
        req=self.request()
        task=self.service.create_task(TaskRequest('Observe only',session_id=self.sid));self.service.wait(task['id'])
        with self.assertRaises(HTTPError) as exc:
            self.client.request(self.base+'/authorize',{'app':APP,**self.fixture.auth_body(req)},control=True)
        self.assertEqual(exc.exception.code,409)
        self.assertEqual(self.m.journal(APP)['attempts'][-1]['state'],'AWAITING_HUMAN');self.assertEqual(self.t.sent,0)

    def test_no_body_principal_or_risk_override(self):
        req=self.request();body={'app':APP,**self.fixture.auth_body(req),'principal':'fake-human'}
        with self.assertRaises(HTTPError) as exc:self.client.request(self.base+'/authorize',body,control=True)
        self.assertEqual(exc.exception.code,400);exc.exception.close();self.assertEqual(self.t.sent,0)

    def test_prior_task_shared_backend_owner_is_rejected_before_waiting_on_device(self):
        task=self.service.create_task(TaskRequest('Read only',session_id=self.sid));self.service.wait(task['id'])
        successor=self.service.create_session()['id']
        with self.assertRaises(APIError) as exc:
            self.service.native_recovery(successor,'inspect',{'app':APP},principal='fixture-host-user')
        self.assertEqual(exc.exception.code,'recovery_owner_conflict')

    def test_new_task_creation_waits_for_revalidation_commit(self):
        req=self.request();identity=self.fixture.reval_body(req)
        self.client.request(self.base+'/authorize',{'app':APP,**self.fixture.auth_body(req)},control=True)
        entered=threading.Event();release=threading.Event();created=threading.Event();results=[]
        original=HumanRecovery._target
        def gated(manager,*args,**kwargs):
            entered.set();self.assertTrue(release.wait(3));return original(manager,*args,**kwargs)
        def recover():
            results.append(self.service.native_recovery(self.sid,'revalidate',{'app':APP,**identity},principal='fixture-host-user'))
        def newtask():
            results.append(self.service.create_task(TaskRequest('Read only successor',session_id=self.sid)));created.set()
        with patch.object(HumanRecovery,'_target',gated):
            rt=threading.Thread(target=recover);rt.start();self.assertTrue(entered.wait(2))
            nt=threading.Thread(target=newtask);nt.start()
            self.assertFalse(created.wait(.05));release.set()
            rt.join(4);nt.join(4);self.assertFalse(rt.is_alive());self.assertFalse(nt.is_alive())
        self.assertEqual(results[0]['state'],'RECOVERED');self.assertTrue(created.is_set());self.assertEqual(self.t.sent,0)
