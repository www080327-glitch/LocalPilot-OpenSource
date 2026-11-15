"""One measured model-request budget shared by the two evaluation harnesses."""
from dataclasses import dataclass, asdict
import json
from pathlib import Path

from localpilot_service.backend_contract import ServiceOpenAIBackend
from scripts.harbor_tokenizer_process import TokenizerProcess, tokenizer_fingerprint


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
    tokenizer_timeout: int = 30

    def __post_init__(self):
        for name in ('max_requests', 'max_input_tokens', 'max_output_tokens', 'max_total_tokens', 'min_available_bytes', 'tokenizer_timeout'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError('Model budget limits must be positive integers')
        if not Path(self.tokenizer_path).is_dir() or not Path(self.tokenizer_python).is_file():
            raise ValueError('Use an existing local tokenizer and its reviewed interpreter')


class BudgetedLocalBackend(ServiceOpenAIBackend):
    def __init__(self, *, model_budget, budget_log, record_admission_denials=False, **kwargs):
        if type(record_admission_denials) is not bool:
            raise ValueError('Admission denial recording must be a host boolean')
        self.record_admission_denials = record_admission_denials
        self.limit = ModelBudget(**model_budget)
        super().__init__(**kwargs)
        if not self.is_loopback or self.chat_template_kwargs != {'enable_thinking': False}:
            raise ValueError('Measured evaluation requires local text inference with thinking disabled')
        self.budget_log = Path(budget_log)
        self.requests = self.charged_tokens = 0
        self.denied_attempts = 0
        self.disqualified = None
        self.tokenizer_sha256 = tokenizer_fingerprint(self.limit.tokenizer_path)
        self.counter = TokenizerProcess(self.limit.tokenizer_python, self.limit.tokenizer_path,
            timeout=self.limit.tokenizer_timeout, stderr_path=self.budget_log.with_name('tokenizer-stderr.log'))
        self._record({'status':'budget_initialized', 'limits':asdict(self.limit),
                      'tokenizer_sha256':self.tokenizer_sha256, 'model':self.model,
                      **({'admission_denials':True} if record_admission_denials else {})})

    def _count(self, payload):
        return self.counter.count(payload)

    def _admit(self, messages, tools, thinking, max_tokens):
        import psutil
        if self.disqualified:
            raise ModelBudgetExceeded('Budget qualification was lost: ' + self.disqualified)
        if psutil.virtual_memory().available < self.limit.min_available_bytes:
            self._deny_admission('memory_headroom', 'Host memory headroom is below the registered reserve')
        if self.requests >= self.limit.max_requests:
            self._deny_admission('requests', 'Measured request budget exhausted')
        maximum = min(max_tokens or self.limit.max_output_tokens, self.limit.max_output_tokens)
        payload = self._payload(messages, tools, maximum, thinking=thinking)
        try:
            tokens = self._count(payload)
        except Exception as error:
            if not self.record_admission_denials:
                raise
            self._deny_admission('tokenizer_failure', 'Tokenizer failed before dispatch: ' + type(error).__name__)
        if (tokens > self.limit.max_input_tokens
                or self.charged_tokens + tokens + maximum > self.limit.max_total_tokens):
            self._deny_admission('tokens', 'Measured request/input/output/total model budget exhausted')
        self.requests += 1
        # Reserve the entire unknown response before dispatch. A failed request
        # consumes this allowance; a retry cannot replenish the shared budget.
        self.charged_tokens += tokens + maximum
        self._record({'status':'admitted', 'request':self.requests, 'counted_input_tokens':tokens,
                      'reserved_output_tokens':maximum, 'charged_total_tokens':self.charged_tokens})
        return tokens, maximum

    def _deny_admission(self, reason, message):
        if self.record_admission_denials:
            self.denied_attempts += 1
            self._record({'status':'denied_before_dispatch', 'request':self.requests + 1,
                          'reason':reason, 'charged_total_tokens':self.charged_tokens})
        raise ModelBudgetExceeded(message)

    def _settle(self, tokens, maximum, response):
        usage = response.usage or {}
        actual_input, output = usage.get('prompt_tokens'), usage.get('completion_tokens')
        record = {'request':self.requests, 'counted_input_tokens':tokens,
                  'provider_input_tokens':actual_input, 'output_tokens':output,
                  'limits':asdict(self.limit), 'model':response.model}
        if type(actual_input) is not int or actual_input != tokens:
            self.disqualified = 'tokenizer_mismatch'
            self._record({**record, 'status':'tokenizer_mismatch'})
            raise ModelBudgetExceeded(f'Tokenizer input {tokens} differs from provider {actual_input}; trial is not budget-qualified')
        if type(output) is not int or not 0 <= output <= maximum:
            self.disqualified = 'invalid_or_missing_output_usage'
            self._record({**record, 'status':self.disqualified, 'reserved_output_tokens':maximum})
            raise ModelBudgetExceeded('Provider output usage is missing, invalid, or exceeds the registered output cap')
        self.charged_tokens -= maximum - output
        self._record({**record, 'status':'completed', 'charged_total_tokens':self.charged_tokens})

    def _record(self, value):
        self.budget_log.parent.mkdir(parents=True, exist_ok=True)
        with self.budget_log.open('a') as stream:
            stream.write(json.dumps(value, allow_nan=False) + '\n')

    def request(self, messages, tools=None, thinking=None, max_tokens=None):
        tokens, maximum = self._admit(messages, tools, thinking, max_tokens)
        try:
            response = super().request(messages, tools, thinking, maximum)
        except Exception:
            self.disqualified = 'failed_usage_unknown'
            self._record({'request':self.requests, 'status':'failed_usage_unknown',
                          'charged_total_tokens':self.charged_tokens})
            raise
        self._settle(tokens, maximum, response)
        return response

    def stream(self, messages, tools=None, thinking=None, max_tokens=None):
        tokens, maximum = self._admit(messages, tools, thinking, max_tokens)
        settled = False
        try:
            for chunk in super().stream(messages, tools, thinking, maximum):
                if chunk.kind == 'response':
                    self._settle(tokens, maximum, chunk.response)
                    settled = True
                yield chunk
            if not settled:
                raise ModelBudgetExceeded('Model stream ended without final usage')
        except BaseException:
            if not settled and self.disqualified is None:
                self.disqualified = 'stream_failed_or_incomplete'
                self._record({'request':self.requests, 'status':'stream_failed_or_incomplete',
                              'charged_total_tokens':self.charged_tokens})
            raise

    def close_counter(self):
        self.counter.close()
