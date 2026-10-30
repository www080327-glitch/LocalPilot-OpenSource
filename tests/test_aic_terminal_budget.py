"""A terminal scenario error must not spend requests on later user turns."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchmarks.bfcl_hybrid import lp_run
from benchmarks.hybrid_accounting import CostLedger
from tests.test_runtime_api import Backend,answer


class TerminalScenarioTests(unittest.TestCase):
    def run_case(self,states):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);runtime=SimpleNamespace(calls=0,closed=False,
                events=SimpleNamespace(events=[]),hybrid=SimpleNamespace(summary=lambda:{},state={'attempts':[],'cooperative':{}}))
            def turn(text):
                state=states[runtime.calls];runtime.calls+=1;return SimpleNamespace(status=state)
            runtime.run_turn=turn
            runtime.request_cancel=lambda *args:None
            runtime.close=lambda:setattr(runtime,'closed',True)
            environment=SimpleNamespace(schemas=[],names=set(),turn=0)
            entry={'id':'transport-control','question':[[{'content':'one'}],[{'content':'two'}],[{'content':'three'}]]}
            with patch('benchmarks.bfcl_hybrid.AgentSession',return_value=runtime):
                row=lp_run(entry,environment,'cloud-only','none',Backend(answer('unused')),None,CostLedger(root/'ledger.sqlite3'),root)
            return row,runtime
    def test_first_terminal_error_stops_without_spending_later_turns(self):
        row,runtime=self.run_case(['error','completed','completed'])
        self.assertEqual(runtime.calls,1);self.assertTrue(runtime.closed)
        self.assertEqual(row['status'],'FAIL_AGENT_TERMINAL')
    def test_incomplete_second_turn_does_not_dispatch_third(self):
        row,runtime=self.run_case(['completed','incomplete','completed'])
        self.assertEqual(runtime.calls,2);self.assertEqual(row['turn_statuses'],['completed','incomplete'])
    def test_three_completed_turns_remain_valid_generation(self):
        row,runtime=self.run_case(['completed']*3)
        self.assertEqual(runtime.calls,3);self.assertEqual(row['status'],'generated')


if __name__=='__main__':unittest.main()
