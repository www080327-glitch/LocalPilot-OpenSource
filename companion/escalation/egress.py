"""Minimize before transport; rewriting never changes a source's grant."""
from dataclasses import asdict, is_dataclass


def cloud_context(request, approved=False):
    raw = asdict(request) if is_dataclass(request) else dict(request)
    scope = dict(raw.get("privacy_scope", {}))
    classification = scope.get("classification", "LOCAL_ONLY")
    if classification not in {"PUBLIC", "LOCAL_ONLY", "USER_APPROVED_CLOUD"}:
        raise ValueError("Unknown cloud classification")
    if classification == "LOCAL_ONLY" or approved is not True:
        raise PermissionError("cloud_context_not_authorized")
    # A selected request is reviewable. Observations, files and memories stay
    # local until a separate version-bound source grant is implemented.
    # Do not trust labels or summaries embedded in those source records.
    omitted = sum(len(raw.get(k, [])) for k in ("relevant_memories", "recent_events", "relevant_files"))
    for key in ("relevant_memories", "recent_events", "relevant_files"):
        raw[key] = []
    raw["companion_summary"] = ""
    scope.update(local_only=False, classification=classification,
                 context_policy="explicit_request_only", omitted_local_records=omitted)
    raw["privacy_scope"] = scope
    return raw
