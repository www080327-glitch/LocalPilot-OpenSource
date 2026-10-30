"""Consumer input bounds and small-first policy; scripted adapters, no weights."""
import json,unittest
from companion.escalation.localpilot import fit_task_input,prepare_context,TransportFailure
from companion.escalation.provider import EscalationRequest
from companion.model.backend import ModelManager
import companion.tests.test_v044_automatic_local as fixtures

class InputBudgetTests(unittest.TestCase):
    def test_metadata_is_omitted_without_truncating_original_question(self):
        q='请创建指定的合成验收文件，并等待工具审批。'
        request=EscalationRequest(q,'test','test',[{'id':'a','summary':'源'*3000},{'id':'b','summary':'文'*3000}],[],[],{'local_only':True},'')
        context,_=prepare_context(request)
        wire,_=fit_task_input(context)
        self.assertLessEqual(len(json.dumps(wire,ensure_ascii=False).encode()),4096)
        payload=json.loads(wire);self.assertEqual(payload['user_request'],q)
        self.assertGreater(payload['source_context']['omitted_records'],0)
    def test_oversized_original_is_refused_and_cloud_is_exact_question_only(self):
        request=EscalationRequest('验'*1500,'test','test',[],[],[],{'local_only':False},'')
        context,_=prepare_context(request)
        with self.assertRaises(TransportFailure):fit_task_input(context,question_only=True)
        context['user_request']='17 + 25?'
        wire,_=fit_task_input(context,question_only=True);self.assertEqual(wire,'17 + 25?')

class SmallFirstTests(unittest.TestCase):
    setUp=fixtures.AutomaticLocalTests.setUp
    tearDown=fixtures.AutomaticLocalTests.tearDown
    def use_primary(self,status='ok'):
        class Fixed:
            def complete(self,messages,max_tokens):return {'status':status,'text':'13' if status=='ok' else '', 'finish_reason':'stop'}
            def unload(self):pass
        self.app.model=ModelManager(self.app.config,adapter=Fixed())
    def test_working_small_model_answers_without_heavy_service(self):
        self.use_primary();result=self.app.ask('6 + 7?')
        self.assertEqual(result['text'],'13');self.assertEqual(self.app.model.inferences,1)
        self.assertEqual(self.fixture.service.tasks,{})
        self.assertEqual(self.app.localpilot.network_calls,0)
    def test_concrete_small_failure_prepares_heavy_local_without_cloud(self):
        self.use_primary('unavailable');result=self.app.ask('6 + 7?')
        self.assertEqual(result['status'],'inference_prepared');self.assertEqual(result['control']['kind'],'local')
        self.assertEqual(self.app.model.inferences,1);self.assertEqual(self.fixture.service.tasks,{})

class ClosedAffinityTests(unittest.TestCase):
    setUp=fixtures.AutomaticLocalTests.setUp
    tearDown=fixtures.AutomaticLocalTests.tearDown
    def test_new_explicit_request_uses_new_session_after_authoritative_closed_state(self):
        from unittest.mock import Mock
        from companion.tests.test_v044_service import request
        self.app.controls._test_bypass=True;self.app.monitor_task=Mock();self.app.config.low_power_policy='off'
        self.fixture.server.catalog['localpilot'].update(reasoning_only=False,prompt_profile='standard')
        p=self.app.prepare_escalation(request('first'),automatic=False)
        one=self.app.command({'command':'submit_escalation','approved':True,'expected_digest':p['review_digest']})
        self.fixture.service.wait(one['task_id']);self.fixture.service.close_session(one['session_id'])
        p=self.app.prepare_escalation(request('new question'),automatic=False)
        two=self.app.command({'command':'submit_escalation','approved':True,'expected_digest':p['review_digest']})
        self.assertNotEqual(one['session_id'],two['session_id'])
        self.fixture.service.wait(two['task_id']);self.assertEqual(len(self.fixture.backend.requests),2)
