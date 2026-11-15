"""Qualification is checked against the real transport ledger, not fake scores."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest

from scripts.harbor_budget_audit import audit_budget_log, comparison_configuration
from scripts.harbor_model_budget import ModelBudgetExceeded
from tests import test_harbor_budget_protocol as protocol


class BudgetAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = protocol.BudgetProtocolTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.backend = self.fixture.backend()
        self.trial = self.fixture.root/'trial'/'result.json'
        self.backend.budget_log.parent.mkdir(exist_ok=True)
        self.arm = {'id':'localpilot','agent':{'import_path':'scripts.localpilot_harbor:LocalPilotHarborAgent',
            'model_name':'fixture','kwargs':{'endpoint':self.backend.base_url,
                'model_budget':asdict(self.backend.limit),'chat_template_kwargs':{'enable_thinking':False}}}}
        baseline = deepcopy(self.arm)
        baseline['id']='reference'
        baseline['agent']['import_path']='scripts.harbor_reference:BudgetedTerminusAgent'
        baseline['agent']['kwargs'].pop('chat_template_kwargs')
        self.identity = {'model_name':'fixture','revision':'fixture-only','quantization':'fixture-only',
                         'tokenizer_sha256':self.backend.tokenizer_sha256}
        self.spec = {'purpose':'evaluation','arms':[self.arm,baseline],
                     'comparison':{'candidate':'localpilot','baseline':'reference'},
                     'execution':{'n_concurrent_trials':1},'model_identity':self.identity}

    def audit(self, started=True):
        destination = self.trial.parent/'agent'/'model-budget.jsonl'
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(self.backend.budget_log.read_bytes())
        return audit_budget_log(self.trial,{'agent_execution':{'started_at':'fixture'} if started else None},self.arm,self.identity)

    def test_successful_real_http_usage_reconciles_pre_dispatch_reservation(self):
        self.backend.request([{'role':'user','content':'fixture'}])
        report = self.audit()
        self.assertTrue(report['qualified'],report)
        self.assertEqual((report['requests'],report['input_tokens'],report['output_tokens'],report['charged_total_tokens']),(1,7,2,9))
        self.assertTrue(comparison_configuration(self.spec)['qualified'])

    def test_budget_or_model_or_endpoint_inequality_blocks_paired_claim(self):
        mutations = [lambda a:a.update(model_name='different'),
            lambda a:a['kwargs']['model_budget'].update(max_requests=20),
            lambda a:a['kwargs'].update(endpoint='http://127.0.0.1:12345/v1'),
            lambda a:a.update(override_timeout_sec=12000),
            lambda a:a['kwargs'].update(model_timeout=360)]
        for change in mutations:
            spec = deepcopy(self.spec)
            change(spec['arms'][1]['agent'])
            with self.subTest(change=change):
                self.assertFalse(comparison_configuration(spec)['qualified'])

    def test_missing_model_identity_and_changed_template_are_unqualified(self):
        self.spec.pop('model_identity')
        self.assertFalse(comparison_configuration(self.spec)['qualified'])
        self.identity['tokenizer_sha256']='different'
        self.assertFalse(self.audit()['qualified'])

    def test_missing_provider_usage_or_failure_retains_original_ledger(self):
        self.fixture.usage['completion_tokens']=None
        with self.assertRaises(ModelBudgetExceeded):
            self.backend.request([{'role':'user','content':'fixture'}])
        original=self.backend.budget_log.read_bytes()
        report=self.audit()
        self.assertFalse(report['qualified'])
        self.assertEqual(self.backend.budget_log.read_bytes(),original)
        self.assertIn('invalid_or_missing_output_usage',report['issues'][0])

    def test_tampered_total_or_legacy_settlement_cannot_qualify(self):
        self.backend.request([{'role':'user','content':'fixture'}])
        rows=[json.loads(line) for line in self.backend.budget_log.read_text().splitlines()]
        rows[-1]['charged_total_tokens']=0
        self.backend.budget_log.write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
        self.assertFalse(self.audit()['qualified'])
        self.backend.budget_log.write_text(json.dumps(rows[-1])+'\n')
        report=self.audit()
        self.assertFalse(report['qualified'])
        self.assertIn('legacy',report['issues'][0])

    def test_new_backend_in_same_attempt_does_not_reset_audited_budget(self):
        self.backend.request([{'role':'user','content':'fixture'}])
        second=self.fixture.backend()
        second.request([{'role':'user','content':'fixture'}])
        self.assertFalse(self.audit()['qualified'])

    def test_missing_log_only_counts_zero_before_agent_execution_started(self):
        before=audit_budget_log(self.trial,{'agent_execution':None},self.arm,self.identity)
        after=audit_budget_log(self.trial,{'agent_execution':{'started_at':'fixture'}},self.arm,self.identity)
        self.assertTrue(before['qualified'])
        self.assertEqual(before['requests'],0)
        self.assertFalse(after['qualified'])
        self.assertIsNone(after['requests'])


if __name__=='__main__':
    unittest.main()
