"""Reduce canonical GUI obligations using host-owned causal evidence only."""
import json
import math

from computer.schemas import WRITE_NAMES


def action_key(receipt):
    try:
        args = json.loads(receipt["arguments"])
    except (KeyError, ValueError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    return (args.get("app"), json.dumps(args.get("postcondition"), sort_keys=True))


def fresh_verification(receipt, obligation=None):
    proof = receipt.get("computer_evidence") or {}
    context = receipt.get("computer_context") or {}
    if not isinstance(proof, dict) or not isinstance(context, dict):
        return False
    result = receipt["payload"].get("result") or {}
    source = receipt.get("source_turn_id", receipt["turn_id"])
    if (receipt.get("receipt_reused") or not isinstance(result, dict)
            or result.get("status") != "ok" or result.get("verified") is not True
            or not proof.get("observation") or proof.get("observation") != result.get("observation")
            or proof.get("source_call_id") != receipt["id"] or proof.get("source_turn_id") != source):
        return False
    generation, observed_at = proof.get("observation_generation"), proof.get("observed_at")
    if (type(generation) is not int or type(observed_at) not in {int, float}
            or not math.isfinite(observed_at)
            or type(context.get("dispatch_generation")) is not int
            or type(context.get("resync_revision")) is not int
            or type(context.get("resync_generation")) is not int
            or proof.get("resync_generation") != context["resync_generation"]
            or generation <= context["dispatch_generation"]
            or generation < context["resync_revision"]):
        return False
    if obligation:
        previous = obligation.get("computer_context") or {}
        if (type(previous.get("dispatch_generation")) is not int
                or type(previous.get("resync_generation")) is not int
                or type(previous.get("recorded_at")) not in {int, float}
                or not math.isfinite(previous["recorded_at"])
                or generation <= previous["dispatch_generation"]
                or proof["resync_generation"] < previous["resync_generation"]
                or observed_at < previous["recorded_at"]):
            return False
    return True


def computer_obligations(receipts):
    unresolved, handoff, rejected = {}, set(), set()
    for receipt in receipts:
        if receipt["name"] not in WRITE_NAMES | {"verify"}:
            continue
        key = action_key(receipt)
        payload = receipt["payload"]
        result = payload.get("result")
        error = payload.get("error", {}).get("type")
        if receipt["name"] in WRITE_NAMES and error == "user_rejected":
            rejected.add(key)
            unresolved.pop(key, None)
            handoff.discard(key)
            continue
        # A refused old read identity and cached mutation are never new facts.
        if receipt.get("receipt_reused") or error == "stale_computer_call_id":
            continue
        if receipt["name"] in WRITE_NAMES and error == "human_handoff_invalidated":
            handoff.add(key)
            continue
        if receipt["name"] in WRITE_NAMES:
            rejected.discard(key)
        if fresh_verification(receipt, unresolved.get(key)):
            unresolved.pop(key, None)
            handoff.discard(key)
        elif receipt["name"] in WRITE_NAMES:
            previous = unresolved.get(key)
            if previous:
                def sent(r):
                    result = r["payload"].get("result")
                    if not isinstance(result, dict):
                        result = {}
                    return r.get("obligation_action_sent", result.get("action_sent",
                        False if r.get("side_effect_status") == "not_completed" else None))
                states = [sent(previous), sent(receipt)]
                unresolved[key] = {**receipt,
                    "obligation_action_sent": True if True in states else None if None in states else False,
                    "obligation_may_have_applied": previous.get("obligation_may_have_applied") is True
                        or previous.get("side_effect_status") in {"partial", "unknown"}
                        or receipt.get("side_effect_status") in {"partial", "unknown"}}
            else:
                unresolved[key] = receipt
        elif (receipt["name"] == "verify" and isinstance(result, dict)
              and (result.get("status") == "error" or result.get("verified") is True) and key not in rejected):
            # A failed read is evidence about an existing mutation, not a new
            # unsent action. Keep the original intent and side-effect provenance.
            unresolved.setdefault(key, receipt)
    return unresolved, handoff
