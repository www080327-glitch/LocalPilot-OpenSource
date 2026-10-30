"""Host-configured cloud worker models; a model name is not API access."""

from dataclasses import dataclass

from .deepseek import DeepSeekBackend
from .openai_backend import OpenAIWorkerBackend
from .cloud_credentials import CloudCredentialError


TIERS = ("LIGHT", "STRONG")
DEFAULT_MAPPING = {"LIGHT": "openai:gpt-6-luna", "STRONG": "openai:gpt-6-sol"}


@dataclass(frozen=True)
class WorkerModel:
    provider: str
    model: str

    @classmethod
    def parse(cls, value):
        provider, separator, model = value.partition(":")
        if not separator or provider not in {"openai", "deepseek"} or not model.strip():
            raise ValueError("Worker model must be openai:MODEL or deepseek:MODEL")
        return cls(provider, model.strip())


def configure_workers(mapping=None, *, data_policy=None):
    """Return (backends, availability). Missing credentials remain unavailable."""
    mapping = mapping or DEFAULT_MAPPING
    if set(mapping) - set(TIERS):
        raise ValueError("Unknown worker tier")
    backends, availability = {}, {}
    for tier in TIERS:
        configured = WorkerModel.parse(mapping.get(tier, DEFAULT_MAPPING[tier]))
        backend = None
        reason = None
        try:
            if configured.provider == "openai":
                backend = OpenAIWorkerBackend(model=configured.model, data_policy=data_policy)
            else:
                backend = DeepSeekBackend(model=configured.model, data_policy=data_policy)
        except ValueError as error:
            if isinstance(error, CloudCredentialError):
                if error.category != 'missing_credentials':
                    raise
            elif "API_KEY" not in str(error):
                raise
            reason = "missing_api_credentials"
        backends[tier] = backend
        availability[tier] = {"provider": configured.provider, "configured_model": configured.model,
                              "available": backend is not None, "reason": reason,
                              "verified_api_access": False}
    return backends, availability
