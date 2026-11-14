"""Independent completion gates protect against inflated benchmark headlines."""
from copy import deepcopy
import unittest
from scripts.aic_summarize import assess_strict


class StrictScoreTests(unittest.TestCase):
    def row(self,**values):
        return {'arm':'B','status':'generated','turn_statuses':['completed']*3,'checker':{'valid':True},'strict_success':True,**values}
    def test_checker_success_with_final_transport_error_is_a_strict_failure(self):
        raw=self.row(turn_statuses=['completed','completed','error']);original=deepcopy(raw)
        result=assess_strict(raw)
        self.assertTrue(result['state_only_checker_pass']);self.assertFalse(result['strict_success'])
        self.assertTrue(result['driver_completion_misclassification']);self.assertEqual(raw,original)
    def test_all_turns_and_the_checker_must_both_pass(self):
        self.assertTrue(assess_strict(self.row())['strict_success'])
        self.assertFalse(assess_strict(self.row(checker={'valid':False}))['strict_success'])
        self.assertFalse(assess_strict(self.row(status='BLOCKED_TIME_LIMIT'))['strict_success'])
        self.assertFalse(assess_strict(self.row(turn_statuses=[]))['strict_success'])
    def test_native_exit_codes_are_typed_and_must_all_be_zero(self):
        self.assertTrue(assess_strict(self.row(arm='A',turn_statuses=[0,0]))['strict_success'])
        for states in [[0,1],[False],[0.0],['completed']]:
            self.assertFalse(assess_strict(self.row(arm='G',turn_statuses=states))['strict_success'])


if __name__=='__main__':unittest.main()
