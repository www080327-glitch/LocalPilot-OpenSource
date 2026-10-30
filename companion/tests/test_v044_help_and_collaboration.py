"""Real native HTTP/SQLite with SCRIPTED local/cloud models; no provider charges."""
from dataclasses import replace
import json
import os
import secrets
import unittest
from unittest.mock import Mock, patch

from companion.tests import test_v044_service as fixtures
from companion.runtime.service import Companion


class HelpCollaborationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ServiceContractTests(methodName='test_authenticated_health_checks_subject_and_persistence')
        self.fixture.setUp();f=self.fixture
        from tests.test_runtime_api import Backend, answer
        from agent.session import AgentSession, SessionBudgets
        from agent.registry import ToolRegistry
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        from agent.policy import DataPolicy
        from localpilot_service.security import Principal
        self.answer=answer;self.cloud=Backend(answer('Cloud synthetic answer'))
        self.cloud.service_reasoning_only=True
        def cloud_factory(callback):
            return AgentSession(ToolRegistry(f.workspace),cloud_backend=self.cloud,policy='cloud-only',
                data_policy=DataPolicy(local_only=False),runtime_tools=False,prompt_profile='minimal_0',budgets=SessionBudgets(max_steps=1,max_output_tokens=256),
                hybrid_policy=HybridPolicy(CloudEgressPolicy('REQUIRES_APPROVAL')),
                hybrid_backends={'selected':self.cloud},hybrid_primary='selected',event_callback=callback)
        f.service.routes['cloud']=cloud_factory
        principal=f.access.principals['companion']
        f.access.principals['companion']=replace(principal,routes={'localpilot':'localpilot','companion-cloud-reasoning':'cloud'})
        token=secrets.token_urlsafe(32)
        f.access.principals['resource']=Principal('resource',token,operator=True,
            scopes=frozenset({'read','resource_control'}),approval_for=('companion',))
        self.environment=patch.dict(os.environ,LOCALPILOT_COMPANION_RESOURCE_TOKEN=token);self.environment.start()
        f.server.catalog['cloud']={'adapter':'deepseek','model':'scripted-cloud','cloud_egress':'REQUIRES_APPROVAL',
            'reasoning_only':True,'prompt_profile':'minimal_0','deployment_status':'ready'}
        f.server.catalog['localpilot']['local_model_lifecycle']={'release_after_task':True,'control_surface_required':True}
        config=replace(f.config,low_power_policy='always',localpilot_analysis_route='localpilot',localpilot_expected_local_model='script-provider')
        self.app=Companion(config);self.app.controls.ui_live=lambda:True;self.app.monitor_task=Mock()
        self.app.resources.sampler=lambda:{'on_ac_power':True,'memory_available_bytes':40*1024**3,'system_cpu_percent':0,'battery_discharge_watts':None}

    def tearDown(self):
        self.app.monitor_stop.set();self.app.channel.stop();self.app.store.close();self.app.lock.close()
        self.environment.stop();self.fixture.tearDown()

    def minimal(self,answer=None):
        self.fixture.server.catalog['localpilot'].update(reasoning_only=True,prompt_profile='minimal_0')
        if answer is not None:self.fixture.backend.steps[:]=[answer]
        prepared=self.app.ask('Explain this synthetic public question')
        self.assertEqual(prepared['status'],'inference_prepared')
        ticket=prepared['control']['id'];self.app.controls.ack(ticket)
        result=self.app.controls.start(ticket)
        self.fixture.service.wait(result['task_id'])
        return result['task_id']

    def observe(self,task_id):return self.app.command({'command':'task_status','task_id':task_id})

    def finish_cloud(self,result):
        self.fixture.service.wait(result['task_id'])
        self.observe(result['task_id'])  # real pending cloud-egress action
        self.fixture.service.wait(result['task_id'])
        return self.observe(result['task_id'])

    def test_standard_agent_cannot_start_before_help_confirmation(self):
        self.app.store.set("inference_options",{"allow_local_on_battery":True,"allow_automatic_cloud":True})
        self.fixture.server.catalog['localpilot'].update(reasoning_only=False,prompt_profile='standard')
        prepared=self.app.ask('请帮我执行这项合成 Agent 任务',force_help=True)
        self.assertIn('agent_help',prepared['control']['required_confirmations'])
        ticket=prepared['control']['id'];self.app.controls.ack(ticket)
        self.assertEqual(self.app.controls.start(ticket)['status'],'confirmation_required')
        self.assertEqual(len(self.fixture.service.tasks),0)
        result=self.app.controls.start(ticket,True)
        self.fixture.service.wait(result['task_id'])
        record=self.app.store.get('localpilot_tasks')[result['task_id']]
        self.assertEqual(record['transport']['mode'],'execution')
        self.assertTrue(record['transport']['user_help_approved'])
        self.assertEqual(self.cloud.requests,[])

    def test_confirmed_standard_agent_uses_only_isolated_workspace_tool(self):
        from agent.session import AgentSession
        from agent.registry import create_default_registry
        from tests.test_runtime_api import call
        (self.fixture.workspace/'synthetic.txt').write_text('SYNTHETIC_FILE_CONTENT')
        self.fixture.backend.steps[:]=[self.answer(None,call('read_file',{'path':'synthetic.txt'})),self.answer('Read the synthetic file')]
        self.fixture.service.routes['localpilot']=lambda cb:AgentSession(create_default_registry(self.fixture.workspace,permission_mode='approve-mutations'),backend=self.fixture.backend,policy='cloud-only',event_callback=cb)
        p=self.app.ask('请帮我读取合成测试文件',force_help=True);ticket=p['control']['id'];self.app.controls.ack(ticket)
        self.assertEqual(len(self.fixture.backend.requests),0)
        result=self.app.controls.start(ticket,True);self.fixture.service.wait(result['task_id'])
        final=self.observe(result['task_id'])
        self.assertEqual(final['status'],'completed')
        self.assertEqual(len(final['task']['tools']),1)
        self.assertIn('SYNTHETIC_FILE_CONTENT',json.dumps([m.to_dict() for m in self.fixture.backend.requests[1]['messages']]))
        self.assertEqual(len(self.cloud.requests),0)

    def test_minimal_route_cannot_masquerade_as_standard_agent(self):
        self.fixture.server.catalog['localpilot'].update(reasoning_only=True,prompt_profile='minimal_0')
        p=self.app.ask('请帮我执行合成任务',force_help=True);ticket=p['control']['id'];self.app.controls.ack(ticket)
        result=self.app.controls.start(ticket,True)
        self.assertEqual(result['error']['code'],'standard_execution_route_required')
        self.assertEqual(len(self.fixture.service.tasks),0)

    def test_detected_problem_only_offers_help_user_acceptance_grants_once(self):
        self.fixture.server.catalog['localpilot'].update(reasoning_only=False,prompt_profile='standard')
        notice=self.app.policy.record('repeated_error','synthetic','多次出现同一错误，是否需要帮助？')
        self.assertEqual(self.fixture.backend.requests,[])
        prepared=self.app.command({'command':'notice_action','id':notice,'action':'help'})
        self.assertEqual(prepared['control']['mode'],'execution')
        self.assertNotIn('agent_help',prepared['control']['required_confirmations'])
        self.assertEqual(len(self.fixture.service.tasks),0)
        ticket=prepared['control']['id'];self.app.controls.ack(ticket)
        result=self.app.controls.start(ticket)
        self.assertTrue(result['task_id'])
        with self.assertRaises(ValueError):self.app.command({'command':'notice_action','id':notice,'action':'help'})

    def test_local_failure_prompts_cloud_no_provider_call_before_yes(self):
        task=self.minimal(RuntimeError('synthetic local failure'))
        self.observe(task)
        control=self.app.controls.current
        self.assertEqual(control['kind'],'cloud')
        self.assertIn('cloud_question_egress',control['required_confirmations'])
        self.assertEqual(self.cloud.requests,[])
        ticket=control['id'];self.app.controls.ack(ticket)
        self.assertEqual(self.app.controls.start(ticket)['status'],'confirmation_required')
        self.assertEqual(self.cloud.requests,[])
        result=self.app.controls.start(ticket,True);self.finish_cloud(result)
        self.assertEqual(len(self.cloud.requests),1)
        self.assertEqual(len(self.fixture.backend.requests),1)
        self.assertNotEqual(result['session_id'],self.app.store.get('localpilot_tasks')[task]['result']['session_id'])

    def test_capability_hint_only_suggests_cloud_and_never_sends_local_answer(self):
        self.app.store.set('inference_options',{'allow_automatic_cloud':True})
        task=self.minimal(self.answer('[NEEDS_CLOUD] PRIVATE_LOCAL_ANSWER: more capable model needed'))
        result=self.observe(task)
        self.assertTrue(result['reasoning_help_requested'])
        control=self.app.controls.current
        self.assertIn('cloud_question_egress',control['required_confirmations'])
        self.assertEqual(self.cloud.requests,[])
        self.app.controls.ack(control['id']);cloud_task=self.app.controls.start(control['id'],True)
        self.finish_cloud(cloud_task)
        payload=json.dumps([m.to_dict() for m in self.cloud.requests[0]['messages']])
        self.assertNotIn('PRIVATE_LOCAL_ANSWER',payload)
        self.assertIn('Explain this synthetic public question',payload)

    def test_enabled_cloud_option_allows_hard_failure_after_visible_control(self):
        self.app.store.set('inference_options',{'allow_automatic_cloud':True})
        task=self.minimal(RuntimeError('synthetic local failure'));self.observe(task)
        control=self.app.controls.current
        self.assertEqual(control['required_confirmations'],[])
        self.assertEqual(self.cloud.requests,[])
        self.app.controls.ack(control['id']);result=self.app.controls.start(control['id'])
        self.finish_cloud(result);self.assertEqual(len(self.cloud.requests),1)

    def test_unverified_completed_answer_does_not_trigger_paid_escalation(self):
        task=self.minimal(self.answer('Synthetic ordinary answer'));self.observe(task)
        self.assertEqual(self.app.controls.current['kind'],'local')
        self.assertEqual(self.cloud.requests,[])

    def test_user_stop_or_unknown_never_triggers_cloud(self):
        task=self.minimal(self.answer('[NEEDS_CLOUD] need assistance'))
        self.app.controls.stop_event.set();self.observe(task)
        self.assertEqual(self.app.controls.current['kind'],'local')
        self.assertEqual(self.cloud.requests,[])
        self.app.controls.stop_event.clear()
        result=self.app.localpilot.status(task);result['unknown_mutation']=True
        self.app.receive_task_update(task,result)
        self.assertEqual(self.app.controls.current['kind'],'local')

    def test_duplicate_terminal_event_cannot_repeat_offer_after_decline(self):
        from concurrent.futures import Future
        task=self.minimal(RuntimeError('local failed'));result=self.observe(task)
        ticket=self.app.controls.current['id'];future=Future();self.app.controls.stop_async(ticket,future)
        item=self.app.queue.get(timeout=1);self.app.controls.stopped(item[1],item[2])
        self.app.receive_task_update(task,result)
        self.assertEqual(self.app.controls.current['id'],ticket)
        self.assertEqual(self.app.controls.current['phase'],'stopped')
        self.assertEqual(self.cloud.requests,[])

    def test_unreleased_model_blocks_cloud_and_keeps_emergency_stop_available(self):
        from concurrent.futures import Future
        task=self.minimal(RuntimeError('local failure'))
        result=self.app.localpilot.status(task)
        result['model_resource']={'managed':True,'model_process_alive':True}
        self.app.receive_task_update(task,result)
        self.assertEqual(self.app.controls.current['phase'],'cleanup_required')
        self.assertEqual(self.cloud.requests,[])
        ticket=self.app.controls.current['id'];future=Future();self.app.controls.stop_async(ticket,future)
        self.assertEqual(future.result()['status'],'stopping')
        item=self.app.queue.get(timeout=2);self.app.controls.stopped(item[1],item[2])

    def test_provider_change_after_review_cannot_send_question_elsewhere(self):
        task=self.minimal(RuntimeError('local failure'));self.observe(task)
        ticket=self.app.controls.current['id'];self.app.controls.ack(ticket)
        self.fixture.server.catalog['cloud']['adapter']='remote-openai'
        result=self.app.controls.start(ticket,True)
        self.assertEqual(result['error']['code'],'cloud_backend_not_deepseek')
        self.assertEqual(len(self.cloud.requests),0)
        self.assertEqual(len(self.fixture.service.tasks),1)

    def test_execution_failure_never_replayed_to_cloud(self):
        self.fixture.backend.steps[:]=[RuntimeError('synthetic agent failure')]
        p=self.app.ask('请帮我执行合成任务',force_help=True);ticket=p['control']['id'];self.app.controls.ack(ticket)
        task=self.app.controls.start(ticket,True)['task_id'];self.fixture.service.wait(task);self.observe(task)
        self.assertEqual(self.app.controls.current['kind'],'local');self.assertEqual(self.cloud.requests,[])
