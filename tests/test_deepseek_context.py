"""No model calls: lossless request projection and authority preservation."""
from copy import deepcopy
import json
import unittest

from agent.deepseek_context import project_handoff
from agent.hybrid import sha

class DeepSeekContextTests(unittest.TestCase):
    def contract(self):
        record={'receipt_id':'r1','status':'completed','effect':'completed','verification':'not_run',
                'version':{'path':'a','sha256':'version1'},'coverage':{'kind':'full_file','truncated':False}}
        return {'completed_steps':[record], 'verified_evidence':[deepcopy(record)],
                'failed_unknown_actions':[{'receipt_id':'u1','effect':'unknown'}],
                'pending_obligations':{'unknown_receipts':1,'pending_approval':True},
                'approval_state':{'pending_kind':'tool','authority':'host only'},
                'approved_capabilities':{'write':False},'permission_mode':'approve-all',
                'task_identity':{'generation':3},'revisions':['latest'], 'resource_budget':{'remaining_steps':2},
                'available_tools':['read_file'],'tool_schema_sha256':'old'}

    def test_references_reconstruct_exact_evidence_without_canonical_mutation(self):
        original=self.contract();before=deepcopy(original)
        view=project_handoff(original,[])
        indexed={r['receipt_id']:r for r in view['completed_steps']}
        self.assertEqual([indexed[r] for r in view['verified_evidence_refs']], original['verified_evidence'])
        self.assertNotIn('verified_evidence',view)
        self.assertEqual(original,before)
        for key in ['failed_unknown_actions','pending_obligations','approval_state','approved_capabilities','permission_mode','task_identity','revisions','resource_budget']:
            self.assertEqual(view[key],original[key])

    def test_missing_ambiguous_or_stale_versions_keep_full_record(self):
        for mutation in ['absent','ambiguous','stale']:
            contract=self.contract()
            if mutation=='absent':contract['completed_steps']=[]
            elif mutation=='ambiguous':contract['completed_steps']*=2
            else:contract['completed_steps'][0]['version']['sha256']='version2'
            view=project_handoff(contract,[])
            self.assertEqual(view['verified_evidence'],contract['verified_evidence'])
            self.assertNotIn('verified_evidence_refs',view)

    def test_finalizing_advertises_no_tools_without_changing_authority(self):
        contract=self.contract();view=project_handoff(contract,None)
        self.assertEqual(view['available_tools'],[])
        self.assertEqual(view['tool_schema_sha256'],sha(None))
        self.assertEqual(view['pending_obligations'],contract['pending_obligations'])
        self.assertEqual(contract['available_tools'],['read_file'])

    def test_many_receipts_reduce_bytes_with_all_versions_retained(self):
        contract=self.contract()
        contract['completed_steps']=[{**deepcopy(contract['completed_steps'][0]),'receipt_id':f'r{i}','metadata':'x'*700} for i in range(12)]
        contract['verified_evidence']=deepcopy(contract['completed_steps'])
        view=project_handoff(contract,[])
        self.assertLess(len(json.dumps(view)),len(json.dumps(contract))*.65)
        self.assertEqual(len(view['completed_steps']),12)
        self.assertEqual(len(view['verified_evidence_refs']),12)
