"""Engineering controls. Synthetic responses never count as model evidence."""
from copy import deepcopy
from dataclasses import replace
import json,tempfile,unittest
from pathlib import Path
from agent.adaptive import AdaptivePolicy,TaskTraits,rank,wilson
from agent.backends import Message
from agent.hybrid import HybridPolicy,CloudEgressPolicy,CloudEgressDenied
from agent.persistence import snapshot_runtime,restore_runtime,PersistenceError,backend_identity
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession,SessionBudgets
from agent.stabilization import StabilizationControls
from tests.test_hybrid_runtime import Local
from tests.test_runtime_api import Backend,answer,call


def candidates(n=2):
    return [{'id':k,'kind':k,'available':True,'tool_calling':True,'context_units':65536,'samples':n,'successes':n,
             'estimated_task_cost_usd':0 if k=='local' else .004,'latency_seconds':40 if k=='local' else 12,'handoff_seconds':5}
            for k in ('local','cloud')]


class RankingTests(unittest.TestCase):
    def route(self,cs=None,traits=None,policy=None,**kw):
        return rank(traits or TaskTraits(),cs or candidates(),policy or AdaptivePolicy(),current='cloud',**kw)
    def test_default_is_shadow_and_uncertainty_does_not_become_quality(self):
        r=self.route();self.assertEqual(r['selected'],'local');self.assertEqual(r['quality_superiority'],'UNKNOWN')
        self.assertEqual(AdaptivePolicy().mode,'shadow');self.assertGreater(wilson(2,2)[1]-wilson(2,2)[0],.5)
    def test_single_eligible_backend_does_not_claim_comparative_quality(self):
        self.assertEqual(self.route(local_only=True)['quality_superiority'], 'UNKNOWN')
    def test_no_measurements_retains_fixed_route(self):self.assertEqual(self.route(candidates(0))['selected'],'cloud')
    def test_privacy_precedes_high_cloud_success(self):
        cs=candidates(100);cs[0]['successes']=0
        r=self.route(cs,local_only=True);self.assertEqual(r['selected'],'local');self.assertIn('privacy_or_cloud_egress',r['candidates'][1]['rejected'])
    def test_lock_cannot_override_privacy(self):
        r=self.route(policy=AdaptivePolicy(model_lock='cloud'),local_only=True);self.assertIsNone(r['selected'])
    def test_capability_context_availability_rejections_are_recorded(self):
        cs=candidates();cs[0].update(available=False,tool_calling=False,context_units=20)
        r=self.route(cs);self.assertEqual(r['selected'],'cloud');self.assertEqual(set(r['candidates'][0]['rejected']),{'unavailable','tool_capability','context_window'})
    def test_observed_zero_delivery_does_not_beat_qualified_model_on_zero_api_cost(self):
        cs=candidates();cs[0]['successes']=0;r=self.route(cs)
        self.assertEqual(r['selected'],'cloud');self.assertEqual(r['quality_superiority'],'UNKNOWN')
        self.assertIn('no_verified_delivery_in_training_under_current_configuration',r['candidates'][0]['rejected'])
    def test_role_choice_does_not_inherit_other_models_quality_badge(self):
        cs=candidates(100);cs[0]['successes']=100;cs[1]['successes']=5
        r=self.route(cs,traits=TaskTraits('bugfix',3,review_required=True))
        self.assertEqual(r['selected'],'cloud');self.assertEqual(r['quality_superiority'],'UNKNOWN')
    def test_cost_unknown_or_exhausted_is_rejected(self):
        cs=candidates();cs[1]['estimated_task_cost_usd']=None;r=self.route(cs,remaining_cloud_usd=0)
        self.assertIn('cloud_cost_budget_or_unknown_estimate',r['candidates'][1]['rejected'])
    def test_deadline_is_estimate_and_may_favor_cloud(self):self.assertEqual(self.route(traits=TaskTraits(deadline_seconds=20))['selected'],'cloud')
    def test_cloud_latency_choice_does_not_force_unnecessary_hybrid(self):
        r=self.route(traits=TaskTraits('long',3,deadline_seconds=25))
        self.assertEqual(r['selected'],'cloud');self.assertEqual(r['mode'],'CLOUD')
        self.assertEqual(r['strategy'],'single-model')
    def test_explicit_planning_collaboration_is_supported(self):
        r=self.route(traits=TaskTraits('planning',3,independent_children=1,deadline_seconds=25))
        self.assertEqual(r['strategy'],'cloud-planning');self.assertEqual(r['mode'],'HYBRID')
    def test_separated_intervals_can_choose_measured_quality(self):
        cs=candidates(100);cs[0]['successes']=0;r=self.route(cs)
        self.assertEqual(r['selected'],'cloud');self.assertEqual(r['quality_superiority'],'SUPPORTED_SCOPED')
    def test_review_requires_two_eligible_backends(self):
        r=self.route(traits=TaskTraits('bugfix',3,review_required=True));self.assertEqual(r['strategy'],'cloud-review')
        r=self.route(traits=TaskTraits('bugfix',3,review_required=True),local_only=True);self.assertNotEqual(r['mode'],'HYBRID')
    def test_handoff_limit_preserves_current(self):self.assertEqual(self.route(switches=1)['selected'],'cloud')
    def test_invalid_policy_fails_closed(self):
        for kw in ({'max_cloud_cost_usd':float('nan')},{'max_model_switches':True},{'allowed_categories':('secret',)},{'mode':'magic'}):
            with self.assertRaises(ValueError):AdaptivePolicy(**kw)


class RuntimeControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.instances=[]
        self.local=Local(answer('local final'));self.cloud=Backend(answer('cloud final'))
    def tearDown(self):
        for r in self.instances:
            if not r._drive_lock.locked():r.close()
        self.tmp.cleanup()
    def factory(self,policy=None,primary='cloud',egress='CLOUD_ALLOWED',permission='full-permission',traits=None):
        ps={'version':1,'models':{k:{'identity':backend_identity(b),'available':True,'categories':{'file':{'samples':2,'successes':2,'median_e2e_seconds':10,'median_cloud_cost_usd':.004}}}
                                   for k,b in [('local',self.local),('cloud',self.cloud)]}}
        r=AgentSession(create_default_registry(self.root,permission_mode=permission),local_backend=self.local,cloud_backend=self.cloud,policy='balanced',streaming=False,
            hybrid_policy=HybridPolicy(CloudEgressPolicy(egress)),hybrid_backends={'local':self.local,'cloud':self.cloud},hybrid_primary=primary,
            adaptive_policy=policy or AdaptivePolicy(),capability_profiles=ps,task_traits=traits or TaskTraits(),
            retry_policy=RetryPolicy(max_attempts=1),stabilization=StabilizationControls(False,True,'off',0),
            budgets=SessionBudgets(max_token_units=8000000,max_primary_switches_per_turn=3))
        self.instances.append(r);return r
    def auto(self,**kw):return AdaptivePolicy(mode='automatic',allowed_categories=('file',),**kw)
    def test_shadow_leaves_real_execution_on_fixed_backend(self):
        r=self.factory();v=r.run_turn('work');self.assertEqual(v.text,'cloud final');self.assertFalse(r.adaptive.state['decisions'][0]['applied'])
        self.assertEqual(v.runtime_metrics['adaptive']['mode'],'shadow');self.assertFalse(v.runtime_metrics['adaptive']['decisions'][0]['applied'])
    def test_allowed_auto_selects_local_before_first_request(self):
        r=self.factory(self.auto());v=r.run_turn('work');self.assertEqual(v.text,'local final');self.assertEqual(r._switches,0)
    def test_out_of_scope_keeps_fixed_route(self):
        r=self.factory(self.auto(),traits=TaskTraits('planning'));self.assertEqual(r.run_turn('work').text,'cloud final')
    def test_json_roundtrip_preserves_model_identity_and_measured_ranking(self):
        r=self.factory();r.adaptive.profiles=json.loads(json.dumps(r.adaptive.profiles))
        d=r.adaptive.decide();self.assertEqual(d['selected'],'local')
        self.assertTrue(all(c['identity_matches_measurement'] for c in d['candidates']))
        self.assertEqual(d['candidates'][0]['samples'],2)
    def test_measurements_do_not_transfer_across_changed_identity(self):
        r=self.factory();r.adaptive.profiles['models']['local']['identity']['model']['name']='different'
        d=r.adaptive.decide();self.assertEqual(d['selected'],'cloud');self.assertEqual(d['candidates'][0]['samples'],0)
    def test_cloud_cost_ceiling_blocks_before_provider_dispatch(self):
        r=self.factory(self.auto(model_lock='cloud',max_cloud_cost_usd=.00001))
        with self.assertRaises(CloudEgressDenied):r.run_turn('work')
        self.assertEqual(len(self.cloud.requests),0)
    def test_unknown_usage_reservation_persists_and_cannot_refund(self):
        r=self.factory(self.auto(model_lock='cloud'));r.run_turn('work');spent=r.adaptive.spent();self.assertGreater(spent,0)
        data=snapshot_runtime(r);new=self.factory(self.auto(model_lock='cloud'));restore_runtime(new,data)
        self.assertEqual(new.adaptive.spent(),spent)
    def test_profile_drift_refuses_restore(self):
        r=self.factory();r.run_turn('work');data=snapshot_runtime(r);new=self.factory();new.adaptive.profiles['limits']='changed'
        with self.assertRaises(PersistenceError):restore_runtime(new,data)
    def test_output_contract_survives_finalization_and_is_bound_on_restore(self):
        r=self.factory();r.delivery_instruction='ONLY JSON with paths; no prose'
        r._finalizing=True;r._refresh_prompt()
        self.assertIn('HOST DELIVERY FORMAT CONTRACT',r.messages[0].content)
        data=snapshot_runtime(r);new=self.factory()
        with self.assertRaises(PersistenceError):restore_runtime(new,data)
        new.delivery_instruction=r.delivery_instruction;restore_runtime(new,data)

    def test_missing_adaptive_config_does_not_downgrade_restore(self):
        r=self.factory();data=snapshot_runtime(r);data.pop('adaptive')
        with self.assertRaises(PersistenceError):restore_runtime(r,data)
    def test_explicit_lock_prevents_host_switch(self):
        r=self.factory(self.auto(model_lock='local'),primary='local');r.run_turn('work')
        with self.assertRaises(CloudEgressDenied):r.hybrid.switch('cloud','switch')
    def test_cloud_egress_approval_still_required(self):
        r=self.factory(self.auto(model_lock='cloud'),egress='REQUIRES_APPROVAL');v=r.run_turn('work')
        self.assertEqual(v.status,'approval_required');self.assertEqual(len(self.cloud.requests),0);self.assertEqual(r.pending_approval['kind'],'cloud_egress')
    def test_mutation_approval_still_required(self):
        self.local=Local(answer(None,call('apply_patch',{'changes':[{'operation':'create','path':'out','content':'x'}]},'write')))
        r=self.factory(self.auto(),permission='approve-mutations');v=r.run_turn('work')
        self.assertEqual(v.status,'approval_required');self.assertFalse((self.root/'out').exists())
    def test_historical_child_switches_do_not_spend_new_turn_budget(self):
        r=self.factory(self.auto(),primary='local');old=self.factory(self.auto(),primary='local')
        old._switches=1;r.turn_id=2;r._children['1.1']=old;r.subagents=[{'id':'1.1','turn_id':1}]
        r.adaptive.check_switch('cloud')
        r._children.clear();r.subagents.clear()

    def test_explicit_child_id_cannot_override_host_model_lock(self):
        r=self.factory(self.auto(model_lock='local'),primary='local')
        d=r.adaptive.decide('child','spawn',current='cloud',locked='cloud')
        self.assertIsNone(d['selected']);self.assertEqual(d['reason'],'proposal_conflicts_with_host_model_lock')

    def test_child_route_is_frozen_for_approval_and_explicit_id(self):
        self.local=Local(answer(None,call('delegate',{'task':'bounded','backend_preference':'cloud','backend_id':'cloud','read_only':True},'spawn')))
        r=self.factory(self.auto(),primary='local');v=r.run_turn('work');self.assertEqual(v.status,'approval_required')
        d=r.adaptive.state['decisions'][-1];self.assertEqual(d['selected'],'cloud')
        r.adaptive.profiles['models']['cloud']['available']=False
        self.assertIs(r.adaptive.decide('child','spawn',current='cloud'),d)


if __name__=='__main__':unittest.main()
