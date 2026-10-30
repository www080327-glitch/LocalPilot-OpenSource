"""Scripted controls; real SQLite/Registry/Session. No physical GUI claims."""
from copy import deepcopy
from pathlib import Path
import json
import hashlib
import tempfile
import unittest

from agent.engine_v5 import EngineV5Policy
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from agent.hybrid import CloudEgressPolicy
from computer.native_macos import ComputerScope, NativeMacOSBackend, NativeComputerRuntime, ActionJournal, ALL_WRITES
from tests.test_computer_runtime import MemoryAX, ScriptBackend, condition, response, APP


BINDING={'status':'ok','pid':9,'process_birth':'1.2','window_id':7,'window_title':'Test','bounds':[1,2,400,300]}

class NativeTransport(MemoryAX):
    def __init__(self):
        super().__init__()
        for node in self.nodes:
            node['window_binding']=deepcopy(BINDING);node['bounds']=[10,20,100,30];node['enabled']=True
        self.validation='ok';self.ops=[];self.throw=None
    def request(self, **r):
        self.ops.append(deepcopy(r))
        if r['op']=='cu_validate':return {'status':'ok'} if self.validation=='ok' else {'status':'error','error':self.validation,'action_sent':False}
        if r['op']=='action':
            if self.throw:raise TimeoutError('scripted dispatch/response uncertainty')
            return self.action(r['app'],r['handle'],r['kind'],**{k:v for k,v in r.items() if k not in {'op','app','handle','kind'}})
        if r['op']=='cu_focus':
            self.env.update(frontmost_app=APP,frontmost_pid=9)
            return {'status':'ok','action_sent':True,'window_focused':True}
        if r['op']=='cu_text':
            if self.throw:raise TimeoutError('scripted possible input dispatch')
            self.nodes[0]['value']+=r['text'];self.sent+=1
            return {'status':'ok','action_sent':True,'posted_events':2,'input_cleanup':'owned_pairs_POSTED_not_delivery_proof'}
        if r['op']=='cu_shortcut':
            self.nodes[0]['value']='shortcut';self.sent+=1
            return {'status':'ok','action_sent':True,'posted_events':2,'input_cleanup':'owned_pairs_POSTED_not_delivery_proof'}
        if r['op']=='cu_capture':return {'status':'error','error':'screen_capture_permission_missing','action_sent':False}
        raise AssertionError(r['op'])


class NativeComputerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.instances=[];self.workspace=self.root/'workspace';self.workspace.mkdir()
        self.t=NativeTransport();self.r=self.make(self.t)
        self.registry=create_default_registry(self.workspace,permission_mode='full-permission');self.r.register_tools(self.registry)
    def tearDown(self):
        for r in self.instances:
            try:r.close()
            except Exception:pass
        self.temp.cleanup()
    def make(self,transport=None,path='run',**scope):
        directory=self.root/path;directory.mkdir(mode=0o700,exist_ok=True)
        b=NativeMacOSBackend([APP],directory/'control',transport=transport or NativeTransport())
        options={'actions':frozenset(ALL_WRITES),'background':True,'foreground':True,'capture':True,**scope}
        r=NativeComputerRuntime(b,scopes=[ComputerScope(APP,('Test',),**options)],evidence_directory=directory,verification_timeout=0)
        self.instances.append(r);return r
    def observed(self,r=None):
        r=r or self.r;return r.inspect_tree(APP)['observation']
    def act(self,name='set_value',r=None,**kwargs):
        r=r or self.r;token=self.observed(r)
        return r.act(name,APP,'input',token,condition(),**({'value':'new'} if name=='set_value' else {}),**kwargs)
    def test_semantic_action_has_durable_verified_receipt(self):
        receipt=self.act();self.assertTrue(receipt['verified']);self.assertEqual(receipt['journal_state'],'verified');self.assertFalse(self.r.journal.blocked(APP));self.assertEqual(self.t.sent,1)
    def test_chinese_unicode_replacement(self):
        token=self.observed();result=self.r.act('input_text',APP,'input',token,condition(value='你好🙂'),text='你好🙂',mode='replace')
        self.assertTrue(result['verified']);self.assertEqual(self.t.nodes[0]['value'],'你好🙂');self.assertEqual(result['input_method'],'AXValue_Unicode_replacement')
    def test_scope_rejects_system_app(self):
        for app in ['com.apple.SecurityAgent','com.apple.systempreferences','com.apple.keychainaccess']:
            with self.assertRaises(ValueError):ComputerScope(app,('Test',))
    def test_empty_wildcard_and_invalid_lifetime_scopes(self):
        for titles in [(),['Test'],('',)]:
            with self.assertRaises(ValueError):ComputerScope(APP,titles)
        for duration in [float('nan'),0,3601,True]:
            with self.assertRaises(ValueError):ComputerScope(APP,('Test',),lifetime_seconds=duration)
    def test_other_window_rejected(self):
        result=self.r.inspect_tree(APP,window_title='Private');self.assertEqual(result['error'],'window_outside_scope');self.assertEqual(self.t.sent,0)
    def test_binding_unknown_rejected(self):
        self.t.nodes[0]['window_binding']={'status':'UNKNOWN'};self.assertEqual(self.act()['error'],'target_scope_or_identity_unknown');self.assertEqual(self.t.sent,0)
    def test_replacement_move_and_process_generation_rejected_by_helper(self):
        for reason in ['target_window_or_process_changed','stale_element_path','stale_element_identity']:
            self.t.validation=reason;self.assertEqual(self.act()['error'],reason)
        self.assertEqual(self.t.sent,0)
    def test_truncated_tree_refuses_mutation(self):
        token=self.observed();self.r.observations[APP]['tree']['truncated']=True
        result=self.r.act('set_value',APP,'input',token,condition(),value='new');self.assertEqual(result['error'],'incomplete_observation');self.assertEqual(self.t.sent,0)
    def test_stale_observation_rejected(self):
        old=self.observed();self.observed();result=self.r.act('set_value',APP,'input',old,condition(),value='new');self.assertEqual(result['error'],'stale_observation')
    def test_secure_control_refused(self):
        self.t.nodes[0]['protected']=True;self.assertEqual(self.act()['error'],'target_scope_or_identity_unknown')
    def test_background_human_ime_protection_preserved(self):
        self.t.env['focused_element']['role']='AXTextArea';result=self.act();self.assertEqual(result['error'],'user_text_input_active');self.assertEqual(self.t.sent,0)
    def test_foreground_requires_explicit_lease(self):
        self.t.env.update(frontmost_app=APP,frontmost_pid=9);self.assertEqual(self.act()['error'],'foreground_authorization_required')
    def test_focus_always_approval_gated_even_full(self):
        token=self.observed();args={'app':APP,'element':'input','observation':token,'postcondition':condition(value='old')}
        denied=self.registry.call('focus_window',args);self.assertEqual(denied['status'],'approval_required');self.assertFalse(self.r.foreground_leases)
        approved=self.registry.call('focus_window',args,approved=True);self.assertTrue(approved['verified']);self.assertIn(APP,self.r._focus_acquired)
    def test_focus_loss_does_not_silently_reactivate(self):
        self.r.grant_foreground(APP);token=self.observed();self.r.act('focus_window',APP,'input',token,condition(value='old'))
        self.t.env.update(frontmost_app='user.app',frontmost_pid=1)
        result=self.act();self.assertEqual(result['error'],'foreground_control_lost');self.assertTrue(self.r.paused)
    def test_insert_requires_foreground_and_preserves_unicode_chunk(self):
        self.r.grant_foreground(APP);self.t.env.update(frontmost_app=APP,frontmost_pid=9)
        token=self.observed();result=self.r.act('input_text',APP,'input',token,condition(value='old你好🙂'),text='你好🙂',mode='insert')
        self.assertTrue(result['verified']);self.assertEqual([r for r in self.t.ops if r['op']=='cu_text'][0]['text'],'你好🙂')
    def test_unknown_persists_across_runtime_restart(self):
        self.t.throw=True;result=self.act();self.assertEqual(result['journal_state'],'UNKNOWN');self.r.close()
        r=self.make(path='run');result=self.act(r=r);self.assertEqual(result['error'],'persistent_outcome_unknown')
    def test_pending_intent_survives_abrupt_owner_loss(self):
        self.r.journal.begin(APP,{'action':'press'});self.r.close()
        r=self.make(path='run');self.assertEqual(self.act(r=r)['error'],'persistent_outcome_unknown')
    def test_verification_failure_is_unknown_and_pauses(self):
        self.t.fault='noop';result=self.act();self.assertFalse(result['verified']);self.assertEqual(result['journal_state'],'UNKNOWN');self.assertTrue(self.r.paused)
    def test_no_dispatch_refusal_does_not_poison_journal(self):
        self.t.fault='stale_element';result=self.act();self.assertEqual(result['journal_state'],'not_dispatched');self.assertFalse(self.r.journal.blocked(APP))
    def test_revocation_and_cancel_stop_future_actions(self):
        self.r.revoke(APP)
        with self.assertRaises(PermissionError):self.observed()
        self.assertTrue(self.r.backend.stop_path.exists());self.assertEqual(self.t.sent,0)
    def test_takeover_blocks_wait_and_resume_needs_fresh_observation(self):
        token=self.observed();self.r.take_over();self.assertEqual(self.r.wait_state(APP,condition(),0)['error'],'computer_paused')
        self.r.resume();self.assertEqual(self.r.act('set_value',APP,'input',token,condition(),value='new')['error'],'stale_observation')
    def test_screenshot_permission_denied_is_explicit(self):
        token=self.observed();result=self.r.capture_window(APP,'input',token);self.assertEqual(result['error'],'screen_capture_permission_missing');self.assertEqual(self.t.sent,0)
    def test_visual_without_capture_refused(self):
        self.r.grant_foreground(APP);self.t.env.update(frontmost_app=APP,frontmost_pid=9);token=self.observed()
        result=self.r.act('visual_click',APP,'button',token,condition('result','applied'),capture='invented',point=[1,2]);self.assertEqual(result['error'],'stale_capture');self.assertEqual(self.t.sent,0)
    def test_task_journal_serializes_independent_connections(self):
        other=ActionJournal(self.root/'run'/'computer-actions.sqlite3');self.r.journal.begin(APP,{'action':'one'})
        try:
            with self.assertRaises(PermissionError):other.begin(APP,{'action':'two'})
        finally:other.close()
    def test_v5_registration_and_prompt_are_real_core(self):
        self.r.cloud_egress=CloudEgressPolicy('CLOUD_ALLOWED')
        backend=ScriptBackend(response())
        session=AgentSession(create_default_registry(self.workspace,permission_mode='full-permission'),backend=backend,policy='cloud-only',computer_runtime=self.r,engine_policy=EngineV5Policy(),streaming=False)
        names={s['function']['name'] for s in session.registry.schemas()};self.assertTrue({'input_text','capture_window','visual_click','request_handoff'}<=names)
        self.assertIn('Native Computer Use',session.messages[0].content);self.assertEqual(session.run_turn('read only').status,'completed')
    def test_cloud_requires_egress_before_any_model_request(self):
        self.r.cloud_egress=CloudEgressPolicy('REQUIRES_APPROVAL')
        backend=ScriptBackend(response());session=AgentSession(create_default_registry(self.workspace,permission_mode='full-permission'),backend=backend,policy='cloud-only',computer_runtime=self.r,engine_policy=EngineV5Policy(),streaming=False)
        result=session.run_turn('inspect public fixture');self.assertEqual(result.status,'approval_required');self.assertEqual(len(backend.requests),0);self.assertEqual(session.pending_approval['kind'],'cloud_egress')
    def test_local_only_egress_never_sends_computer_context(self):
        backend=ScriptBackend(response());session=AgentSession(create_default_registry(self.workspace,permission_mode='full-permission'),backend=backend,policy='cloud-only',computer_runtime=self.r,engine_policy=EngineV5Policy(),streaming=False)
        try:session.run_turn('inspect')
        except PermissionError:pass
        self.assertEqual(len(backend.requests),0)


    def test_model_view_removes_uncontrolled_application_identity(self):
        value={'before':{'frontmost_app':'private.app','frontmost_pid':55,'focused_element':{'role':'AXTextArea','identifier':'private.content','pid':55}},'before_frontmost_app':'private.app','before_frontmost_pid':55}
        public=self.r._public(value)
        self.assertNotIn('private',json.dumps(public));self.assertEqual(public['before']['focused_element']['role'],'AXTextArea')
        self.assertEqual(value['before']['frontmost_app'],'private.app')
    def test_scope_fingerprint_is_stable_across_foreground_lease(self):
        from agent.persistence import configuration
        session=AgentSession(create_default_registry(self.workspace),backend=ScriptBackend(response()),policy='cloud-only',computer_runtime=self.r,engine_policy=EngineV5Policy(),streaming=False)
        before=configuration(session);self.r.grant_foreground(APP);self.r.allow_frontmost=True
        self.assertEqual(before,configuration(session))
    def test_host_verifier_checks_fresh_UI_not_model_text(self):
        from types import SimpleNamespace
        self.r.completion_conditions=[{'app':APP,'window_title':'Test','postcondition':condition(value='old')}]
        self.assertEqual(self.r.host_verification(self.root,SimpleNamespace(text='wrong model claim')).status,'passed')
        self.t.nodes[0]['value']='changed'
        self.assertEqual(self.r.host_verification(self.root,SimpleNamespace(text='old')).status,'failed')
    def test_host_verification_cannot_clear_journal_unknown(self):
        self.r.completion_conditions=[{'app':APP,'window_title':'Test','postcondition':condition(value='old')}]
        self.r.journal.begin(APP,{'action':'uncertain'})
        self.assertEqual(self.r.host_verification(self.root).status,'unknown');self.assertTrue(self.r.journal.blocked(APP))
    def test_journal_retains_unknown_for_closed_summary(self):
        self.r.journal.begin(APP,{'action':'uncertain'});self.r.close()
        self.assertTrue(self.r.summary()['pending_intents'][APP])
    def test_clipboard_shortcuts_are_not_registered(self):
        from agent.tool_protocol import validate_arguments
        token=self.observed()
        for key in ('c','v'):
            with self.assertRaises(ValueError):self.registry.call('shortcut',{'app':APP,'element':'input','observation':token,'postcondition':condition(),'key':key,'modifiers':['command']},approved=True)
    def test_taskservice_SQLite_restart_preserves_human_reobservation(self):
        from localpilot_api.service import TaskService,TaskRequest,SETTLED
        workspace=self.root/'workspace';workspace.mkdir(exist_ok=True)
        def factory(callback):
            r=self.make(path='service-computer');r.cloud_egress=CloudEgressPolicy('CLOUD_ALLOWED')
            return AgentSession(create_default_registry(workspace,permission_mode='full-permission'),backend=ScriptBackend(response()),policy='cloud-only',computer_runtime=r,engine_policy=EngineV5Policy(),streaming=False,event_callback=callback)
        service=TaskService({'localpilot':factory},persistence=self.root/'service.sqlite3')
        task=service.create_task(TaskRequest('read generated state'))
        with service.condition:service.condition.wait_for(lambda:service.tasks[task['id']].status in SETTLED and not service.tasks[task['id']].executing,3)
        self.assertEqual(service.task_snapshot(task['id'])['status'],'completed')
        sid=task['session_id'];service.shutdown()
        restored=TaskService({'localpilot':factory},persistence=self.root/'service.sqlite3')
        try:
            runtime=restored.sessions[sid].runtime;self.assertTrue(runtime.computer.paused);self.assertFalse(runtime.computer.observations);self.assertFalse(runtime.computer.foreground_leases)
        finally:restored.shutdown()
    def test_pending_journal_is_UNKNOWN_in_service_recovery_class(self):
        from agent.persistence import recovery_class
        session=AgentSession(create_default_registry(self.workspace),backend=ScriptBackend(response()),policy='cloud-only',computer_runtime=self.r,engine_policy=EngineV5Policy(),streaming=False)
        self.r.journal.begin(APP,{'action':'lost owner'})
        self.assertEqual(recovery_class(session),'UNKNOWN_BLOCKED')

    def test_session_cancel_sets_native_fence_before_next_dispatch(self):
        session=AgentSession(create_default_registry(self.workspace),backend=ScriptBackend(response()),policy='cloud-only',computer_runtime=self.r,engine_policy=EngineV5Policy(),streaming=False)
        token=self.observed();session.request_cancel()
        self.assertTrue(self.r.backend.stop_path.exists());self.assertTrue(self.r.pause_requested.is_set())
        result=self.r.act('set_value',APP,'input',token,condition(),value='new');self.assertEqual(result['error'],'computer_paused');self.assertEqual(self.t.sent,0)

    def test_input_timeout_never_claims_cleanup_and_resume_cannot_clear_it(self):
        self.r.grant_foreground(APP);self.t.env.update(frontmost_app=APP,frontmost_pid=9);self.t.throw=True
        token=self.observed();result=self.r.act('input_text',APP,'input',token,condition(value='oldnew'),text='new',mode='insert')
        self.assertEqual(result['journal_state'],'UNKNOWN');self.assertEqual(self.r.backend.quiesce()['cleanup'],'UNKNOWN')
        self.assertEqual(self.r.resume()['error'],'persistent_outcome_unknown')
    def test_revoked_scope_cannot_be_resumed(self):
        self.r.revoke(APP);self.assertEqual(self.r.resume()['error'],'authorization_revoked_or_expired')

    def test_resume_keeps_only_newly_observed_native_window_bindings(self):
        self.observed();self.r.take_over();self.assertTrue(self.r.backend.stop_path.exists())
        result=self.r.resume();self.assertEqual(result['status'],'ok');self.assertIn('input',self.r.backend._bindings);self.assertFalse(self.r.backend.stop_path.exists())
        token=self.r.observations[APP]['token'];result=self.r.act('set_value',APP,'input',token,condition(),value='new');self.assertTrue(result['verified'])

    def test_control_journal_cannot_be_in_model_workspace(self):
        registry=create_default_registry(self.root)
        with self.assertRaises(ValueError):self.r.register_tools(registry)

    def test_locked_window_observation_never_queries_target(self):
        self.t.env['locked']=True
        result=self.r.inspect_windows(APP);self.assertEqual(result['error'],'locked_or_unknown');self.assertFalse(any(r['op']=='cu_windows' for r in self.t.ops))

    def test_explicit_foreground_scope_does_not_grant_or_require_background_qualification(self):
        t=NativeTransport();t.env.update(frontmost_app=APP,frontmost_pid=9)
        r=self.make(t,path='foreground-only',background=False);r.grant_foreground(APP)
        self.assertFalse(r.background_safe_apps);self.assertTrue(self.act(r=r)['verified'])

    def test_revocation_is_durable_and_blocks_a_second_runtime_in_same_scope(self):
        other=self.make(path='run');self.r.revoke(APP)
        with self.assertRaises(PermissionError):other.inspect_tree(APP)
        self.r.close();other.close();restored=self.make(path='run')
        self.assertEqual(restored.resume()['error'],'authorization_revoked_or_expired')
        self.assertTrue(restored.revocation_paths[APP].is_file())

    def test_revocation_HTTP_requires_host_control_and_blocks_pending_GUI_write(self):
        from localpilot_api.service import TaskService,TaskRequest,SETTLED
        from localpilot_api.server import APIServer
        from localpilot_api.client import Client
        from urllib.error import HTTPError
        import threading
        owners=[]
        def factory(callback):
            r=self.make(path='http-scope');r.cloud_egress=CloudEgressPolicy('CLOUD_ALLOWED')
            def write(messages):
                record=r.observations[APP]
                return response('set_value',{'app':APP,'element':'input','observation':record['token'],'postcondition':condition(),'value':'new'},'pending')
            b=ScriptBackend(response('inspect_tree',{'app':APP}),write,response())
            session=AgentSession(create_default_registry(self.workspace,permission_mode='approve-mutations'),backend=b,policy='cloud-only',computer_runtime=r,engine_policy=EngineV5Policy(),streaming=False,event_callback=callback)
            owners.append(session);return session
        service=TaskService({'localpilot':factory},persistence=self.root/'http-service.sqlite3')
        server=APIServer(('127.0.0.1',0),service,api_key='fixture-client',control_token='fixture-host-control')
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True);worker.start()
        try:
            task=service.create_task(TaskRequest('pending generated GUI write'))
            with service.condition:service.condition.wait_for(lambda:service.tasks[task['id']].status in SETTLED and not service.tasks[task['id']].executing,3)
            self.assertEqual(service.task_snapshot(task['id'])['status'],'requires_approval')
            url=f'http://127.0.0.1:{server.server_port}';ordinary=Client(url,api_key='fixture-client',timeout=3)
            path='/localpilot/v1/tasks/'+task['id']+'/computer/revoke'
            with self.assertRaises(HTTPError) as denied:ordinary.request(path,{'app':APP})
            self.assertEqual(denied.exception.code,403)
            host=Client(url,api_key='fixture-client',control_token='fixture-host-control',timeout=3)
            revoked=host.request(path,{'app':APP},control=True)
            self.assertEqual(revoked['status'],'requires_human');self.assertTrue(owners[0].computer.revocation_paths[APP].is_file())
            self.assertEqual(owners[0].computer.resume()['error'],'authorization_revoked_or_expired')
            self.assertEqual(owners[0].computer.backend.transport.sent,0)
        finally:server.shutdown();server.server_close();service.shutdown()

    def prepare_vision(self):
        self.t.nodes[0]['bounds']=[10,20,80,30];self.t.nodes[1]['bounds']=[100,100,80,30]
        token=self.observed();path=self.r.evidence/'captured.png';path.write_bytes(b'scripted-image-data')
        image={'app':APP,'at':self.r.clock(),'observation':token,'anchor_element':'input','path':str(path),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'width':800,'height':600,'window_binding':deepcopy(BINDING),
            'logical_frame':[1,2,400,300],'full_image_size':[800,600],'crop_pixels':[0,0,800,600]}
        self.r.captures={'capture-test':image};self.r.capture_history={'capture-test':deepcopy(image)}
        class Vision:
            calls=0
            response={'status':'ok','width':800,'height':600,'matches':[{'text':'Apply','confidence':1.0,'bounds_pixels':[230,190,40,40]}]}
            def locate(v,*args):v.calls+=1;return deepcopy(v.response)
            def compare(v,*args):v.calls+=1;return {'status':'ok','raw_bytes_equal':True,'thumbnail_changed_fraction':0}
            def close(v):pass
        self.r.vision=Vision();return token,image,self.r.vision
    def test_visual_OCR_maps_to_one_enabled_AX_control_without_dispatch(self):
        token,image,v=self.prepare_vision();result=self.r.locate_visual(APP,token,'capture-test','Apply')
        self.assertEqual(result['element'],'button');self.assertEqual(result['recommended_action'],'press');self.assertEqual(self.t.sent,0)
        self.assertIn('NOT_PROVEN',result['actionability']);self.assertFalse(result['cloud_sent'])
    def test_visual_OCR_duplicate_text_requires_human(self):
        token,image,v=self.prepare_vision();v.response=deepcopy(v.response);v.response['matches']*=2
        self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'visual_text_missing_or_ambiguous');self.assertEqual(self.t.sent,0)
    def test_visual_OCR_low_confidence_and_wrong_text_are_rejected(self):
        token,image,v=self.prepare_vision()
        for key,value in [('confidence',.2),('text','Other')]:
            v.response=deepcopy(type(v).response);v.response['matches'][0][key]=value
            self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'unreliable_visual_text')
    def test_visual_OCR_never_infers_enabled_from_pixels(self):
        self.t.nodes[1]['enabled']=False;token,image,v=self.prepare_vision()
        self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'visual_AX_target_missing_or_ambiguous');self.assertEqual(self.t.sent,0)
    def test_visual_OCR_changed_capture_never_reaches_vision(self):
        token,image,v=self.prepare_vision();Path(image['path']).write_bytes(b'changed')
        self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'stale_capture');self.assertEqual(v.calls,0)
    def test_visual_OCR_expired_capture_never_reaches_vision(self):
        token,image,v=self.prepare_vision();image['at']-=4
        self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'stale_capture');self.assertEqual(v.calls,0)
    def test_visual_OCR_different_image_geometry_is_rejected(self):
        token,image,v=self.prepare_vision();v.response=deepcopy(v.response);v.response['width']=801
        self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'visual_image_geometry_mismatch')
    def test_visual_image_cannot_escape_private_capture_root(self):
        token,image,v=self.prepare_vision();other=self.workspace/'outside.png';other.write_bytes(b'scripted-image-data');image['path']=str(other)
        self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'stale_capture');self.assertEqual(v.calls,0)
    def test_capture_comparison_never_reconciles_unknown(self):
        token,image,v=self.prepare_vision();self.r.capture_history['second']=deepcopy(image);self.r.journal.begin(APP,{'action':'uncertain'})
        result=self.r.compare_captures(APP,'capture-test','second');self.assertFalse(result['semantic_verification']);self.assertFalse(result['reconciles_UNKNOWN']);self.assertTrue(self.r.journal.blocked(APP))
    def test_capture_comparison_rejects_window_generation_change(self):
        token,image,v=self.prepare_vision();second=deepcopy(image);second['window_binding']['window_id']=8;self.r.capture_history['second']=second
        self.assertEqual(self.r.compare_captures(APP,'capture-test','second')['error'],'capture_comparison_scope_mismatch');self.assertEqual(v.calls,0)
    def test_capture_comparison_rejects_crop_change(self):
        token,image,v=self.prepare_vision();second=deepcopy(image);second['crop_pixels']=[1,0,799,600];self.r.capture_history['second']=second
        self.assertEqual(self.r.compare_captures(APP,'capture-test','second')['error'],'capture_comparison_scope_mismatch');self.assertEqual(v.calls,0)

    def test_disabled_semantic_control_is_rejected_before_journal_or_dispatch(self):
        self.t.nodes[0]['enabled']=False
        result=self.act();self.assertEqual(result['error'],'disabled_control');self.assertEqual(self.t.sent,0);self.assertFalse(self.r.journal.blocked(APP))

    def test_low_confidence_OCR_is_only_corroboration_with_exact_AX_label(self):
        token,image,v=self.prepare_vision();v.response=deepcopy(v.response);v.response['matches'][0]['confidence']=.5
        result=self.r.locate_visual(APP,token,'capture-test','Apply');self.assertEqual(result['strategy'],'B_OCR_AX_semantic_agreement');self.assertTrue(result['AX_label_agreement']);self.assertEqual(self.t.sent,0)
    def test_low_confidence_OCR_without_AX_label_never_returns_coordinates(self):
        self.t.nodes[1]['title']=None;token,image,v=self.prepare_vision();v.response=deepcopy(v.response);v.response['matches'][0]['confidence']=.5
        self.assertEqual(self.r.locate_visual(APP,token,'capture-test','Apply')['error'],'low_confidence_requires_AX_label_agreement');self.assertEqual(self.t.sent,0)

    def test_model_summary_bounds_diagnostics_without_erasing_unknown_or_receipts(self):
        self.r.last_receipt={'status':'error','action':'shortcut','app':APP,'action_sent':None,'verified':None,'error':'action_outcome_unknown','intent_id':'retained-intent','journal_state':'UNKNOWN','postcondition':condition(),'before':{'diagnostic':'x'*20000}}
        original=deepcopy(self.r.last_receipt)
        self.r.timings.extend([{'operation':'AX_tree','seconds':.1,'diagnostic':'x'*1000} for _ in range(100)])
        self.r.journal.begin(APP,{'action':'uncertain'})
        summary=self.r.model_summary();self.assertLess(len(json.dumps(summary)),4000)
        self.assertEqual(summary['last_receipt']['intent_id'],'retained-intent');self.assertEqual(summary['last_receipt']['journal_state'],'UNKNOWN');self.assertTrue(summary['pending_intents'][APP])
        self.assertEqual(self.r.last_receipt,original);self.assertEqual(len(self.r.timings),100);self.assertIn('before',self.r.summary()['last_receipt'])
    def test_native_model_working_state_fits_after_verified_write(self):
        session=AgentSession(create_default_registry(self.workspace),backend=ScriptBackend(response()),policy='cloud-only',computer_runtime=self.r,engine_policy=EngineV5Policy(),streaming=False)
        self.act();session.turn_id=1;session._computer_receipt_turn=1;session.working.task='Report three generated UI fields'
        session.working.computer=session._computer_summary()
        state=session.working.snapshot(phase='finalizing',plan=None,goals=[],pending=None,turn_id=1,budget={})
        self.assertEqual(state['computer']['last_receipt']['verified'],True)

if __name__=='__main__':unittest.main()
