"""OpenAI text protocol subset; no backend requests or tool execution here."""
import json

from agent.backends import Message
from .service import APIError, SETTLED, TaskRequest


RESPONSE_STATUS = {"queued": "queued", "running": "in_progress", "cancelling": "in_progress",
    "completed": "completed", "failed": "failed", "cancelled": "cancelled", "timed_out": "incomplete",
    "incomplete": "incomplete", "requires_approval": "incomplete", "requires_human": "incomplete"}


def _text_content(content, part_type):
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(isinstance(p, dict) and set(p) <= {"type", "text"}
            and p.get("type") == part_type and isinstance(p.get("text"), str) for p in content):
        return "\n".join(p["text"] for p in content)
    raise APIError("Only text content is supported; images/audio/files/tool outputs require a future adapter")


def parse_request(body, protocol, service):
    if not isinstance(body, dict):
        raise APIError("Request must be a JSON object")
    allowed = {"model", "stream", "metadata", "localpilot", "max_output_tokens", "max_tokens"}
    allowed |= {"input", "instructions", "previous_response_id", "conversation", "background", "store"} if protocol == "responses" else {"messages", "n", "stream_options"}
    if set(body) - allowed:
        raise APIError("Unsupported parameters: " + ", ".join(sorted(set(body) - allowed)), "unsupported_parameter")
    for name in {"stream", "background", "store"} & body.keys():
        if type(body[name]) is not bool:
            raise APIError(f"{name} must be a boolean")
    if body.get("store") is False:
        raise APIError("store=false is unsupported; tasks are retained in process", "unsupported_parameter")
    if body.get("n", 1) != 1 or isinstance(body.get("n"), bool):
        raise APIError("Only n=1 is supported")
    if "metadata" in body and (not isinstance(body["metadata"], dict) or body["metadata"]):
        raise APIError("Nonempty metadata is not supported")
    if "stream_options" in body and body["stream_options"] not in ({}, {"include_usage": True}, {"include_usage": False}):
        raise APIError("Only stream_options.include_usage is supported")
    options = body.get("localpilot", {})
    if not isinstance(options, dict) or set(options) - {"session_id", "timeout_seconds"}:
        raise APIError("localpilot accepts only session_id and timeout_seconds")
    session_id = options.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id):
        raise APIError("session_id must be a nonempty string")
    previous = body.get("previous_response_id")
    if previous is not None and (not isinstance(previous, str) or not previous):
        raise APIError("previous_response_id must be a nonempty string")
    conversation = body.get("conversation")
    if isinstance(conversation, dict) and set(conversation) == {"id"}:
        conversation = conversation["id"]
    if conversation is not None:
        if not isinstance(conversation, str) or not conversation:
            raise APIError("conversation must be an existing session ID or {id: ID}")
        if previous:
            raise APIError("conversation and previous_response_id are mutually exclusive")
        if session_id and session_id != conversation:
            raise APIError("Conflicting session identifiers")
        session_id = conversation
    if previous:
        old = service.task_snapshot(previous)
        if session_id and session_id != old["session_id"]:
            raise APIError("previous_response_id belongs to another session", "session_conflict", 409)
        session_id = old["session_id"]
    history, instructions = [], body.get("instructions")
    source = body.get("input") if protocol == "responses" else body.get("messages")
    if protocol == "responses" and isinstance(source, str):
        text = source
    else:
        if not isinstance(source, list) or not source:
            raise APIError("input/messages must be nonempty text messages")
        parsed = []
        system = []
        for item in source:
            if not isinstance(item, dict) or set(item) - {"type", "role", "content"} or item.get("type", "message") != "message":
                raise APIError("Only text message inputs are supported")
            role = item.get("role")
            if not isinstance(role, str):
                raise APIError("Message role must be text")
            content = _text_content(item.get("content"), "input_text" if protocol == "responses" else "text")
            if role in {"system", "developer"}:
                if parsed:
                    raise APIError("System/developer instructions must precede conversation messages")
                system.append(content)
            elif role in {"user", "assistant"}:
                parsed.append(Message(role, content))
            else:
                raise APIError("Unsupported message role")
        if not parsed or parsed[-1].role != "user":
            raise APIError("The last message must be a user turn")
        if instructions is not None and not isinstance(instructions, str):
            raise APIError("instructions must be text")
        instructions = "\n".join(system + ([instructions] if instructions else [])) or None
        history, text = parsed[:-1], parsed[-1].content
    if "max_tokens" in body and "max_output_tokens" in body:
        raise APIError("Specify only one output token limit")
    request = TaskRequest(text, body.get("model", "localpilot"), session_id, tuple(history), instructions,
        options.get("timeout_seconds", 120), body.get("max_output_tokens", body.get("max_tokens")), previous)
    return request


def extension(task):
    return {"task_id": task["id"], "session_id": task["session_id"], "status": task["status"],
            "quiescent": task["quiescent"], "required_action": task["required_action"],
            "error": task["error"], "tools": task["tools"], "goals": task["goals"],
            "subagents": task.get("subagents", []), "computer": task["computer"],
            "verification_status": (task["result"] or {}).get("verification_status", "not_run"),
            "engineering_status": (task["result"] or {}).get("engineering_status", "unverified"),
            "task_outcome": (task["result"] or {}).get("task_outcome", "unverified"),
            "task_succeeded": (task["result"] or {}).get("task_outcome") == "passed",
            **({"service": task["service"]} if "service" in task else {}),
            **({"receipt_summary": task["receipt_summary"], "verification_summary": task["verification_summary"]}
               if "receipt_summary" in task else {})}


def usage(task, chat=False):
    calls = (task["result"] or {}).get("model_calls", [])
    # Never manufacture token counts from SSE chunks/characters/admission units.
    if not calls or any(c.get("input_tokens") is None or c.get("output_tokens") is None for c in calls):
        return None
    input_tokens = sum(c["input_tokens"] for c in calls)
    output_tokens = sum(c["output_tokens"] for c in calls)
    if chat:
        return {"prompt_tokens": input_tokens, "completion_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens,
            "input_tokens_details": {"cached_tokens": sum(c["prompt_cache_hit_tokens"] for c in calls) if all(c.get("prompt_cache_hit_tokens") is not None for c in calls) else None},
            "output_tokens_details": {"reasoning_tokens": None}}


def response(task):
    output = []
    for message in task["output"]:
        if message["role"] != "assistant":
            continue
        if message.get("content"):
            output.append({"id": task["id"] + "_msg_" + str(len(output)), "type": "message", "role": "assistant",
                "status": message.get("status", "completed"), "content": [{"type": "output_text", "text": message["content"], "annotations": []}]})
        for call in message.get("tool_calls", []):
            output.append({"id": task["id"] + "_fc_" + str(len(output)), "type": "function_call", "status": "completed",
                           "call_id": call["id"], "name": call["function"]["name"], "arguments": call["function"]["arguments"]})
    status = RESPONSE_STATUS[task["status"]]
    return {"id": task["id"], "object": "response", "created_at": task["created_at"], "model": task["model"],
        "status": status, "output": output, "error": task["error"], "usage": usage(task),
        "incomplete_details": {"reason": task["status"]} if status == "incomplete" else None,
        "previous_response_id": task["previous_task_id"], "conversation": {"id": task["session_id"]},
        "localpilot": extension(task)}


def _pending_calls(task):
    calls = {}
    for message in task["output"]:
        for call in message.get("tool_calls", []):
            calls[call["id"]] = call
        if message.get("tool_call_id"):
            calls.pop(message["tool_call_id"], None)
    return list(calls.values())


def finish_reason(task):
    if task["status"] == "completed":
        return "stop"
    if task["status"] == "requires_approval" and _pending_calls(task):
        return "tool_calls"
    if task["status"] == "incomplete" and (task["result"] or {}).get("status") in {"max_steps_exceeded", "tool_budget_exceeded"}:
        return "length"
    # Chat has no human/cancel/error finish reason; null plus the extension is
    # deliberate. A caller must not interpret this as successful completion.
    return None


def chat_completion(task):
    text = "".join(m.get("content") or "" for m in task["output"] if m["role"] == "assistant")
    message = {"role": "assistant", "content": text or None}
    if finish_reason(task) == "tool_calls":
        message["tool_calls"] = _pending_calls(task)
    return {"id": task["id"], "object": "chat.completion", "created": task["created_at"], "model": task["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason(task), "logprobs": None}],
            "usage": usage(task, True), "localpilot": extension(task)}


def _chunk(task, delta, finish=None, extra=None):
    return {"id": task["id"], "object": "chat.completion.chunk", "created": task["created_at"], "model": task["model"],
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish, "logprobs": None}], "usage": None, **(extra or {})}


def stream_events(service, task_id, protocol, *, include_usage=False):
    """Yield (event name, JSON body). Typed Responses items are opened/closed per
    model round; LocalPilot tool execution/events travel in an explicit extension.
    """
    task = service.task_snapshot(task_id)
    sequence, cursor, index = 0, 0, 0
    current = None
    seen_calls = set()
    def typed(event_type, **data):
        nonlocal sequence
        sequence += 1
        return event_type, {"type": event_type, "sequence_number": sequence, **data}
    def close_text(item_status="completed"):
        nonlocal current
        if current is None:
            return []
        item_id, output_index, text = current
        current = None
        item = {"id": item_id, "type": "message", "status": item_status, "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}]}
        return [typed("response.output_text.done", item_id=item_id, output_index=output_index, content_index=0, text=text),
                typed("response.content_part.done", item_id=item_id, output_index=output_index, content_index=0, part=item["content"][0]),
                typed("response.output_item.done", output_index=output_index, item=item)]
    if protocol == "responses":
        # Avoid a race where a fast completed task changes the initial event.
        initial = response({**task, "status": "running", "output": [], "result": None, "required_action": None})
        yield typed("response.created", response=initial)
        yield typed("response.in_progress", response=initial)
    else:
        yield None, _chunk(task, {"role": "assistant", "content": ""})
    while True:
        events, task = service.events(task_id, cursor)
        if not events and (task["status"] not in SETTLED or not task["quiescent"]):
            yield None, None  # HTTP heartbeat comment, not a fabricated chunk.
        for event in events:
            cursor = event["sequence"]
            if event["type"] != "runtime.event":
                continue
            runtime = event["data"]
            kind, data = runtime["type"], runtime["data"]
            if kind == "ModelResponseStarted" and protocol == "responses":
                yield from close_text()
            if kind == "TextDelta":
                if protocol == "responses":
                    if current is None:
                        item_id = task_id + "_msg_" + str(index)
                        current = [item_id, index, ""]
                        index += 1
                        yield typed("response.output_item.added", output_index=current[1],
                            item={"id": item_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []})
                        yield typed("response.content_part.added", item_id=item_id, output_index=current[1], content_index=0,
                            part={"type": "output_text", "text": "", "annotations": []})
                    current[2] += data["text"]
                    yield typed("response.output_text.delta", item_id=current[0], output_index=current[1], content_index=0,
                                delta=data["text"], logprobs=[])
                else:
                    yield None, _chunk(task, {"content": data["text"]})
            elif kind == "ToolCallRequested" and protocol == "responses" and (runtime["turn_id"], data["tool_call_id"]) not in seen_calls:
                seen_calls.add((runtime["turn_id"], data["tool_call_id"]))
                yield from close_text()
                arguments = data.get("call", {}).get("function", {}).get("arguments", data.get("arguments"))
                arguments = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
                item = {"id": task_id + "_fc_" + str(index), "type": "function_call", "call_id": data["tool_call_id"],
                        "name": data["name"], "arguments": arguments, "status": "completed"}
                yield typed("response.output_item.added", output_index=index, item={**item, "arguments": "", "status": "in_progress"})
                yield typed("response.function_call_arguments.delta", item_id=item["id"], output_index=index, delta=arguments)
                yield typed("response.function_call_arguments.done", item_id=item["id"], output_index=index, arguments=arguments, name=data["name"])
                yield typed("response.output_item.done", output_index=index, item=item)
                index += 1
            # Every runtime event, including approvals, goals, CU failures and
            # receipts, remains observable. It never invokes a client-side tool.
            if protocol == "responses":
                yield typed("localpilot.runtime_event", task_id=task_id, event=runtime)
            elif kind != "TextDelta":
                yield None, _chunk(task, {}, extra={"localpilot": {"task_id": task_id, "event": runtime}})
        if task["status"] in SETTLED and not task["quiescent"]:
            continue
        if task["status"] in SETTLED:
            if protocol == "responses":
                yield from close_text(task["output"][-1].get("status", "completed") if task["output"] else "completed")
                name = {"completed": "response.completed", "failed": "response.failed", "cancelled": "response.cancelled"}.get(task["status"], "response.incomplete")
                if task["status"] in {"requires_approval", "requires_human"}:
                    yield typed("localpilot." + task["status"], localpilot=extension(task))
                yield typed(name, response=response(task))
            else:
                if task["status"] == "failed":
                    yield None, {"error": task["error"], "localpilot": extension(task)}
                completion = chat_completion(task)
                pending = completion["choices"][0]["message"].get("tool_calls")
                if pending:
                    yield None, _chunk(task, {"tool_calls": [{"index": i, **c} for i, c in enumerate(pending)]})
                yield None, _chunk(task, {}, finish_reason(task), {"localpilot": extension(task)})
                if include_usage:
                    yield None, {**_chunk(task, {}), "choices": [], "usage": usage(task, True)}
                yield None, "[DONE]"
            return
