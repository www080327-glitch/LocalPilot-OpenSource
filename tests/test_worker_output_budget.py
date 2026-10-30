"""Host-configured Child output bounds; no real model inference."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from agent.backends import ToolCall
from agent.registry import create_default_registry
from agent.session import AgentSession,SessionBudgets
from tests.test_worker_tiering import ScriptBackend,reply


class WorkerOutputBudgetControls(unittest.TestCase):
    def exercise(self,parent_ceiling,child_ceiling):
        class Capture(ScriptBackend):
            def request(self,messages,**kwargs):
                self.request_ceiling=kwargs['max_tokens']
                return super().request(messages,**kwargs)
        with tempfile.TemporaryDirectory() as d:
            call=ToolCall('delegate-output-bound','delegate',json.dumps({'task':'Return a brief finding.','backend_preference':'cloud','tier':'LIGHT'}))
            parent=ScriptBackend(reply(tool=call),reply('integrated'));child=Capture(reply('finding'))
            session=AgentSession(create_default_registry(Path(d)),cloud_backend=parent,cloud_worker_backends={'LIGHT':child,'STRONG':child},
                budgets=SessionBudgets(max_token_units=4000000,max_output_tokens=parent_ceiling,max_worker_output_tokens=child_ceiling,max_worker_token_units=300000))
            result=session.run_turn('Delegate the finding.')
            self.assertEqual(result.status,'approval_required');self.assertEqual(session.approve().text,'integrated')
            admitted=next(iter(session._children.values())).budgets.max_output_tokens
            self.assertEqual(child.request_ceiling,admitted);session.close()
            return admitted

    def test_configured_child_ceiling_reaches_model_request(self):self.assertEqual(self.exercise(2048,1024),1024)
    def test_child_cannot_exceed_parent_output_ceiling(self):self.assertEqual(self.exercise(768,1024),768)
    def test_default_and_old_checkpoint_budget_stay_512(self):
        data=asdict(SessionBudgets());data.pop('max_worker_output_tokens')
        self.assertEqual(SessionBudgets(**data).max_worker_output_tokens,512)
    def test_zero_or_model_boolean_cannot_define_output_budget(self):
        for value in [0,-1,True]:
            with self.assertRaises(ValueError):SessionBudgets(max_worker_output_tokens=value)


if __name__=='__main__':unittest.main()
