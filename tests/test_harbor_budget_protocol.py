"""Budget implementation over real local HTTP and tokenizer subprocess fixtures."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from scripts.harbor_model_budget import BudgetedLocalBackend, ModelBudgetExceeded
from scripts.harbor_tokenizer_process import TokenizerProcess, tokenizer_fingerprint


class BudgetProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'tokenizer_config.json').write_text('{"fixture": true}')
        self.counter_script = self.root / 'counter.py'
        self.counter_script.write_text('import json, sys\nfor line in sys.stdin:\n json.loads(line)\n print(json.dumps({"input_tokens":7}),flush=True)\n')
        self.backends = []
        self.calls = []
        self.usage = {'prompt_tokens':7, 'completion_tokens':2}
        self.status = 200
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.calls.append(body)
                self.send_response(outer.status)
                if outer.status != 200:
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"fixture failure"}}')
                    return
                if body.get('stream'):
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    frames = [{'id':'fixture', 'model':'fixture', 'choices':[{'index':0,'delta':{'content':'done'},'finish_reason':None}]},
                              {'id':'fixture', 'model':'fixture', 'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
                    if outer.usage is not None:
                        frames.append({'id':'fixture','model':'fixture','choices':[],'usage':outer.usage})
                    for frame in frames:
                        self.wfile.write(('data: ' + json.dumps(frame) + '\n\n').encode())
                    self.wfile.write(b'data: [DONE]\n\n')
                else:
                    value = {'id':'fixture','object':'chat.completion','model':'fixture',
                             'choices':[{'index':0,'message':{'role':'assistant','content':'done'},'finish_reason':'stop'}],
                             'usage':outer.usage}
                    raw = json.dumps(value).encode()
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        for backend in self.backends:
            backend.close_counter()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temporary.cleanup()

    def backend(self, **limits):
        budget = {'tokenizer_path':str(self.root),'tokenizer_python':sys.executable,'max_requests':2,
                  'max_input_tokens':100,'max_output_tokens':8,'max_total_tokens':100,'min_available_bytes':1, **limits}
        backend = BudgetedLocalBackend(model_budget=budget,budget_log=self.root/'budget.jsonl',
            base_url=f'http://127.0.0.1:{self.server.server_port}/v1',model='fixture',effective_context=1024,
            timeout=2,supports_streaming=True,include_stream_usage=True,chat_template_kwargs={'enable_thinking':False})
        backend.counter = TokenizerProcess(sys.executable,self.root,script=self.counter_script,timeout=1)
        self.backends.append(backend)
        return backend

    def records(self):
        return [json.loads(line) for line in (self.root/'budget.jsonl').read_text().splitlines()]

    def test_request_reservation_settlement_and_request_cap(self):
        backend = self.backend(max_requests=1)
        backend.request([{'role':'user','content':'fixture'}])
        self.assertEqual(backend.charged_tokens,9)
        self.assertEqual([row['status'] for row in self.records()],['budget_initialized','admitted','completed'])
        with self.assertRaises(ModelBudgetExceeded):
            backend.request([{'role':'user','content':'must not dispatch'}])
        self.assertEqual(len(self.calls),1)

    def test_mismatched_provider_input_disqualifies_later_requests(self):
        self.usage['prompt_tokens']=8
        backend=self.backend()
        for _ in range(2):
            with self.assertRaises(ModelBudgetExceeded):
                backend.request([{'role':'user','content':'fixture'}])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.records()[-1]['status'],'tokenizer_mismatch')

    def test_output_usage_missing_or_over_limit_is_not_qualified(self):
        for value in (None,-1,True,9):
            with self.subTest(output=value):
                self.usage['completion_tokens']=value
                backend=self.backend()
                with self.assertRaises(ModelBudgetExceeded):
                    backend.request([{'role':'user','content':'fixture'}])
                self.assertEqual(backend.charged_tokens,15)
                self.assertEqual(self.records()[-1]['status'],'invalid_or_missing_output_usage')

    def test_failed_request_reservation_is_retained_and_not_retried(self):
        backend=self.backend()
        self.status=500
        with self.assertRaises(Exception):
            backend.request([{'role':'user','content':'fixture'}])
        self.assertEqual(backend.charged_tokens,15)
        self.status=200
        with self.assertRaises(ModelBudgetExceeded):
            backend.request([{'role':'user','content':'must not dispatch'}])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.records()[-1]['status'],'failed_usage_unknown')

    def test_complete_stream_settles_and_missing_usage_is_rejected(self):
        backend=self.backend()
        self.assertEqual(sum(chunk.kind=='response' for chunk in backend.stream([{'role':'user','content':'fixture'}])),1)
        self.assertIsNone(backend.disqualified)
        self.usage=None
        with self.assertRaises(ModelBudgetExceeded):
            list(backend.stream([{'role':'user','content':'fixture'}]))
        self.assertIsNotNone(backend.disqualified)

    def test_tokenizer_timeout_including_blocked_large_write_is_bounded(self):
        self.counter_script.write_text('import time\ntime.sleep(30)\n')
        counter=TokenizerProcess(sys.executable,self.root,script=self.counter_script,timeout=0.1)
        start=time.monotonic()
        with self.assertRaises(TimeoutError):
            counter.count({'data':'x'*1000000})
        self.assertLess(time.monotonic()-start,4)
        self.assertIsNone(counter.process)

    def test_tokenizer_eof_and_partial_json_are_not_a_successful_zero_count(self):
        for code in ('pass', 'import sys\nsys.stdout.write("{")\nsys.stdout.flush()'):
            self.counter_script.write_text(code)
            counter=TokenizerProcess(sys.executable,self.root,script=self.counter_script,timeout=1)
            with self.assertRaises(RuntimeError):
                counter.count({'fixture':True})
            self.assertIsNone(counter.process)

    def test_tokenizer_template_changes_identity(self):
        before=tokenizer_fingerprint(self.root)
        (self.root/'chat_template.jinja').write_text('fixture-template')
        self.assertNotEqual(tokenizer_fingerprint(self.root),before)


if __name__ == '__main__':
    unittest.main()
