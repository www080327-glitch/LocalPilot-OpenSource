"""Request-only receipt references; SQLite remains the complete authority.

Inspired by DSH's event-derived request projection and explicit tool snapshots.
No DSH Session format, acceptance watermark, or second task store is introduced.
"""
from copy import deepcopy


def project_handoff(contract, tools):
    """Deduplicate exact evidence records and publish the current tool surface.

    An evidence record is replaced only if its full value remains available in
    completed_steps under an unambiguous receipt_id. UNKNOWN/failed records,
    permissions, budgets, task revisions and pending obligations are untouched.
    This view is assembled before Cloud Egress authorization and byte admission.
    """
    from .hybrid import sha
    view = deepcopy(contract)
    completed = view.get("completed_steps", [])
    evidence = view.get("verified_evidence", [])
    ids = [record.get("receipt_id") for record in completed]
    if evidence and all(record.get("receipt_id") and ids.count(record["receipt_id"]) == 1
                        and record in completed for record in evidence):
        view.pop("verified_evidence")
        view["verified_evidence_refs"] = [record["receipt_id"] for record in evidence]
        view["evidence_reference_rule"] = (
            "verified_evidence_refs refers to the exact complete records in completed_steps by receipt_id; "
            "these are version-bound observations, not task verification or permission grants.")
    # The canonical catalog may contain read_file during finalization even
    # though the actual request has no tools. Never advertise that stale surface.
    if tools is None:
        view["available_tools"] = []
        view["tool_schema_sha256"] = sha(None)
    view["request_projection"] = "deepseek_receipt_refs_v1"
    return view
