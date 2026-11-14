"""Pinned Terminus2 loop with the same measured product model transport.

Only LLM transport/budgeting changes. Its terminal parser, tmux interaction,
task loop and official verifier remain Harbor's implementation.
"""
import asyncio
from pathlib import Path

from harbor.agents.terminus_2.terminus_2 import Terminus2
from harbor.llms.base import BaseLLM, LLMResponse
from harbor.models.metric import UsageInfo

from scripts.harbor_model_budget import BudgetedLocalBackend, ModelBudget


class ProductTransportLLM(BaseLLM):
    def __init__(self, backend):
        self.backend = backend

    def get_model_context_limit(self):
        return self.backend.limit.max_input_tokens

    def get_model_output_limit(self):
        return self.backend.limit.max_output_tokens

    async def call(self, prompt, message_history=None, **kwargs):
        messages = list(message_history or []) + [{'role':'user','content':prompt}]
        response = await asyncio.to_thread(self.backend.request, messages,
            max_tokens=self.backend.limit.max_output_tokens)
        usage = response.usage or {}
        # This is a local endpoint without provider API billing. Device and
        # energy costs remain outside Harbor's API-cost field.
        measured = UsageInfo(prompt_tokens=usage['prompt_tokens'], completion_tokens=usage['completion_tokens'],
            cache_tokens=usage.get('prompt_cache_hit_tokens',0), cost_usd=0)
        return LLMResponse(content=response.message.content or '', model_name=response.model, usage=measured)


class BudgetedTerminusAgent(Terminus2):
    @classmethod
    def preflight(cls, kwargs=None, env=None):
        options = dict(kwargs or {})
        options.pop('endpoint')
        ModelBudget(**options.pop('model_budget'))
        options.pop('model_timeout', None)
        return Terminus2.preflight(options, env)

    def __init__(self, logs_dir, model_name=None, *, endpoint, model_budget, model_timeout=120, **kwargs):
        self.product_backend = BudgetedLocalBackend(model_budget=model_budget,
            budget_log=Path(logs_dir)/'model-budget.jsonl', base_url=endpoint, model=model_name,
            effective_context=model_budget.get('max_input_tokens',32768), timeout=model_timeout,
            supports_streaming=False, chat_template_kwargs={'enable_thinking':False},
            generation_parameters={'temperature':0})
        kwargs.pop('skip_model_parsing', None)
        super().__init__(logs_dir=Path(logs_dir), model_name=model_name,
            skip_model_parsing=True, **kwargs)

    def _init_llm(self, **kwargs):
        return ProductTransportLLM(self.product_backend)

    async def run(self, instruction, environment, context):
        try:
            return await super().run(instruction, environment, context)
        finally:
            self.product_backend.close_counter()
