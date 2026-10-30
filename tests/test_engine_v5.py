from pathlib import Path
import tempfile
import unittest

from agent.engine_v5 import EngineV5Policy
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.safety import CapabilityPolicy
from agent.session import AgentSession, SessionBudgets
from agent.stabilization import HostVerification, StabilizationControls
from tests.test_runtime_api import Backend, answer, call


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def make(self, *steps, **kwargs):
        return AgentSession(create_default_registry(self.root,permission_mode=kwargs.pop('permission','full-permission')),
            backend=Backend(*steps),policy='cloud-only',streaming=False,engine_policy=EngineV5Policy(),
            retry_policy=RetryPolicy(max_attempts=1),budgets=SessionBudgets(max_steps=10,max_token_units=1000000),
            stabilization=StabilizationControls(stagnation_limit=0),**kwargs)
    def write(self, id='write'):
        return answer(None,call('apply_patch',{'changes':[{'path':'one.txt','operation':'create','content':'proof'}]},id))

    def test_minimal_has_complete_short_prompt_but_the_same_tools_and_approval(self):
        from agent.engine_v5 import prompt, PROMPT
        standard=self.make(answer('hello'))
        minimal=self.make(self.write(),answer('done'),prompt_profile='minimal_agent_v2',permission='approve-mutations')
        self.assertLess(len(prompt(minimal)),len(prompt(standard))//4)
        self.assertNotIn(PROMPT,prompt(minimal))
        self.assertEqual(standard.registry.schemas(),minimal.registry.schemas())
        result=minimal.run_turn('create one.txt')
        self.assertEqual(result.status,'approval_required');self.assertFalse((self.root/'one.txt').exists())
        result=minimal.approve()
        self.assertEqual(result.status,'completed');self.assertEqual((self.root/'one.txt').read_text(),'proof')
        self.assertEqual(len(minimal.tool_history),1)

    def test_repeated_invalid_proposal_stops_before_dispatch(self):
        bad=lambda id:answer(None,call('apply_patch',{'changes':[{'path':'one.txt','content':'proof'}]},id))
        session=self.make(bad('a'),bad('b'),self.write(),answer('done'))
        result=session.run_turn('create one.txt')
        self.assertEqual(result.status,'incomplete');self.assertFalse((self.root/'one.txt').exists())
        self.assertEqual(len(session.tool_history),2)

    def test_safe_argument_repair_does_not_replay_effect(self):
        bad=answer(None,call('apply_patch',{'changes':[{'path':'one.txt','content':'proof'}]},'bad'))
        session=self.make(bad,self.write(),answer('done'))
        result=session.run_turn('create one.txt')
        self.assertEqual(result.status,'completed');self.assertEqual((self.root/'one.txt').read_text(),'proof')
        self.assertEqual(sum(r.get('side_effect_status')=='completed' for r in session.tool_history),1)

    def test_failed_execution_final_receives_bounded_feedback(self):
        def check(root,projection):
            good=(root/'one.txt').exists()
            return HostVerification('passed' if good else 'failed','fixture-existence',{},good,good,True)
        session=self.make(answer('premature'),self.write(),answer('done'),completion_check=check,
                          verification_callback=lambda root,result:check(root,None))
        result=session.run_turn('create one.txt')
        self.assertEqual(result.status,'completed');self.assertEqual(result.completion['v5_repairs'],1)
        self.assertEqual(result.completion['execution'],'completed')

    def test_mutation_approval_survives_v5(self):
        session=self.make(self.write(),answer('done'),permission='approve-mutations')
        result=session.run_turn('create one.txt')
        self.assertEqual(result.status,'approval_required');self.assertFalse((self.root/'one.txt').exists())
        result=session.approve()
        self.assertEqual(result.status,'completed');self.assertEqual(len(session.tool_history),1)

    def test_partial_tool_output_never_executes(self):
        response=self.write();response.finish_reason='length'
        session=self.make(response,answer('partial'))
        result=session.run_turn('create one.txt')
        self.assertNotEqual(result.status,'completed');self.assertFalse((self.root/'one.txt').exists())

    def test_final_verification_failure_can_recover_without_tools(self):
        def check(root,value):return HostVerification('passed','fixture',{},True,True,True)
        def final(root,result):
            good=result.text=='DELIVERED'
            return HostVerification('passed' if good else 'failed','delivery',{},good,good,True)
        session=self.make(answer('wrong format'),answer('DELIVERED'),completion_check=check,verification_callback=final)
        result=session.run_turn('deliver')
        self.assertEqual(result.status,'completed');self.assertEqual(result.completion['attempts'],2)
        self.assertEqual(len(session.tool_history),0)

    def test_known_absent_builtin_read_is_failed_observation_not_unknown_effect(self):
        session=self.make(answer(None,call('read_file',{'path':'missing.txt'},'missing')),answer('done'))
        result=session.run_turn('read missing.txt and report absence')
        self.assertEqual(result.status,'completed')
        self.assertEqual(session.tool_history[0]['status'],'failed')
        self.assertEqual(result.completion['obligations']['unknown_receipts'],0)
        self.assertIsNone(session.tool_history[0]['read_receipt']['version'])

    def test_extension_cannot_mint_builtin_absence(self):
        session=self.make(answer(None,call('read_file',{'path':'missing.txt'},'missing')),answer('done'))
        def extension(workspace_root,path):raise FileNotFoundError('synthetic extension failure')
        session.registry._tools['read_file']=extension
        result=session.run_turn('inspect')
        self.assertEqual(result.status,'incomplete')
        self.assertEqual(result.completion['obligations']['unknown_receipts'],1)

    def test_absence_is_observed_only_after_gateway_approval(self):
        session=self.make(answer(None,call('read_file',{'path':'missing.txt'},'missing')),answer('absent'),permission='approve-all')
        result=session.run_turn('inspect')
        self.assertEqual(result.status,'approval_required')
        self.assertEqual(session.tool_history,[])
        result=session.approve()
        self.assertEqual(result.status,'completed')
        self.assertEqual(session.tool_history[0]['status'],'failed')

    def test_large_tool_group_does_not_consume_the_reserved_delivery_retry(self):
        for i in range(8):(self.root/f'part{i}.txt').write_text('synthetic evidence\n'*500)
        reads=answer(None,*[call('read_file',{'path':f'part{i}.txt'},f'read-{i}') for i in range(8)])
        def ready(root,projection):return HostVerification('passed','all requested read receipts independently checked',{},True,True,True)
        def verify(root,result):
            good=result.text=='DELIVERED'
            return HostVerification('passed' if good else 'failed','final-format',{},good,good,True)
        backend=Backend(reads,answer('wrong format'),answer('DELIVERED'))
        session=AgentSession(create_default_registry(self.root,permission_mode='full-permission'),backend=backend,
            policy='cloud-only',streaming=False,engine_policy=EngineV5Policy(),completion_check=ready,verification_callback=verify,
            budgets=SessionBudgets(max_steps=8,max_output_tokens=1024,max_token_units=140000),
            stabilization=StabilizationControls(stagnation_limit=0))
        result=session.run_turn('Read all eight files, then give the required final format.')
        self.assertEqual(result.status,'completed')
        self.assertEqual(len(session.tool_history),8)
        self.assertEqual(result.completion['attempts'],2)
        self.assertLessEqual(result.runtime_metrics['admission_units'],140000)
        self.assertTrue(any(e.type=='ContextCompacted' for e in session.events.events))


if __name__=='__main__':unittest.main()
