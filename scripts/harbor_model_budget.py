"""One measured model-request budget shared by the two evaluation harnesses."""
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import subprocess

from localpilot_service.backend_contract import ServiceOpenAIBackend


class ModelBudgetExceeded(RuntimeError):
    retryable = False


@dataclass(frozen=True)
class ModelBudget:
    tokenizer_path: str
    tokenizer_python: str
    max_requests: int = 24
    max_input_tokens: int = 32768
    max_output_tokens: int = 1024
    max_total_tokens: int = 500000
    min_available_bytes: int = 8 * 1024**3

    def __post_init__(self):
        for name in ('max_requests', 'max_input_tokens', 'max_output_tokens', 'max_total_tokens', 'min_available_bytes'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError('Model budget limits must be positive integers')
        if not Path(self.tokenizer_path).is_dir() or not Path(self.tokenizer_python).is_file():
            raise ValueError('Use an existing local tokenizer and its reviewed interpreter')


class BudgetedLocalBackend(ServiceOpenAIBackend):
    def __init__(self, *, model_budget, budget_log, **kwargs):
        self.limit = ModelBudget(**model_budget)
        super().__init__(**kwargs)
        if not self.is_loopback or self.chat_template_kwargs != {'enable_thinking': False}:
            raise ValueError('Measured evaluation requires local text inference with thinking disabled')
        self.budget_log = Path(budget_log)
        self.requests = self.charged_tokens = 0
        self.counter = None

    def _count(self, payload):
        if self.counter is None:
            code = Path(__file__).with_name('harbor_token_counter.py')
            self.counter = subprocess.Popen([self.limit.tokenizer_python, str(code), self.limit.tokenizer_path],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                env={**{k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','TMPDIR'}}, 'HF_HUB_OFFLINE':'1', 'TRANSFORMERS_OFFLINE':'1',
                     'TOKENIZERS_PARALLELISM':'false'})
        self.counter.stdin.write(json.dumps(payload) + '\n')
        self.counter.stdin.flush()
        row = json.loads(self.counter.stdout.readline())
        if 'error' in row:
            raise ValueError('Tokenizer refused request: ' + row['error'])
        return row['input_tokens']

    def _admit(self, messages, tools, thinking, max_tokens):
        import psutil
        if psutil.virtual_memory().available < self.limit.min_available_bytes:
            raise ModelBudgetExceeded('Host memory headroom is below the registered reserve')
        maximum = min(max_tokens or self.limit.max_output_tokens, self.limit.max_output_tokens)
        payload = self._payload(messages, tools, maximum, thinking=thinking)
        tokens = self._count(payload)
        if (self.requests >= self.limit.max_requests or tokens > self.limit.max_input_tokens
                or self.charged_tokens + tokens + maximum > self.limit.max_total_tokens):
            raise ModelBudgetExceeded('Measured request/input/output/total model budget exhausted')
        self.requests += 1
        # Reserve the entire unknown response before dispatch. A failed request
        # consumes this allowance; a retry cannot replenish the shared budget.
        self.charged_tokens += tokens + maximum
        return tokens, maximum

    def _settle(self, tokens, maximum, response):
        usage = response.usage or {}
        actual_input, output = usage.get('prompt_tokens'), usage.get('completion_tokens')
        record = {'request':self.requests, 'counted_input_tokens':tokens,
                  'provider_input_tokens':actual_input, 'output_tokens':output,
                  'limits':asdict(self.limit), 'model':response.model}
        if actual_input != tokens:
            self._record({**record, 'status':'tokenizer_mismatch'})
            raise ModelBudgetExceeded(f'Tokenizer input {tokens} differs from provider {actual_input}; trial is not budget-qualified')
        if output is not None:
            self.charged_tokens -= maximum - output
        self._record({**record, 'status':'completed', 'charged_total_tokens':self.charged_tokens})

    def _record(self, value):
        self.budget_log.parent.mkdir(parents=True, exist_ok=True)
        with self.budget_log.open('a') as stream:
            stream.write(json.dumps(value) + '\n')

    def request(self, messages, tools=None, thinking=None, max_tokens=None):
        tokens, maximum = self._admit(messages, tools, thinking, max_tokens)
        try:
            response = super().request(messages, tools, thinking, maximum)
        except Exception:
            self._record({'request':self.requests, 'status':'failed_usage_unknown',
                          'charged_total_tokens':self.charged_tokens})
            raise
        self._settle(tokens, maximum, response)
        return response

    def stream(self, messages, tools=None, thinking=None, max_tokens=None):
        tokens, maximum = self._admit(messages, tools, thinking, max_tokens)
        try:
            for chunk in super().stream(messages, tools, thinking, maximum):
                if chunk.kind == 'response':
                    self._settle(tokens, maximum, chunk.response)
                yield chunk
        except Exception:
            self._record({'request':self.requests, 'status':'stream_failed_or_incomplete',
                          'charged_total_tokens':self.charged_tokens})
            raise

    def close_counter(self):
        if self.counter is not None:
            self.counter.stdin.close()
            try:
                self.counter.wait(10)
            except subprocess.TimeoutExpired:
                self.counter.terminate()
                self.counter.wait(10)
            self.counter.stdout.close()
            self.counter = None
