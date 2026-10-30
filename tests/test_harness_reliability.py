"""V4.7 controlled safety/causality tests; no real model claims."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from agent.harness import HarnessPolicy,TaskContract,decision,file_evidence
from agent.finalization import FinalizationPolicy
from agent.persistence import snapshot_runtime,restore_runtime,PersistenceError
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession,SessionBudgets
from agent.stabilization import HostVerification,StabilizationControls
from tests.test_runtime_api import Backend,answer,call


def write(content='proof',operation='create',id='write'):
    change={'path':'one.txt','operation':operation}
    change.update({'content':content} if operation=='create' else {'old_text':'old','new_text':content})
    return answer(None,call('apply_patch',{'changes':[change]},id))


class HarnessReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def check(self,root,value):
        p=root/'one.txt';good=p.is_file() and p.read_text()=='proof'
        return HostVerification('passed' if good else 'failed','exact fixture content; harness independently checks receipts',
            {'one.txt':hashlib.sha256(p.read_bytes()).hexdigest()} if p.is_file() else {},good,good,True)
    def session(self,backend,policy=None,contract=None):
        return AgentSession(create_default_registry(self.root,permission_mode='full-permission'),backend=backend,
            policy='cloud-only',streaming=False,retry_policy=RetryPolicy(max_attempts=1),
            budgets=SessionBudgets(max_steps=12,max_token_units=4000000),stabilization=StabilizationControls(stagnation_limit=0),
            finalization_policy=FinalizationPolicy(),completion_check=self.check,verification_callback=self.check,
            harness_policy=policy or HarnessPolicy(),task_contract=contract or TaskContract(output_paths=('one.txt',)))
    def test_stale_pre_mutation_read_is_blocked_even_with_passing_host_checker(self):
        (self.root/'one.txt').write_text('old')
        s=self.session(Backend(answer(None,call('read_file',{'path':'one.txt'},'read')),write(operation='update'),answer('done')),
            HarnessPolicy(max_completion_repairs=0))
        r=s.run_turn('fix one.txt');self.assertEqual(r.status,'incomplete')
        self.assertEqual(r.completion['file_evidence']['failures'][0]['reason'],'missing_current_full_read_after_last_mutation')
    def test_missing_read_recovers_by_observation_without_mutation_replay(self):
        s=self.session(Backend(write(),answer('premature'),answer(None,call('read_file',{'path':'one.txt'},'fresh')),answer('done')))
        r=s.run_turn('create and verify');self.assertEqual(r.status,'completed')
        self.assertEqual(r.completion['harness_repairs'],1)
        self.assertEqual(sum(t['name']=='apply_patch' for t in s.tool_history),1)
    def test_same_call_id_cannot_refresh_old_read(self):
        (self.root/'one.txt').write_text('old')
        s=self.session(Backend(answer(None,call('read_file',{'path':'one.txt'},'read')),write(operation='update'),
            answer(None,call('read_file',{'path':'one.txt'},'read')),answer('done')),HarnessPolicy(max_completion_repairs=0))
        self.assertEqual(s.run_turn('fix').status,'incomplete')
    def test_external_change_after_read_refuses_completion(self):
        def changed(messages):
            (self.root/'one.txt').write_text('external');return answer('done')
        s=self.session(Backend(write(),answer(None,call('read_file',{'path':'one.txt'},'read')),changed),HarnessPolicy(max_completion_repairs=0))
        self.assertNotEqual(s.run_turn('create').status,'completed')
    def test_old_turn_receipts_do_not_prove_new_generation(self):
        s=self.session(Backend(write(),answer(None,call('read_file',{'path':'one.txt'},'read')),answer('done'),answer('done')),HarnessPolicy(max_completion_repairs=0))
        self.assertEqual(s.run_turn('create').status,'completed')
        self.assertEqual(s.run_turn('new task').status,'incomplete')
    def test_identical_invalid_proposal_stops_with_zero_dispatch(self):
        bad=lambda id:answer(None,call('apply_patch',{'changes':[{'path':'one.txt','content':'proof'}]},id))
        s=self.session(Backend(bad('a'),bad('b'),write()))
        self.assertEqual(s.run_turn('create').status,'incomplete')
        self.assertFalse((self.root/'one.txt').exists());self.assertEqual(len(s.tool_history),2)
        self.assertFalse(s.tool_history[-1]['payload']['result']['repair_allowed'])
    def test_not_dispatched_parameter_correction_is_accepted(self):
        bad=answer(None,call('apply_patch',{'changes':[{'path':'one.txt','content':'proof'}]},'bad'))
        s=self.session(Backend(bad,write(),answer(None,call('read_file',{'path':'one.txt'},'read')),answer('done')))
        self.assertEqual(s.run_turn('create').status,'completed')
        self.assertEqual(s.tool_history[0]['payload']['result']['stage'],'not_dispatched')
    def test_dispatched_unknown_is_never_repaired_or_replayed(self):
        s=self.session(Backend(write(),write(id='fresh-id'),answer('done')))
        original=s.registry._tools['apply_patch'];calls=[]
        def unknown(**kw):
            calls.append(kw);v=original(**kw);return {**v,'status':'unknown','action_may_have_applied':True}
        s.registry._tools['apply_patch']=unknown
        r=s.run_turn('create');self.assertEqual(r.status,'incomplete');self.assertEqual(len(calls),1)
        self.assertEqual(r.completion['execution'],'unknown_blocked');self.assertNotIn('harness_repairs',r.completion)
        self.assertEqual(s.tool_history[1]['payload']['error']['type'],'unknown_effect_quarantined')
    def test_goal_repair_requires_explicit_model_action(self):
        def complete(messages):
            payload=json.loads(next(m.content for m in messages if m.role=='tool' and m.tool_call_id=='goal'))
            return answer(None,call('manage_goal',{'action':'complete','id':payload['result']['id']},'complete'))
        s=self.session(Backend(answer(None,call('manage_goal',{'action':'create','description':'create verified proof'},'goal')),
            write(),answer(None,call('read_file',{'path':'one.txt'},'read')),answer('premature'),complete,answer('done')))
        r=s.run_turn('create');self.assertEqual(r.status,'completed');self.assertEqual(r.completion['harness_repairs'],1)
        self.assertEqual(s.goals.list()[0].status,'done')
    def test_pending_approval_is_retained_without_completion_repair(self):
        s=self.session(Backend(write()));s.set_permissions('approve-mutations')
        r=s.run_turn('create');self.assertEqual(r.status,'approval_required');self.assertFalse((self.root/'one.txt').exists())
        self.assertNotIn('harness_repairs',s._completion)
    def test_checkpoint_refuses_changed_contract_and_preserves_repair_count(self):
        s=self.session(Backend());s.run_turn=lambda x:None
        s._completion={'harness_repairs':2,'attempts':0,'history':[]};data=snapshot_runtime(s)
        restored=self.session(Backend());restore_runtime(restored,data)
        self.assertEqual(restored._completion['harness_repairs'],2)
        changed=self.session(Backend(),contract=TaskContract(output_paths=('two.txt',)))
        with self.assertRaises(PersistenceError):restore_runtime(changed,data)
    def test_decisions_are_public_role_based(self):
        p=HarnessPolicy()
        self.assertEqual(decision(p,TaskContract())['mode'],'DIRECT_EXECUTION')
        self.assertEqual(decision(p,TaskContract(independent_children=2))['mode'],'PARALLEL_SUBTASKS')
        self.assertEqual(decision(p,TaskContract(review_required=True))['mode'],'SEQUENTIAL_SUBTASKS')
        self.assertEqual(decision(p,TaskContract(handoff_required=True))['mode'],'MODEL_ESCALATION')
        self.assertEqual(decision(p,TaskContract(privacy_local_only=True))['mode'],'NO_DELEGATION')
    def test_cloud_goal_feedback_preserves_ids_without_private_description(self):
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        from agent.deepseek import DeepSeekBackend
        from agent.backends import Message
        b=DeepSeekBackend(api_key='fixture')
        s=AgentSession(create_default_registry(self.root),cloud_backend=b,harness_policy=HarnessPolicy(),
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),hybrid_primary='cloud',hybrid_backends={'cloud':b})
        messages=[Message('assistant',None,[call('manage_goal',{'action':'create','description':'PRIVATE_BODY'},'g')]),
            Message('tool',json.dumps({'ok':True,'result':{'id':'goal-1','subgoals':['goal-2'],'status':'pending','description':'PRIVATE_BODY'}}),tool_call_id='g')]
        view=s.hybrid.project_messages(messages);payload=json.loads(view[-1].content)
        self.assertEqual(payload['goal_state'],{'id':'goal-1','subgoals':['goal-2'],'status':'pending'})
        self.assertNotIn('PRIVATE_BODY',json.dumps([m.to_dict() for m in view]));self.assertEqual(s.hybrid.state['grants'],[])
        s.close()
    def test_child_success_records_cannot_certify_parent_owned_mutation(self):
        sessions=[]
        def false_roles(messages):
            s=sessions[0]
            s.subagents.append({'id':'1.1','turn_id':s.turn_id,'status':'completed','read_only':False})
            return answer('child claimed success')
        contract=TaskContract(output_paths=('one.txt',),child_output_groups=(('one.txt',),))
        s=self.session(Backend(write(),answer(None,call('read_file',{'path':'one.txt'},'read')),false_roles),contract=contract);sessions.append(s)
        r=s.run_turn('Independent child must own one.txt')
        self.assertEqual(r.status,'incomplete')
        self.assertIn('child_output_ownership_unproved',[f['reason'] for f in r.completion['file_evidence']['failures']])
    def test_missing_child_role_never_triggers_mutation_retry(self):
        contract=TaskContract(output_paths=('one.txt',),child_output_groups=(('one.txt',),))
        s=self.session(Backend(write(),answer(None,call('read_file',{'path':'one.txt'},'read')),answer('done')),contract=contract)
        r=s.run_turn('Child-owned output required');self.assertEqual(r.status,'incomplete')
        self.assertNotIn('harness_repairs',r.completion)
        self.assertEqual(sum(t['name']=='apply_patch' for t in s.tool_history),1)
    def test_file_contract_without_semantic_verifiers_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'trusted execution'):
            AgentSession(create_default_registry(self.root),backend=Backend(),harness_policy=HarnessPolicy(),
                task_contract=TaskContract(output_paths=('one.txt',)),finalization_policy=FinalizationPolicy())
    def test_single_model_handoff_contract_is_sequential_child_work(self):
        c=TaskContract(output_paths=('one.txt',),child_output_groups=(('one.txt',),))
        self.assertEqual(decision(HarnessPolicy(),c)['mode'],'SEQUENTIAL_SUBTASKS')
    def test_unavailable_backend_selection_is_bounded_not_dispatched_feedback(self):
        from agent.hybrid import HybridPolicy,CloudEgressPolicy
        bad=lambda id:answer(None,call('request_model_switch',{'target':'local','reason':'unavailable stage','task_complexity':'simple','scope':'session'},id))
        b=Backend(bad('a'),bad('b'),answer('never needed'))
        s=AgentSession(create_default_registry(self.root),cloud_backend=b,streaming=False,harness_policy=HarnessPolicy(),
            hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),hybrid_primary='cloud',hybrid_backends={'cloud':b},
            budgets=SessionBudgets(max_steps=8,max_token_units=4000000),stabilization=StabilizationControls(stagnation_limit=0))
        r=s.run_turn('Unavailable model must not be called')
        self.assertEqual(r.status,'incomplete');self.assertEqual(len(s.tool_history),2)
        self.assertEqual(s.tool_history[0]['payload']['result']['stage'],'not_dispatched')
        self.assertFalse(s.tool_history[0]['payload']['result']['action_sent']);self.assertEqual(s._switches,0)
        s.close()


if __name__=='__main__':unittest.main()
