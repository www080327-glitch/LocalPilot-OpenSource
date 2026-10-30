"""Future Model Manager v1 contract and a deliberately non-executing test adapter."""
from copy import deepcopy
from dataclasses import dataclass
import uuid
from .sdk import Client


@dataclass(frozen=True)
class ResourceGrant:
    allowed_models: tuple = ()
    allow_download: bool = False
    max_download_bytes: int = 0
    disk_bytes: int = 0
    memory_bytes: int = 0
    hardware: str = "UNKNOWN"
    approved_licenses: tuple = ()
    approved_sources: tuple = ()

    def __post_init__(self):
        if type(self.allow_download) is not bool:
            raise ValueError("allow_download must be a host boolean")
        if any(type(v) is not int or v < 0 for v in
               (self.max_download_bytes, self.disk_bytes, self.memory_bytes)):
            raise ValueError("Resource grants require finite nonnegative integer byte budgets")
        if not isinstance(self.hardware, str) or not self.hardware:
            raise ValueError("Hardware must be identified text or UNKNOWN")
        if any(not isinstance(v, tuple) or any(not isinstance(s, str) or not s for s in v)
               for v in (self.allowed_models, self.approved_licenses, self.approved_sources)):
            raise ValueError("Host model/source/license grants must be tuples of named entries")


class ManagerError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class ControlledModelManager:
    """Simulation only: never downloads, loads code, installs dependencies or starts vLLM."""
    evidence_kind = "SIMULATED"

    def __init__(self, registry):
        self.registry = deepcopy(registry)
        self.jobs, self.keys = {}, {}

    def list_models(self):
        return [{"id": k, **deepcopy(v)} for k,v in self.registry.items()]

    def model(self, model_id):
        if model_id not in self.registry:
            raise ManagerError("model_not_registered")
        return {"id": model_id, **deepcopy(self.registry[model_id])}

    def health(self):
        return {"status": "ready", "evidence_kind": self.evidence_kind, "real_vllm": "NOT_RUN"}

    def job(self, job_id):
        return deepcopy(self.jobs[job_id])

    def ensure(self, model_id, *, grant, idempotency_key, operation="ensure"):
        model = self.model(model_id)
        if operation not in {"ensure", "download", "load", "unload"}:
            raise ManagerError("operation_unsupported")
        if not isinstance(grant, ResourceGrant) or model_id not in grant.allowed_models:
            raise ManagerError("model_permission_denied")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ManagerError("idempotency_required")
        fingerprint = (model_id, operation, grant)
        if idempotency_key in self.keys:
            old, jid = self.keys[idempotency_key]
            if old != fingerprint:
                raise ManagerError("idempotency_conflict")
            return self.job(jid)
        reason = None
        if operation != "unload":
            if model.get("trust_remote_code") is not False:
                reason = "untrusted_code_forbidden"
            elif model.get("source") not in grant.approved_sources or not model.get("revision"):
                reason = "source_revision_not_approved"
            elif model.get("license") not in grant.approved_licenses:
                reason = "license_not_approved"
            elif model.get("hardware") != grant.hardware or grant.hardware == "UNKNOWN":
                reason = "hardware_incompatible_or_unknown"
            else:
                resource = model.get("resource_estimate", {})
                memory, disk = resource.get("memory_bytes"), resource.get("disk_bytes")
                if type(memory) is not int or type(disk) is not int or memory < 0 or disk < 0:
                    reason = "resource_estimate_unknown"
                elif memory > grant.memory_bytes or disk > grant.disk_bytes:
                    reason = "resource_budget_exceeded"
                elif not model.get("downloaded", False) and (not grant.allow_download or disk > grant.max_download_bytes):
                    reason = "download_not_authorized"
                elif operation == "load" and not model.get("downloaded", False):
                    reason = "model_not_downloaded"
        jid = "job_" + uuid.uuid4().hex
        job = {"id": jid, "model_id": model_id, "operation": operation, "status": "failed" if reason else "queued",
               "failure_reason": reason, "progress": 0, "evidence_kind": self.evidence_kind}
        self.jobs[jid] = job; self.keys[idempotency_key] = (fingerprint, jid)
        return self.job(jid)

    def advance(self, job_id):
        job = self.jobs[job_id]
        if job["status"] == "failed" or job["status"] == "completed":
            return self.job(job_id)
        phases = ["queued", "downloading", "loading", "completed"] if job["operation"] == "ensure" else ["queued", "running", "completed"]
        index = phases.index(job["status"]) + 1
        job["status"], job["progress"] = phases[index], int(100 * index / (len(phases)-1))
        if job["status"] == "completed":
            model = self.registry[job["model_id"]]
            model["deployment_status"] = "not_deployed" if job["operation"] in {"unload", "download"} else "ready"
            if job["operation"] != "unload":
                model["downloaded"] = True
        return self.job(job_id)


class HTTPModelManager:
    """Authenticated contract transport. Host supplies a bounded grant ID, not arbitrary code/options."""
    def __init__(self, base_url, *, token, timeout=15):
        self.client = Client(base_url, token=token, timeout=timeout)

    def list_models(self):
        return self.client.request("/model-manager/v1/models")

    def model(self, model_id):
        from urllib.parse import quote
        return self.client.request("/model-manager/v1/models/" + quote(model_id, safe=""))

    def health(self):
        return self.client.request("/model-manager/v1/health")

    def job(self, job_id):
        from urllib.parse import quote
        return self.client.request("/model-manager/v1/jobs/" + quote(job_id, safe=""))

    def ensure(self, model_id, *, grant_id, idempotency_key, operation="ensure"):
        if operation not in {"ensure", "download", "load", "unload"}:
            raise ManagerError("operation_unsupported")
        return self.client.request("/model-manager/v1/jobs", {"model_id": model_id, "grant_id": grant_id, "operation": operation}, key=idempotency_key)
