"""Read-only WeChat approval evidence checks; no network, credentials or services.

Call validate_case with authenticated snapshots, an explicit workspace and the
expected ordinary client subject, then validate_persisted_audit with host events.
The caller obtains those inputs; this module never loads platform login state.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

TERMINAL = {'completed', 'incomplete', 'failed', 'cancelled', 'timed_out'}
TARGETS = {'approved': 'approval-tests/approved.txt', 'rejected': 'approval-tests/rejected.txt'}


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def private(path):
    from localpilot_channels.security import private_file
    try:
        checked = private_file(path)
        require(checked.exists(), 'wrong_path_type')
        return checked
    except (OSError, ValueError):
        raise RuntimeError('private_path_required') from None


def fingerprint(value):
    return 'sha256:' + hashlib.sha256(str(value).encode()).hexdigest()[:16]


def receipts(task):
    rows = task.get('tools', [])
    require(isinstance(rows, list), 'receipts_invalid')
    seen, actual = set(), []
    for row in rows:
        rid = row.get('receipt_id')
        require(isinstance(rid, str) and rid not in seen, 'receipt_identity_invalid')
        seen.add(rid)
        payload = row.get('payload') or {}
        result = payload.get('result') or {}
        result = result if isinstance(result, dict) else {}
        reused = bool(row.get('receipt_reused') or (row.get('read_receipt') or {}).get('reused'))
        if (payload.get('ok') is True and row.get('receipt_reused') is False and not reused
                and result.get('stage') != 'not_dispatched' and result.get('status') not in {'denied', 'approval_required'}):
            actual.append(row)
    return actual


def exact_tool_tickets(history, task_id, session_id, target):
    tickets = set()
    for event in history:
        require(event.get('task_id') == task_id and event.get('session_id') == session_id, 'event_identity_mismatch')
        action = (event.get('data') or {}).get('required_action') or {}
        requests = action.get('requests') or []
        if len(requests) != 1:
            continue
        request = requests[0]
        changes = (request.get('preview') or {}).get('changes') or []
        if (request.get('kind') == 'tool' and request.get('name') == 'apply_patch' and len(changes) == 1
                and changes[0].get('path') == target and changes[0].get('operation') == 'create'):
            aid = action.get('id')
            if isinstance(aid, str) and re.fullmatch(r'[A-Za-z0-9_.:@-]{1,128}', aid):
                tickets.add(aid)
    return tickets


def validate_case(case, channel, task, history, platform, sender, *, workspace, client_subject):
    external, tid, sid = channel.get('task_id'), task.get('id'), task.get('session_id')
    require(re.fullmatch(r'm_[a-f0-9]{64}', external or '') and re.fullmatch(r'resp_[a-f0-9]{32}', tid or '')
            and re.fullmatch(r'sess_[a-f0-9]{32}', sid or ''), 'task_identity_invalid')
    require(channel.get('official_task_id') == tid and channel.get('session_id') == sid
            and task.get('object') == 'localpilot.task' and task.get('service', {}).get('client_subject') == client_subject, 'task_association_failed')
    require(task.get('quiescent') is True and task.get('status') in TERMINAL
            and (task.get('recovery') or {}).get('class') != 'UNKNOWN_BLOCKED', 'task_not_settled')
    target = TARGETS[case]
    tickets = exact_tool_tickets(history, tid, sid, target)
    choice = 'approve' if case == 'approved' else 'reject'
    accepted = [d for d in channel.get('decisions', []) if d.get('outcome') == 'applied'
                and d.get('decision') == choice and d.get('approval_id') in tickets]
    require(len(accepted) == 1, 'exact_tool_decision_not_confirmed')
    tools, actual = task.get('tools', []), receipts(task)
    patches = [row for row in tools if row.get('name') == 'apply_patch']
    reads = [row for row in tools if row.get('name') in {'file_info', 'list_directory'}]
    require(len(patches) == 1 and len(tools) == len(reads) + 1, 'unexpected_tool_set')
    require(all(row in actual and row.get('side_effect_status') == 'completed' for row in reads), 'preflight_execution_not_confirmed')
    patch = patches[0]
    from localpilot_channels.security import canonical_path
    path = canonical_path(Path(workspace).absolute() / target)
    if case == 'approved':
        require(task['status'] == 'completed' and channel.get('status') == 'completed'
                and len(actual) == len(tools) and patch in actual
                and patch.get('side_effect_status') == 'completed', 'approval_execution_not_confirmed')
        result = patch.get('payload', {}).get('result') or {}
        applied = result.get('changes') or []
        require(result.get('status') == 'ok' and len(applied) == 1
                and applied[0].get('path') == target and applied[0].get('operation') == 'create'
                and applied[0].get('before_sha256') is None and applied[0].get('verification') == 'passed', 'write_receipt_path_mismatch')
        path = private(path)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == applied[0].get('after_sha256'), 'created_file_receipt_mismatch')
    else:
        require(task['status'] == 'completed' and channel.get('status') == 'rejected'
                and len(actual) == len(reads) and patch.get('receipt_reused') is False
                and patch.get('side_effect_status') == 'not_completed' and patch.get('payload', {}).get('ok') is False
                and not path.exists() and not path.is_symlink()
                and (patch.get('payload', {}).get('error') or {}).get('type') == 'user_rejected', 'rejection_no_write_not_confirmed')
    audit = channel.get('audit') or {}
    require(audit.get('source') == 'official_task_receipts' and audit.get('official_task_id') == tid
            and audit.get('session_id') == sid and audit.get('receipt_count') == len(tools)
            and audit.get('successful_non_reused_receipts') == len(actual) and audit.get('reused_receipts') == 0, 'audit_association_failed')
    text = (task.get('result') or {}).get('text')
    require(isinstance(text, str) and text and channel.get('reply') == text, 'final_reply_mismatch')
    rows = list(platform.get('messages', {}).values())
    originals = [r for r in rows if r.get('taskId') == external and r.get('sender') == sender
                 and not r.get('kind') and not r.get('validationOnly')]
    require(len(originals) == 1, 'original_wechat_message_missing')
    sent = [r for r in rows if r.get('kind') in {'query', 'decision'} and r.get('taskId') == external and r.get('sender') == sender
            and r.get('peer') == originals[0].get('peer') and r.get('context')
            and r.get('delivery') == 'sent' and r.get('status') == channel['status'] and r.get('reply') == text]
    require(bool(sent), 'final_wechat_send_receipt_missing')
    return {'channel_task': fingerprint(external), 'official_task': fingerprint(tid),
            'session': fingerprint(sid), 'decision': choice, 'actual_execution_count': len(actual),
            'readonly_execution_count': len(reads), 'successful_write_count': int(case == 'approved'),
            'official_status': task['status'], 'channel_status': channel['status'], 'quiescent': True, 'delivery': 'sent'}


def validate_persisted_audit(case, task, linked):
    patches = [row for row in task['tools'] if row.get('name') == 'apply_patch']
    require(len(patches) == 1, 'unexpected_tool_set')
    receipt = hashlib.sha256(json.dumps(patches[0]['receipt_id'], sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    linked = [row for row in linked if row.get('official_task_id') == task['id'] and row.get('session_id') == task['session_id']]
    require(any(row.get('type') == 'official_tool_receipt_observed' and row.get('tool') == 'apply_patch'
                and row.get('receipt_fingerprint') == receipt and row.get('reused') is False
                and row.get('success_evidence') is (case == 'approved') for row in linked), 'persisted_tool_audit_missing')
    require(any(row.get('type') == 'official_task_state_observed' and row.get('task_status') == task['status']
                and row.get('quiescent') is True for row in linked), 'persisted_terminal_audit_missing')
