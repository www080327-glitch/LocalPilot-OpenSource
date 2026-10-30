"""Host generation options on existing Chat Completions adapters, without fallback."""
import math
from agent.deepseek import DeepSeekBackend
from agent.deepseek_optimized import DeepSeekOptimizedBackend
from agent.deepseek_native import DeepSeekNativeBackend
from agent.local_http import LocalHTTPBackend
from agent.omlx import OMLXBackend


def generation_options(value):
    if not isinstance(value, dict) or set(value) - {"temperature", "top_p", "seed", "presence_penalty", "frequency_penalty", "stop"}:
        raise ValueError("Unsupported generation parameter")
    limits = {"temperature": (0, 2), "top_p": (0, 1), "presence_penalty": (-2, 2), "frequency_penalty": (-2, 2)}
    for name, (low, high) in limits.items():
        if name in value and (type(value[name]) not in {int, float} or not math.isfinite(value[name]) or not low <= value[name] <= high):
            raise ValueError("Invalid generation parameter: " + name)
    if "seed" in value and type(value["seed"]) is not int:
        raise ValueError("seed must be an integer")
    if "stop" in value and not (isinstance(value["stop"], str) or isinstance(value["stop"], list) and all(isinstance(s, str) for s in value["stop"])):
        raise ValueError("stop must be text or a list of text")
    return dict(value)


class HostGenerationMixin:
    def __init__(self, *args, generation_parameters=None, **kwargs):
        self.generation_parameters = generation_options(generation_parameters or {})
        super().__init__(*args, **kwargs)
        self.service_contract = {"generation_parameters": dict(self.generation_parameters), "timeout": self.timeout}

    def _payload(self, *args, **kwargs):
        payload = super()._payload(*args, **kwargs)
        payload.update(self.generation_parameters)
        return payload


class ServiceDeepSeekBackend(HostGenerationMixin, DeepSeekBackend):
    pass


class ServiceDeepSeekOptimizedBackend(HostGenerationMixin, DeepSeekOptimizedBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service_contract["agent_engine"] = self.engine
        self.service_contract["deepseek_protocol_revision"] = 3
        self.service_receipt_refs = True
        self.service_contract["context_projection"] = "deepseek_receipt_refs_v1"
        self.service_reasoning_replay = True
        self.service_contract["reasoning_replay"] = "same_model_egress_scope_full_message_sha256_v2"


class ServiceDeepSeekNativeBackend(DeepSeekNativeBackend):
    def __init__(self, *args, generation_parameters=None, **kwargs):
        self.generation_parameters = generation_options(generation_parameters or {})
        if set(self.generation_parameters) - {'temperature', 'stop'}:
            raise ValueError('Unsupported Messages generation parameter')
        super().__init__(*args, **kwargs)
        self.service_contract = {'protocol': 'deepseek_messages_v1', 'timeout': self.timeout,
                                 'generation_parameters': dict(self.generation_parameters),
                                 'reasoning_replay': 'same_model_egress_scope_full_message_sha256_v2'}

    def _payload(self, *args, **kwargs):
        payload = super()._payload(*args, **kwargs)
        if 'temperature' in self.generation_parameters:
            payload['temperature'] = self.generation_parameters['temperature']
        if 'stop' in self.generation_parameters:
            value = self.generation_parameters['stop']
            payload['stop_sequences'] = [value] if isinstance(value, str) else value
        return payload


class ServiceOpenAIBackend(HostGenerationMixin, LocalHTTPBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.include_stream_usage:
            self.service_contract["include_stream_usage"] = True


class ServiceOMLXBackend(HostGenerationMixin, OMLXBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service_contract.update(provider='omlx', shared_service=True,
                                     include_stream_usage=self.include_stream_usage)


# Separate provider identity/capability/lifecycle contract, same Runtime API.
from agent.vllm import VLLMBackend


class ServiceVLLMBackend(VLLMBackend):
    pass


class ManagedLocalBackend(ServiceOpenAIBackend):
    """The trusted Model Manager owns loading; ordinary clients see Task API."""
    def __init__(self, *args, manager, **kwargs):
        self.manager=manager
        super().__init__(*args,api_key=manager.token,**kwargs)

    def health_check(self):
        return super().health_check()

    def request(self, *args, **kwargs):
        with self.manager.inference():
            return super().request(*args, **kwargs)

    def stream(self, *args, **kwargs):
        with self.manager.inference():
            yield from super().stream(*args, **kwargs)
