"""Opt-in qualification against the real loaded local model and tokenizer."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.harbor_model_budget import BudgetedLocalBackend, ModelBudgetExceeded


@unittest.skipUnless(os.environ.get('LOCALPILOT_BUDGET_MODEL'), 'Real local model budget qualification is opt-in')
class MeasuredBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.backends = []
        self.limit = {'tokenizer_path':os.environ['LOCALPILOT_BUDGET_TOKENIZER_PATH'],
            'tokenizer_python':os.environ['LOCALPILOT_BUDGET_TOKENIZER_PYTHON'],
            'max_requests':1, 'max_input_tokens':32768, 'max_output_tokens':16, 'max_total_tokens':50000}

    def tearDown(self):
        for backend in self.backends:
            backend.close_counter()
        self.tmp.cleanup()

    def backend(self):
        backend = BudgetedLocalBackend(model_budget=self.limit, budget_log=self.root/'budget.jsonl',
            base_url=os.environ.get('LOCALPILOT_BUDGET_ENDPOINT','http://127.0.0.1:63420/v1'),
            model=os.environ['LOCALPILOT_BUDGET_MODEL'], effective_context=32768,
            timeout=90, include_stream_usage=True, chat_template_kwargs={'enable_thinking':False})
        self.backends.append(backend)
        return backend

    def test_real_usage_matches_tokenizer_and_second_request_is_blocked(self):
        backend = self.backend()
        backend.request([{'role':'system','content':'Budget fixture.'}, {'role':'user','content':'Reply BUDGET-714.'}],max_tokens=16)
        row=json.loads((self.root/'budget.jsonl').read_text())
        self.assertEqual(row['counted_input_tokens'],row['provider_input_tokens'])
        with self.assertRaises(ModelBudgetExceeded):
            backend.request([{'role':'user','content':'Must not reach inference.'}],max_tokens=16)
        self.assertEqual(backend.requests,1)

    def test_real_stream_usage_is_budgeted(self):
        backend=self.backend()
        chunks=list(backend.stream([{'role':'user','content':'Reply STREAM-714.'}],max_tokens=16))
        self.assertEqual(sum(x.kind=='response' for x in chunks),1)
        self.assertEqual(json.loads((self.root/'budget.jsonl').read_text())['status'],'completed')

    def test_tool_schema_and_tool_history_count_match_provider(self):
        backend=self.backend()
        schema={'type':'function','function':{'name':'shell','description':'Fixture shell',
            'parameters':{'type':'object','properties':{'command':{'type':'string'}},'required':['command']}}}
        messages=[{'role':'user','content':'Inspect the fixture marker.'},
            {'role':'assistant','content':None,'tool_calls':[{'id':'fixture-read','type':'function','function':{'name':'shell','arguments':'{"command":"cat marker.txt"}'}}]},
            {'role':'tool','tool_call_id':'fixture-read','content':'MARKER-714'},
            {'role':'user','content':'Reply with that marker only. Do not call a tool.'}]
        backend.request(messages,[schema],max_tokens=16)
        row=json.loads((self.root/'budget.jsonl').read_text())
        self.assertEqual(row['counted_input_tokens'],row['provider_input_tokens'])

    def test_reference_uses_shared_transport_without_litellm_retry(self):
        from scripts.harbor_reference import BudgetedTerminusAgent, ProductTransportLLM
        options={'endpoint':'http://127.0.0.1:63420/v1','model_budget':self.limit,
                 'max_turns':1,'enable_summarize':False,'record_terminal_session':False}
        BudgetedTerminusAgent.preflight(options)
        agent=BudgetedTerminusAgent(self.root,os.environ['LOCALPILOT_BUDGET_MODEL'],**options)
        self.backends.append(agent.product_backend)
        self.assertIsInstance(agent._llm,ProductTransportLLM)
