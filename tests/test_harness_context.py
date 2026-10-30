"""Request projection controls; never real-model benchmark successes."""
from copy import deepcopy
import json
import unittest
from agent.backends import Message
from agent.context import ContextTooSmall,context_units
from agent.finalization import sha
from agent.harness_context import trim_optional_state,transfer_with_optional_projection


def fixture():
    return {'model_handoff_version':1,'current_goal':'Keep complete task and original requirements',
        'pending_obligations':{'unknown_receipts':1,'unfinished_workers':2,'mutation_intent':False},
        'failed_unknown_actions':[{'receipt_id':'unknown','status':'completed','effect':'unknown','verification':'unknown','path':'protected.json'}],
        'pending_call_ids':['pending'],'resource_budget':{'remaining_admission_units':10000,'child_reserved_units':9000},
        'approval_state':{'pending_kind':'mutation','authority':'host only'},'approved_capabilities':{'execute':False},
        'completed_steps':[{'receipt_id':str(i),'status':'completed','effect':'completed','verification':'not_run','path':'known.json','metadata':'x'*1200} for i in range(8)],
        'verified_evidence':[],'omitted_receipts':0,'receipt_count':9,'ledger_sha256':'canonical-source','parent_handoff':None}


class HarnessContextControls(unittest.TestCase):
    def test_canonical_and_critical_unknown_permission_budget_state_preserved(self):
        original=fixture();before=deepcopy(original);view=trim_optional_state(original)
        self.assertEqual(original,before)
        for k in original:
            if k not in {'completed_steps','verified_evidence','omitted_receipts'}:self.assertEqual(view[k],original[k])
        self.assertEqual(view['context_projection']['source_contract_sha256'],sha(original))
        self.assertEqual(view['omitted_receipts'],1)

    def test_same_context_and_output_limits_with_explicit_loss_index(self):
        original=fixture();messages=[Message('system','Host limits remain authoritative')]
        with self.assertRaises(ContextTooSmall):transfer_with_optional_projection(messages,[],5000,1000,working_state=original)
        view,info=transfer_with_optional_projection(messages,[],5000,1000,working_state=original,enabled=True)
        self.assertLessEqual(context_units(view,[]),4000)
        self.assertGreater(info['optional_completed_context_entries_omitted'],0)
        state=json.loads(view[-1].content.split('\n',1)[1])
        self.assertEqual(state['failed_unknown_actions'],original['failed_unknown_actions'])
        self.assertEqual(state['pending_obligations'],original['pending_obligations'])
        self.assertEqual(len(original['completed_steps']),8)

    def test_critical_overflow_refuses_instead_of_truncating_task(self):
        original=fixture();original['completed_steps']=[];original['current_goal']='critical '*2000
        with self.assertRaises(ContextTooSmall):transfer_with_optional_projection([],[],5000,1000,working_state=original,enabled=True)
        self.assertEqual(len(original['current_goal']),len('critical '*2000))

    def test_unknown_is_never_an_optional_completed_row(self):
        original=fixture();original['completed_steps']=[{**original['failed_unknown_actions'][0],'body':'x'*10000}]
        self.assertIsNone(trim_optional_state(original))
        with self.assertRaises(ContextTooSmall):transfer_with_optional_projection([],[],5000,1000,working_state=original,enabled=True)

    def test_nested_parent_contract_is_only_projected_in_copy(self):
        original=fixture();original['completed_steps']=[];original['parent_handoff']=fixture();before=deepcopy(original)
        view=trim_optional_state(original)
        self.assertEqual(original,before)
        self.assertEqual(view['parent_handoff']['failed_unknown_actions'],before['parent_handoff']['failed_unknown_actions'])
        self.assertEqual(len(view['parent_handoff']['completed_steps']),7)


if __name__=='__main__':unittest.main()
