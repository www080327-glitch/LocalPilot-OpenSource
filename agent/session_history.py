"""Retain a completed turn without rewriting its admitted model window."""
from .context_v5 import RequestHistory


def retained_turn(runtime, context_start):
    history = runtime._request_history
    # A turn can finish before dispatch. Keep the preceding response and any
    # other canonical tail that has not entered the admitted window yet.
    cut = min(context_start, history.source_count)
    prefix = [message for message in runtime.messages[:cut] if message.role == 'system']
    removed = cut - len(prefix)
    if removed <= 0:
        return None
    workers = [record for record in runtime.subagents if record['turn_id'] == runtime.turn_id]
    worker_ids = {record['id'] for record in workers}
    return {
        'messages': prefix + runtime.messages[cut:],
        'tool_history': [receipt for receipt in runtime.tool_history if receipt['turn_id'] == runtime.turn_id],
        'completed_tool_calls': {key: value for key, value in runtime.completed_tool_calls.items()
                                 if key[0] == runtime.turn_id},
        'subagents': workers,
        '_children': {key: child for key, child in runtime._children.items() if key in worker_ids},
        '_child_accounted': {key: value for key, value in runtime._child_accounted.items() if key in worker_ids},
        '_call_context': {key: value for key, value in runtime._call_context.items() if key[0] == runtime.turn_id},
        '_request_history': RequestHistory(history.scope, history.source_count - removed, history.messages),
    }, context_start - removed
