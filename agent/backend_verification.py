"""Bounded service smoke: no AgentSession, Gateway, workspace tools or model lifecycle."""

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import uuid

from .backends import Message
from .local_http import LocalBackendError
from .serving import VERIFICATION_CHECKS


CHECKS = VERIFICATION_CHECKS
EVIDENCE = ("unclassified-service", "scripted-tested", "real-model-tested")


class ProbeFailure(ValueError):
    def __init__(self, message, observations=None):
        super().__init__(message)
        self.observations = observations or []


def observation(response):
    return {"reported_model": response.model, "finish_reason": response.finish_reason,
            "usage": response.usage, "text_characters": len(response.message.content or ""),
            "reasoning_characters": len(response.message.reasoning_content or ""),
            "tool_calls": len(response.message.tool_calls)}


def complete(response, *, tools=False):
    allowed = {"tool_calls"} if tools else {"stop"}
    if response.finish_reason not in allowed:
        raise ProbeFailure("Unexpected or incomplete finish_reason", [observation(response)])
    if not tools and (response.message.tool_calls or not (response.message.content or "").strip()):
        raise ProbeFailure("Expected a nonempty text answer without tool calls", [observation(response)])
    return response


def streamed(backend, messages, tools=None):
    response = None
    text, reasoning = [], []
    size = 0
    for index, chunk in enumerate(backend.stream(messages, tools=tools, max_tokens=96)):
        size += len(chunk.text.encode())
        if index > 1024 or size > 16384:
            raise ProbeFailure("Smoke output guard exceeded")
        if chunk.kind == "text":
            text.append(chunk.text)
        elif chunk.kind == "reasoning":
            reasoning.append(chunk.text)
        elif chunk.kind == "response":
            if response is not None:
                raise ProbeFailure("Multiple terminal responses")
            response = chunk.response
    if response is None:
        raise ProbeFailure("Missing terminal stream response")
    if (response.message.content or "") != "".join(text) or (response.message.reasoning_content or "") != "".join(reasoning):
        raise ProbeFailure("Stream deltas do not match terminal response")
    return response


def verify_backend(backend, checks=CHECKS, *, evidence_kind="unclassified-service"):
    """Only explicit invocation sends fixed synthetic prompts to configured service.

    Verified means this small protocol observation, never a context/performance
    guarantee. A failed prompt or transport error is unknown, not unsupported.
    """
    checks = tuple(checks)
    if not checks or set(checks) - set(CHECKS):
        raise ValueError("Unknown/empty backend smoke checks")
    if evidence_kind not in EVIDENCE:
        raise ValueError("Unknown evidence kind")
    results = {}
    state = backend.status()
    healthy = state["service_running"] and state["model_available"]
    results["health_models"] = {"status": "verified" if healthy else "unknown",
        "outcome": "passed" if healthy else "failed", "source": "models_endpoint",
        "detail": "Configured model ID listed; inference not established" if healthy else state.get("error", "Models unavailable"),
        "observations": []}

    def probe(name):
        prompt = [Message("user", "Reply with the word READY.")]
        if name == "basic_chat":
            return [observation(complete(backend.request(prompt, max_tokens=96)))]
        if name == "streaming":
            return [observation(complete(streamed(backend, prompt)))]
        if name == "reasoning":
            response = complete(backend.request([Message("user", "Compute 7 times 8. Reason briefly, then give the answer.")],
                thinking=next(iter(backend.capabilities.supported_thinking_efforts), None), max_tokens=96))
            if not (response.message.reasoning_content or "").strip():
                raise ProbeFailure("No structured reasoning_content observed; thinking control remains unverified", [observation(response)])
            return [observation(response)]
        token = secrets.token_hex(4)
        tools = [{"type": "function", "function": {"name": "probe_echo", "description": "Synthetic echo; no real tools or side effects.",
            "parameters": {"type": "object", "properties": {"token": {"type": "string"}},
                           "required": ["token"], "additionalProperties": False}}}]
        messages = [Message("user", f"Call probe_echo with token {token}. After receiving its result, repeat the returned token.")]
        # Verify streamed tool fragments/continuation when configured and selected.
        send = (lambda ms, ts: streamed(backend, ms, ts)) if "streaming" in checks and backend.capabilities.supports_streaming else (
            lambda ms, ts: backend.request(ms, tools=ts, max_tokens=96))
        first = complete(send(messages, tools), tools=True)
        first_observation = observation(first)
        calls = first.message.tool_calls
        if len(calls) != 1 or not calls[0].id or calls[0].name != "probe_echo":
            raise ProbeFailure("Expected one structured probe_echo call", [first_observation])
        try:
            args = json.loads(calls[0].arguments)
        except (ValueError, TypeError) as error:
            raise ProbeFailure("Tool arguments are not valid JSON", [first_observation]) from error
        if args != {"token": token}:
            raise ProbeFailure("Tool arguments did not match the synthetic schema/request", [first_observation])
        # This is a synthetic reply, never a dispatch to Registry/Gateway.
        reply_token = secrets.token_hex(4)
        messages += [first.message, Message("tool", json.dumps({"token": reply_token}), tool_call_id=calls[0].id)]
        try:
            second = complete(send(messages, tools))
        except ProbeFailure as error:
            error.observations.insert(0, first_observation)
            raise
        if reply_token not in (second.message.content or ""):
            raise ProbeFailure("Tool-result continuation did not echo the result", [first_observation, observation(second)])
        return [first_observation, observation(second)]

    for name in CHECKS[1:]:
        configured = backend.profile.configured_capabilities.get(name)
        if name not in checks or not healthy:
            results[name] = {"status": "unknown", "outcome": "skipped", "source": "not_run",
                             "detail": "Not selected" if name not in checks else "Health/models failed", "observations": []}
        elif configured is False:
            results[name] = {"status": "unsupported", "outcome": "skipped", "source": "operator_disabled",
                             "detail": "Disabled by operator configuration; no model test", "observations": []}
        elif name == "reasoning" and configured is not True:
            results[name] = {"status": "unknown", "outcome": "skipped", "source": "not_run",
                             "detail": "No explicit reasoning configuration; no generic thinking mapping assumed", "observations": []}
        else:
            try:
                observations = probe(name)
                results[name] = {"status": "verified", "outcome": "passed", "source": "smoke_observation",
                                 "detail": "Short protocol sample passed", "observations": observations}
            except (LocalBackendError, ProbeFailure, OSError, ValueError) as error:
                results[name] = {"status": "unknown", "outcome": "failed", "source": "smoke_observation",
                    "detail": str(error), "error_type": type(error).__name__,
                    "status_code": getattr(error, "status_code", None), "observations": getattr(error, "observations", [])}
    report = {"schema_version": 1, "run_id": str(uuid.uuid4()),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "profile_fingerprint": backend.profile.fingerprint, "profile": backend.profile.identity(),
        "evidence_kind": evidence_kind, "evidence_source": "operator_declared_not_model_attestation",
        "checks": results, "passed": all(c["outcome"] != "failed" for c in results.values()),
        "limits": "Short protocol smoke only; no context limit, performance, reasoning correctness/control, parallel tools, cache or Agent quality proof."}
    backend.profile.attach_verification(report)
    return report


def render_report(report):
    lines = ["# Inference backend verification", "", f"Run: {report['run_id']}",
             f"UTC: {report['verified_at']}", f"Evidence: {report['evidence_kind']} (operator declared)",
             f"Profile fingerprint: {report['profile_fingerprint']}", "",
             "| Check | Status | Outcome | Source | Detail |", "| --- | --- | --- | --- | --- |"]
    for name, check in report["checks"].items():
        detail = check["detail"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {check['status']} | {check['outcome']} | {check['source']} | {detail} |")
    lines += ["", report["limits"], "", "Configured identity (operator claims, not hardware measurements):", "", "```json",
              json.dumps(report["profile"], ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def write_report(report, stem):
    target = Path(stem).expanduser()
    json_path, md_path = Path(str(target) + ".json"), Path(str(target) + ".md")
    if json_path.exists() or md_path.exists():
        raise FileExistsError("Backend report already exists; choose a new output stem")
    with json_path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with md_path.open("x", encoding="utf-8") as output:
        output.write(render_report(report))
    return json_path, md_path
