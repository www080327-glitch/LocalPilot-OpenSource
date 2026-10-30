"""V3 recovery controls: scripted input, real durable files/flock/processes.

No CGEvents or model calls. Optional sink preserves per-scenario raw evidence.
"""
from copy import deepcopy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from computer.local_native import LocalNativeBackend, NativeOutcomeUnknown
from computer.runtime import ComputerRuntime
from agent.registry import create_default_registry
from tests.test_local_native_backend import APP, NativeTransport, target
from tests.test_computer_runtime import condition


def durable_proof(request):
    proof = {"version": 1, "kind": "NO_DISPATCH", "terminal": True, "posted_events": 0,
             **{k: request[k] for k in ("owner", "request_id", "lease", "fence")},
             "target_identity": request['target'], "controller": request['target']['controller'],
             "input_cleanup": {"status": "ok", "cleanup": "no_owned_inputs", "keys": [], "buttons": [], "modifiers": []}}
    path = Path(request['receipt_path'])
    with path.open('x') as f:
        json.dump(proof, f); f.flush(); os.fsync(f.fileno())
    fd=os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return proof


class RecoveryTransport(NativeTransport):
    def __init__(self, mode='lost-no-dispatch', app=APP):
        super().__init__(); self.mode=mode; self.app=app
        self.allowed_apps=frozenset([app]); self.last_request=None

    def identity(self):
        return {**super().identity(), 'app': self.app}

    def request(self, **r):
        if r['op'] != 'native_text': return super().request(**r)
        self.last_request = deepcopy(r)
        if self.mode in {'lost-no-dispatch', 'crash-no-dispatch', 'no-dispatch'}:
            durable_proof(r)
            if self.mode=='crash-no-dispatch': os._exit(31)
            if self.mode=='lost-no-dispatch': raise TimeoutError('scripted response lost after durable zero dispatch')
            return {'status':'error','action_sent':False,'input_cleanup':{'status':'ok','cleanup':'no_owned_inputs'}}
        if self.mode=='before-entry': raise TimeoutError('scripted helper died before entry')
        if self.mode=='after-pair':
            result=super().request(**r)
            raise TimeoutError('scripted pair posted, response lost')
        if self.mode=='down-only':
            self.sent+=1
            return {'status':'error','action_sent':True,'request_id':r['request_id'],
                    'posted_events':1,'input_cleanup':{'status':'error','cleanup':'UNKNOWN','keys':[0]}}
        return super().request(**r)


def crashed_owner(directory):
    with patch('computer.local_native.BUILD', Path(directory)/'build'):
        b=LocalNativeBackend([APP], enabled=True, targets=[target()], transport=RecoveryTransport('crash-no-dispatch'))
        b.inspect_tree(APP); b.action(APP,'input','type_text',text='OLD')


class RecoveryV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup); self.backends=[]
        self.p=patch('computer.local_native.BUILD', self.root/'build'); self.p.start(); self.addCleanup(self.p.stop)
        self.addCleanup(lambda: [b.close() for b in self.backends])

    def evidence(self, name, **facts):
        sink=os.environ.get('LOCALPILOT_RECOVERY_EVIDENCE')
        if sink:
            with Path(sink).open('a') as f:
                f.write(json.dumps({'case':name,'classification':'scripted PASS',**facts},default=str)+'\n')

    def native(self, transport=None, app=APP):
        t=transport or RecoveryTransport()
        policy={**target(), 'app':app}
        b=LocalNativeBackend([app],enabled=True,targets=[policy],transport=t); self.backends.append(b)
        return b,t

    def unknown(self, mode='lost-no-dispatch'):
        b,t=self.native(RecoveryTransport(mode)); b.inspect_tree(APP)
        try: result=b.action(APP,'input','type_text',text='OLD')
        except NativeOutcomeUnknown as exc: result=exc.computer_receipt
        record=json.loads((self.root/'native-leases'/f'{t.pid}.lock.state').read_text())
        self.assertEqual(record['status'],'uncertain'); self.assertFalse(result.get('replay_allowed',False))
        return b,t,record

    def recover(self,b,record,authorized=True):
        return b.recover_input(APP,request_id=record['request_id'],authorized=authorized)

    def test_same_owner_reconcile_requires_new_observation_and_approval(self):
        b,t,record=self.unknown(); result=self.recover(b,record)
        self.assertEqual(result['status'],'ok'); self.assertFalse(b._states)
        self.assertEqual(t.sent,0)
        runtime=ComputerRuntime(b,allowed_apps=[APP],verification_timeout=0)
        reg=create_default_registry(self.root,permission_mode='approve-mutations'); runtime.register_tools(reg)
        t.mode='normal'; tree=runtime.inspect_tree(APP)
        args={'app':APP,'element':'input','observation':tree['observation'],'text':'NEW','postcondition':condition(value='oldNEW')}
        self.assertEqual(reg.call('type_text',args)['status'],'approval_required'); self.assertEqual(t.sent,0)
        result=reg.call('type_text',args,approved=True); self.assertTrue(result['verified']); self.assertEqual(t.sent,1)
        self.assertEqual(t.nodes[0]['value'],'oldNEW')
        self.evidence('same-owner-recover-new-approval',record=record,recovery=result)

    def test_cross_owner_reconcile_does_not_require_live_old_helper_or_target(self):
        for change in ('same-pid', 'birth', 'pid', 'window', 'control', 'helper'):
            with self.subTest(change=change), patch('computer.local_native.BUILD', self.root/change/'build'):
                # Own temp store; unknown remains app-scoped across generations.
                old,t=self.native(); old.inspect_tree(APP)
                with self.assertRaises(NativeOutcomeUnknown): old.action(APP,'input','type_text',text='OLD')
                record=old._lease_record(next(iter(old._leases.values()))); old.close()
                other=RecoveryTransport('normal')
                if change=='birth': other.birth='changed'
                if change=='pid': other.pid+=1
                if change=='window': other.window_id+=1
                if change=='control': other.control_generation+=1
                if change=='helper': other.controller={**other.controller,'instance':'new-controller'}
                b,t=self.native(other); b.inspect_tree(APP)
                self.assertEqual(b.qualify_action('type_text',APP,{'handle':'input'})['reason'],'input_cleanup_unknown')
                self.assertEqual(self.recover(b,record)['status'],'ok')
                b.inspect_tree(APP); self.assertEqual(b.qualify_action('type_text',APP,{'handle':'input'})['status'],'ok')
                self.assertEqual(t.sent,0); b.close()
                self.evidence('cross-owner/'+change,original=record)

    def test_authorization_and_request_scope_cannot_clear_unknown(self):
        b,t,record=self.unknown()
        for auth in (False,None,1,'true'):
            result=self.recover(b,record,auth); self.assertEqual(result['reason'],'native_recovery_authorization_required')
            self.evidence('authorization/'+repr(auth),result=result)
        result=b.recover_input(APP,request_id='0'*32,authorized=True)
        self.assertEqual(result['reason'],'native_recovery_obligation_mismatch')
        self.evidence('wrong-request-authorized',result=result)
        result=b.recover_input('unallowed',request_id=record['request_id'],authorized=True)
        self.assertEqual(result['reason'],'native_recovery_authorization_required')
        self.evidence('unallowed-app-authorized',result=result)
        self.assertEqual(t.sent,0)

    def test_terminal_proof_tampering_and_torn_files_fail_closed(self):
        changes=[('version',2),('version',True),('kind','POSTED'),('terminal',False),('terminal',1),
                 ('posted_events',1),('posted_events',False),('request_id','old-request'),('owner','old-owner'),
                 ('lease','old-lease'),('fence','old-fence'),('controller',{'instance':'restarted'}),
                 ('target_identity',{'pid':2}),('input_cleanup',{'status':'ok','cleanup':'owned_key_up_POSTED'}),
                 ('input_cleanup',{'status':'ok','cleanup':'no_owned_inputs','keys':[0],'buttons':[],'modifiers':[]}),
                 ('input_cleanup',{'status':'ok','cleanup':'no_owned_inputs','keys':[],'buttons':[0],'modifiers':[]}),
                 ('input_cleanup',{'status':'ok','cleanup':'no_owned_inputs','keys':[],'buttons':[],'modifiers':['shift']}),
                 ('input_cleanup',{'status':'ok','cleanup':'no_owned_inputs'})]
        for index,(key,value) in enumerate(changes):
            with self.subTest(key=key,value=value), patch('computer.local_native.BUILD',self.root/str(index)/'build'):
                b,t=self.native();b.inspect_tree(APP)
                with self.assertRaises(NativeOutcomeUnknown):b.action(APP,'input','type_text',text='OLD')
                record=b._lease_record(next(iter(b._leases.values()))); path=Path(record['receipt_path'])
                proof=json.loads(path.read_text()); proof[key]=value; path.write_text(json.dumps(proof))
                result=self.recover(b,record);self.assertEqual(result['reason'],'native_recovery_proof_invalid')
                self.assertEqual(b._lease_record(type('S',(),{'name':str(path.parent/f'{t.pid}.lock')})())['status'],'uncertain')
                self.evidence(f'proof-tamper/{index}-{key}',result=result,proof=proof);b.close()
        b,t,record=self.unknown();path=Path(record['receipt_path'])
        for name,raw in [('empty',''),('torn','{'),('oversized','x'*65537),('wrong-type','[]')]:
            path.write_text(raw);result=self.recover(b,record);self.assertNotEqual(result['status'],'ok')
            self.evidence('proof-file/'+name,result=result)

    def test_missing_and_symlink_proof_fail_closed(self):
        b,t,record=self.unknown();path=Path(record['receipt_path']); data=path.read_bytes();path.unlink()
        self.assertNotEqual(self.recover(b,record)['status'],'ok');self.evidence('proof-missing')
        other=self.root/'other';other.write_bytes(data);path.symlink_to(other)
        self.assertEqual(self.recover(b,record)['reason'],'native_recovery_proof_unavailable');self.evidence('proof-symlink')

    def test_already_posted_or_no_proof_cannot_reconcile(self):
        for mode in ('before-entry','after-pair','down-only'):
            with self.subTest(mode=mode), patch('computer.local_native.BUILD',self.root/mode/'build'):
                b,t=self.native(RecoveryTransport(mode));b.inspect_tree(APP)
                try:b.action(APP,'input','type_text',text='OLD')
                except NativeOutcomeUnknown:pass
                record=b._lease_record(next(iter(b._leases.values())));result=self.recover(b,record)
                self.assertNotEqual(result['status'],'ok');self.assertEqual(t.sent,0 if mode=='before-entry' else 1)
                b.close();other,_=self.native(RecoveryTransport('normal'));other.transport.pid+=1;other.inspect_tree(APP)
                self.assertEqual(other.qualify_action('type_text',APP,{'handle':'input'})['reason'],'input_cleanup_unknown')
                self.evidence('nonrecoverable/'+mode,result=result,record=record);other.close()

    def test_recovery_persistence_failure_keeps_obligation_and_allows_explicit_retry(self):
        for stage in ('file-fsync','rename','directory-fsync'):
            with self.subTest(stage=stage),patch('computer.local_native.BUILD',self.root/stage/'build'):
                b,t=self.native();b.inspect_tree(APP)
                with self.assertRaises(NativeOutcomeUnknown):b.action(APP,'input','type_text',text='OLD')
                record=b._lease_record(next(iter(b._leases.values())))
                if stage=='rename':
                    original=os.replace;count=0
                    def fault(*args):
                        nonlocal count
                        count+=1
                        if count==1:raise OSError('injected rename failure')
                        return original(*args)
                    ctx=patch('computer.local_native.os.replace',side_effect=fault)
                else:
                    original=os.fsync;count=0
                    def fault(*args):
                        nonlocal count
                        count+=1
                        if count==(2 if stage=='file-fsync' else 1):raise OSError('injected durability failure')
                        return original(*args)
                    ctx=patch('computer.local_native.os.fsync',side_effect=fault)
                with ctx:result=self.recover(b,record)
                self.assertNotEqual(result['status'],'ok')
                b.inspect_tree(APP);self.assertEqual(b.qualify_action('type_text',APP,{'handle':'input'})['reason'],'input_cleanup_unknown')
                self.assertEqual(self.recover(b,record)['status'],'ok');self.assertEqual(t.sent,0)
                self.evidence('recovery-io/'+stage,failed=result);b.close()

    def test_runtime_abrupt_exit_os_flock_release_and_persistent_recovery(self):
        p=multiprocessing.get_context('spawn').Process(target=crashed_owner,args=(str(self.root),));p.start();p.join(8)
        self.assertFalse(p.is_alive());self.assertEqual(p.exitcode,31)
        b,t=self.native(RecoveryTransport('normal'));b.inspect_tree(APP)
        self.assertEqual(b.qualify_action('type_text',APP,{'handle':'input'})['reason'],'input_cleanup_unknown')
        record=json.loads(next((self.root/'native-leases').glob('*.state')).read_text())
        self.assertEqual(self.recover(b,record)['status'],'ok');self.assertEqual(t.sent,0)
        self.evidence('runtime-process-death-restart',record=record,exitcode=p.exitcode)

    def test_competing_owner_cannot_reconcile_before_quiescence(self):
        old,t,record=self.unknown(); b,other=self.native(RecoveryTransport('normal'))
        self.assertEqual(self.recover(b,record)['reason'],'pid_lease_conflict')
        self.evidence('recover-while-old-owner-holds-flock')
        old.quiesce();self.assertEqual(self.recover(b,record)['status'],'ok');self.evidence('recover-after-quiescence')
        self.assertEqual(t.sent+other.sent,0)

    def test_different_apps_independent_unknown_does_not_block_clean_owner(self):
        old,t,record=self.unknown();old.close()
        other_app=APP+'.second';transport=RecoveryTransport('normal',app=other_app);transport.pid+=1
        b,other=self.native(transport,app=other_app);b.inspect_tree(other_app)
        self.assertEqual(b.qualify_action('type_text',other_app,{'handle':'input'})['status'],'ok')
        self.assertEqual(b.action(other_app,'input','type_text',text='NEW')['status'],'ok')
        self.assertEqual(other.sent,1);self.evidence('unknown-app-A-clean-app-B',original=record)

    def test_repeated_requests_during_quarantine_never_replay(self):
        b,t,record=self.unknown();b.quiesce();other,o=self.native(RecoveryTransport('normal'))
        for event in ('new-inspect','new-window','new-controller','new-pid','new-birth'):
            if event=='new-window':o.window_id+=1
            if event=='new-controller':o.controller={**o.controller,'instance':'new'}
            if event=='new-pid':o.pid+=1
            if event=='new-birth':o.birth='new'
            other.inspect_tree(APP);result=other.action(APP,'input','type_text',text='OLD')
            self.assertFalse(result['action_sent']);self.assertEqual(result['reason'],'input_cleanup_unknown')
            self.evidence('quarantine-request/'+event,result=result)
        self.assertEqual(o.sent,0)

    def test_concurrent_recovery_exactly_one_transition_no_dispatch(self):
        old,t,record=self.unknown();old.close();barrier=threading.Barrier(2);results=[]
        bs=[self.native(RecoveryTransport('normal'))[0] for _ in range(2)]
        def run(b):barrier.wait(3);results.append(self.recover(b,record))
        threads=[threading.Thread(target=run,args=(b,)) for b in bs]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
        self.assertEqual(sum(r['status']=='ok' for r in results),1)
        self.evidence('concurrent-reconcile-two-owners',results=results)

    def test_runtime_resume_keeps_unknown_until_explicit_reconcile(self):
        b,t=self.native();r=ComputerRuntime(b,allowed_apps=[APP],verification_timeout=0)
        tree=r.inspect_tree(APP);result=r.act('type_text',app=APP,element='input',observation=tree['observation'],text='OLD',postcondition=condition(value='oldOLD'))
        self.assertIsNone(result['action_sent']);self.assertTrue(r.paused)
        record=json.loads(next((self.root/'native-leases').glob('*.state')).read_text())
        self.assertEqual(r.resume()['error'],'input_cleanup_unknown');self.evidence('runtime-resume-unknown-blocked')
        self.assertEqual(self.recover(b,record)['status'],'ok');t.mode='normal'
        self.assertEqual(r.resume()['status'],'ok');self.assertEqual(t.sent,0)
        self.evidence('runtime-resume-after-no-dispatch-reconcile')

    def test_corrupt_intent_blocks_all_generations_and_recovery(self):
        b,t,record=self.unknown();b.close();path=self.root/'native-leases'/f'{t.pid}.lock.state'
        for name,raw in [('empty',''),('torn','{'),('bad-schema','{"version":1}'),('oversized','x'*8193)]:
            path.write_text(raw);b,other=self.native(RecoveryTransport('normal'));other.pid+=1;b.inspect_tree(APP)
            self.assertEqual(b.qualify_action('type_text',APP,{'handle':'input'})['reason'],'native_lease_state_unknown')
            self.assertNotEqual(self.recover(b,record)['status'],'ok');self.evidence('intent-corruption/'+name);b.close()

    def test_recovery_followed_by_second_failure_rejects_old_terminal(self):
        b,t,first=self.unknown();self.assertEqual(self.recover(b,first)['status'],'ok')
        b.inspect_tree(APP)
        with self.assertRaises(NativeOutcomeUnknown):b.action(APP,'input','type_text',text='SECOND')
        second=b._lease_record(next(iter(b._leases.values())));self.assertNotEqual(first['request_id'],second['request_id'])
        self.assertEqual(self.recover(b,first)['reason'],'native_recovery_obligation_mismatch')
        self.assertEqual(self.recover(b,second)['status'],'ok');self.assertEqual(t.sent,0)
        self.evidence('recover-then-fail-again-original-proof-fenced',first=first,second=second)

    def test_legacy_v1_obligation_survives_upgrade_and_new_pid(self):
        directory=self.root/'native-leases';directory.mkdir(mode=0o700)
        record={'version':1,'app':APP,'pid':23,'process_birth':'old','status':'uncertain','owner':'legacy','request_id':'legacy'}
        (directory/'23.lock.state').write_text(json.dumps(record))
        b,t=self.native(RecoveryTransport('normal'));b.inspect_tree(APP)
        self.assertEqual(b.qualify_action('type_text',APP,{'handle':'input'})['reason'],'input_cleanup_unknown')
        self.assertNotEqual(self.recover(b,record)['status'],'ok');self.assertEqual(t.sent,0)
        self.evidence('legacy-v1-upgrade-no-automatic-retirement',record=record)

    def test_multiple_obligations_cannot_be_silently_discarded(self):
        b,t,record=self.unknown();b.close();other={**record,'pid':t.pid+1,'request_id':'f'*32}
        (self.root/'native-leases'/f'{t.pid+1}.lock.state').write_text(json.dumps(other))
        b,t=self.native();result=self.recover(b,record)
        self.assertEqual(result['reason'],'native_recovery_obligation_mismatch')
        self.evidence('multiple-pending-obligations',result=result)

    def test_closed_backend_cannot_recover_or_acquire_control(self):
        b,t,record=self.unknown();b.close()
        self.assertEqual(self.recover(b,record)['reason'],'dispatch_stopped')
        self.assertFalse(b.action(APP,'input','type_text',text='NEW')['action_sent'])
        self.evidence('closed-backend-recovery-refused')

    def test_directory_failure_plus_rollback_failure_cannot_publish_clean(self):
        b,t,record=self.unknown();b.quiesce()
        original=os.fsync;calls=0;renames=[]
        def fsync(fd):
            nonlocal calls
            calls+=1
            # Old ordering: clean file sync succeeds, then dir sync fails.
            # V3 ordering: the directory preflight fails before clean exists.
            if calls==1:raise OSError('directory unavailable')
            return original(fd)
        def rename(*args):
            renames.append(args)
            raise OSError('rollback/rename unavailable')
        with patch('computer.local_native.os.fsync',side_effect=fsync),patch('computer.local_native.os.replace',side_effect=rename):
            result=self.recover(b,record)
        self.assertNotEqual(result['status'],'ok');self.assertEqual(renames,[])
        other,transport=self.native(RecoveryTransport('normal'));other.inspect_tree(APP)
        self.assertEqual(other.qualify_action('type_text',APP,{'handle':'input'})['reason'],'input_cleanup_unknown')
        self.assertEqual(t.sent+transport.sent,0)
        self.evidence('compound-storage-failure-before-clean-publication',result=result)
