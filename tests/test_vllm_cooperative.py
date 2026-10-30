"""Provider boundary, zero-egress routing, and durable cost limit regressions."""
from concurrent.futures import ThreadPoolExecutor
import tempfile
from pathlib import Path
import unittest

from agent.backends import BackendCapabilities, BackendResponse, Message, ModelInfo, ToolCall
from agent.cooperative import CooperativePolicy, decide
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.local_http import LocalBackendError
from agent.policy import DataPolicy
from agent.registry import create_default_registry
from agent.retry import RetryPolicy
from agent.session import AgentSession, SessionBudgets
from agent.vllm import VLLMBackend
from agent.safety import CapabilityPolicy
from benchmarks.hybrid_accounting import CostLedger, BudgetExceeded


class Scripted:
    capabilities = BackendCapabilities(supports_tool_calling=True)
    def __init__(self, local, responses):
        self.is_local = local
        self.model_info = ModelInfo('local' if local else 'cloud', '35B', 131072)
        self.responses = list(responses)
        self.seen = []
    def health_check(self): return True
    def request(self, messages, **kwargs):
        self.seen.append(messages)
        return self.responses.pop(0)


class CooperativeTests(unittest.TestCase):
    def decision(self, mode='local-first', **updates):
        fields = dict(current='local', local_requests=0, tool_errors=0, stagnation=0,
            context_bytes=1000, local_context=65536, bucket='simple', profile={})
        fields.update(updates)
        return decide(CooperativePolicy(mode=mode), **fields)

    def test_cloud_closed_wins_over_difficulty_and_failure(self):
        for mode in ('local-first', 'balanced', 'cloud-first'):
            self.assertEqual(self.decision(mode, cloud_allowed=False, tool_errors=5, bucket='complex')['target'], 'local')

    def test_unseen_quality_never_claims_calibration(self):
        self.assertEqual(self.decision('balanced')['target'], 'cloud')
        self.assertEqual(self.decision('cloud-first')['target'], 'cloud')
        self.assertEqual(self.decision()['target'], 'local')

    def test_early_exit_and_hysteresis(self):
        self.assertEqual(self.decision(local_requests=2)['reason'], 'local_trial_budget_exhausted')
        self.assertEqual(self.decision(tool_errors=1)['reason'], 'tool_error')
        self.assertEqual(self.decision(escalated=True)['reason'], 'route_hysteresis')
        self.assertEqual(self.decision(bucket='complex')['target'], 'cloud')

    def test_profile_cannot_turn_model_self_confidence_into_quality(self):
        self.assertEqual(self.decision('balanced', profile={'confidence':1})['target'], 'cloud')
        self.assertEqual(self.decision('balanced', profile={'samples':100,'successes':100})['target'], 'local')

    def test_runtime_local_only_never_calls_cloud(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Scripted(True, [BackendResponse(Message('assistant','done'))])
            cloud = Scripted(False, [])
            r = AgentSession(create_default_registry(tmp), local_backend=local, cloud_backend=cloud,
                policy='local-only', streaming=False, runtime_tools=False,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('LOCAL_ONLY')),
                hybrid_backends={'l':local,'c':cloud}, hybrid_primary='l',
                cooperative_policy=CooperativePolicy(mode='local-only'))
            try:
                r.run_turn('answer simply')
                self.assertEqual(len(local.seen),1)
                self.assertEqual(cloud.seen,[])
            finally:r.close()

    def test_step_escalation_preserves_executed_read_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'a.txt').write_text('fact')
            local = Scripted(True, [BackendResponse(Message('assistant',tool_calls=[ToolCall('r1','read_file','{"path":"a.txt"}')]))])
            cloud = Scripted(False, [BackendResponse(Message('assistant','fact'))])
            r = AgentSession(create_default_registry(tmp), local_backend=local, cloud_backend=cloud,
                policy='local-first', streaming=False, runtime_tools=False,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',('a.txt',))),
                hybrid_backends={'l':local,'c':cloud}, hybrid_primary='l',
                cooperative_policy=CooperativePolicy(mode='local-first',max_local_requests=1))
            try:
                result=r.run_turn('Read a.txt')
                self.assertEqual(len(local.seen),1)
                self.assertEqual(len(cloud.seen),1)
                self.assertEqual(len(r.tool_history),1)
                self.assertTrue(any(m.role=='tool' and m.tool_call_id=='r1' for m in cloud.seen[0]))
                self.assertIn('completed_steps',r.hybrid.state['handoffs'][0]['contract'])
            finally:r.close()

    def test_cloud_handoff_reuses_completed_mutation_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            args='{"changes":[{"path":"once.txt","operation":"create","content":"proof"}]}'
            local=Scripted(True,[BackendResponse(Message('assistant',tool_calls=[ToolCall('first','apply_patch',args)]))])
            cloud=Scripted(False,[BackendResponse(Message('assistant',tool_calls=[ToolCall('fresh-id','apply_patch',args)])),BackendResponse(Message('assistant','done'))])
            registry=create_default_registry(tmp,permission_mode='full-permission',capabilities=CapabilityPolicy(read=True,write=True))
            r=AgentSession(registry,local_backend=local,cloud_backend=cloud,policy='local-first',streaming=False,runtime_tools=False,
                hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED',('once.txt',))),
                hybrid_backends={'l':local,'c':cloud},hybrid_primary='l',cooperative_policy=CooperativePolicy(mode='local-first',max_local_requests=1))
            try:
                r.run_turn('Create once.txt containing proof')
                self.assertEqual(Path(tmp,'once.txt').read_text(),'proof')
                self.assertTrue(any(t.get('receipt_reused') for t in r.tool_history))
            finally:r.close()

    def test_calibration_rejects_a_different_model_or_evaluation_split(self):
        for profile in ({'split':'evaluation','buckets':{}}, {'split':'development','buckets':{'simple':{'samples':100,'successes':100}}}):
            with tempfile.TemporaryDirectory() as tmp:
                local=Scripted(True,[]);cloud=Scripted(False,[])
                with self.assertRaises(ValueError):
                    AgentSession(create_default_registry(tmp),local_backend=local,cloud_backend=cloud,policy='balanced',
                        hybrid_policy=HybridPolicy(CloudEgressPolicy('CLOUD_ALLOWED')),
                        hybrid_backends={'l':local,'c':cloud},hybrid_primary='l',
                        cooperative_policy=CooperativePolicy(),cooperative_profiles=profile)


class VLLMTests(unittest.TestCase):
    def test_token_observation_is_not_mutated_by_a_later_raw_cancel_stream(self):
        from benchmarks.vllm_backend_qualification import TimedBackend
        from tests.test_local_http_backend import MockServer,sse
        server=MockServer()
        try:
            b=TimedBackend(base_url=server.base_url,model='mock-local',token_timing=True)
            server.add(sse({'choices':[{'index':0,'delta':{'content':'ok'},'token_ids':[7,8,9],'finish_reason':'stop'}]},
                           {'choices':[],'usage':{'prompt_tokens':3,'completion_tokens':3}}),content_type='text/event-stream')
            observed=b.measured([Message('user','test')])
            server.add(sse({'choices':[{'index':0,'delta':{'content':'1'},'token_ids':[16],'finish_reason':'stop'}]}),content_type='text/event-stream')
            stream=b.stream([Message('user','count')],max_tokens=4);next(stream);stream.close()
            self.assertEqual(observed['token_ids'],[7,8,9])
        finally:server.close()

    def test_service_catalog_does_not_advertise_an_unconfigured_tool_parser(self):
        import json,os
        from localpilot_service.deployment import build
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'workspace').mkdir()
            cfg={'schema_version':1,'port':0,'data_dir':str(root/'private'),
                'clients':[{'subject':'test','token_env':'LP_VLLM_TEST_TOKEN','routes':{'local':'local'}}],
                'routes':{'local':{'workspace':str(root/'workspace'),'backend':{'kind':'vllm','base_url':'http://127.0.0.1:9/v1','model':'model','timeout':.1},'cloud_egress':'LOCAL_ONLY'}}}
            p=root/'service.json';p.write_text(json.dumps(cfg));p.chmod(0o600)
            with patch.dict(os.environ,{'LP_VLLM_TEST_TOKEN':'test-token-012345678901234567890123456789'}):
                server=build(p)
                try:self.assertEqual(server.catalog['local']['capabilities'],['streaming'])
                finally:server.service.shutdown();server.server_close();server.access.close()

    def test_provider_contract_discovers_and_closes_only_its_stream(self):
        from tests.test_local_http_backend import MockServer, sse
        server=MockServer()
        try:
            b=VLLMBackend(base_url=server.base_url,model='mock-local',supports_tool_calling=True)
            self.assertEqual(b.discover()[0]['id'],'mock-local')
            server.add(sse({'model':'mock-local','choices':[{'index':0,'delta':{'content':'hi'},'finish_reason':'stop'}]},
                           {'choices':[],'usage':{'prompt_tokens':3,'completion_tokens':1}}),content_type='text/event-stream')
            chunks=list(b.stream([{'role':'user','content':'hello'}],max_tokens=8))
            self.assertEqual(chunks[-1].response.message.content,'hi')
            self.assertEqual(chunks[-1].response.usage['completion_tokens'],1)
            self.assertEqual(len(b._responses),0)
        finally:server.close()

    def test_remote_vllm_remains_cloud_in_five_mode_selection(self):
        from localpilot_service.routing import select_route
        catalog={'remote':{'adapter':'remote-vllm','cloud_egress':'CLOUD_ALLOWED','model':'model'}}
        _,decision=select_route({'r':'remote'},catalog,routing_preferences={'version':'1.0','source':'cloud_only','objective':'quality'})
        self.assertEqual(decision['selected'],'r')

    def test_capability_and_context_fail_before_http(self):
        b=VLLMBackend(base_url='http://127.0.0.1:9/v1',model='frozen',effective_context=1000)
        with self.assertRaises(ValueError):b.request([Message('user','hi')],tools=[{}],max_tokens=2)
        with self.assertRaises(LocalBackendError):b.request([Message('user','x'*2000)],max_tokens=2)
        DataPolicy(local_only=True).check_backend(b)
        with self.assertRaises(ValueError):VLLMBackend(base_url='http://192.0.2.1/v1',model='frozen',allow_remote=True)
        remote=VLLMBackend(base_url='https://192.0.2.1/v1',model='frozen',allow_remote=True,api_key='example')
        with self.assertRaises(PermissionError):DataPolicy(local_only=True).check_backend(remote)


class LedgerTests(unittest.TestCase):
    def test_concurrent_reservations_and_restart_cannot_exceed_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp,'cost.sqlite3')
            ledger=CostLedger(path,limit_cny=.1)
            def reserve(_):
                try:return ledger.reserve(prompt_upper=10000,output_upper=1000)
                except BudgetExceeded:return None
            with ThreadPoolExecutor(max_workers=8) as executor:
                ids=[v for v in executor.map(reserve,range(16)) if v]
            self.assertEqual(len(ids),2) # .042 CNY each, held until settled.
            second=CostLedger(path,limit_cny=.1)
            self.assertLessEqual(second.snapshot()['budget_charged_cny'],.1)
            with self.assertRaises(BudgetExceeded):second.reserve(prompt_upper=10000,output_upper=1000)
            second.settle(ids[0],None,elapsed_seconds=1,error='timeout')
            snapshot=second.snapshot()
            # executor.map preserves input order; concurrent SQL insertion
            # order is intentionally unspecified. Check the settled receipt.
            by_id={row['request_id']:row for row in snapshot['calls']}
            self.assertEqual(by_id[ids[0]]['status'],'USAGE_UNKNOWN')
            self.assertEqual(by_id[ids[1]]['status'],'RESERVED')
            self.assertAlmostEqual(snapshot['budget_charged_cny'],.084)
            self.assertIsNone(snapshot['standard_api_cost_usd'])

    def test_only_official_cache_usage_discounts_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=CostLedger(Path(tmp,'cost.sqlite3'))
            identity=ledger.reserve(prompt_upper=1000,output_upper=100)
            ledger.settle(identity,{'prompt_tokens':1000,'completion_tokens':100,'prompt_cache_hit_tokens':500},elapsed_seconds=1)
            call=ledger.snapshot()['calls'][0]
            self.assertAlmostEqual(call['cost_usd_standard'],.000273)


if __name__=='__main__':unittest.main()
