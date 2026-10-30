"""Shared QQ/WeChat message facade over the official, authenticated durable task API."""
import hmac
import json
import os
import re
import threading
import time

from .client import ChannelError, ServiceClient
from .store import Store, digest

ID = re.compile(r'[A-Za-z0-9_.:@-]{1,128}')
TERMINAL = {'completed', 'incomplete', 'failed', 'cancelled', 'timed_out'}
STATUSES = TERMINAL | {'queued', 'running', 'cancelling', 'requires_approval', 'requires_human'}


class Adapter:
    def __init__(self, config, directory, *, environment=None, timeout=10, wait_seconds=1,
                 task_timeout_seconds=None):
        environment = os.environ if environment is None else environment
        if task_timeout_seconds is not None and (type(task_timeout_seconds) is not int or not 0 < task_timeout_seconds <= 3600):
            raise ValueError('invalid_task_timeout')
        self.task_timeout_seconds = task_timeout_seconds
        if set(config) != {'instance_id', 'service_url', 'channels'} or not ID.fullmatch(config['instance_id']):
            raise ValueError('invalid_channel_configuration')
        self.namespace = config['instance_id']
        self.channels, self.bindings, self.secrets = {}, {}, []
        subjects = set()

        def credential(name, minimum=24):
            value = environment.get(name, '') if isinstance(name, str) and name.isidentifier() else ''
            if not re.fullmatch(r'[!-~]{' + str(minimum) + r',4096}', value) or value in self.secrets:
                raise ValueError('missing_invalid_or_reused_channel_credential')
            self.secrets.append(value)
            return value

        for entry in config['channels']:
            if set(entry) - {'kind', 'channel', 'ingress_key_env', 'senders', 'approval'}:
                raise ValueError('unsupported_channel_configuration')
            channel, kind = entry['channel'], entry['kind']
            if (kind not in {'qq', 'wechat'} or not ID.fullmatch(channel)
                    or not channel.startswith('qq.' if kind == 'qq' else 'wechat.ilink.') or channel in self.channels):
                raise ValueError('invalid_channel_identity')
            cfg = {'key': credential(entry['ingress_key_env'], 16), 'kind': kind, 'approval': None}
            for sender in entry['senders']:
                if set(sender) != {'sender_id', 'subject', 'token_env', 'model'}:
                    raise ValueError('invalid_sender_configuration')
                sid, subject = sender['sender_id'], sender['subject']
                if not ID.fullmatch(sid) or subject in subjects or not ID.fullmatch(sender['model']):
                    raise ValueError('sender_subject_must_be_unique')
                client = ServiceClient(config['service_url'], credential(sender['token_env']), subject, timeout=timeout)
                if (channel, sid) in self.bindings:
                    raise ValueError('duplicate_sender')
                self.bindings[channel, sid] = {'client': client, 'model': sender['model']}
                subjects.add(subject)
            if entry.get('approval'):
                ap = entry['approval']
                if kind != 'wechat' or set(ap) != {'key_env', 'token_env', 'subject', 'senders'}:
                    raise ValueError('qq_approval_forbidden_or_invalid_operator')
                if not ap['senders'] or any((channel, sid) not in self.bindings for sid in ap['senders']):
                    raise ValueError('approvers_must_be_confirmed_senders')
                if ap['subject'] in subjects:
                    raise ValueError('operator_must_be_independent')
                cfg['approval'] = {'key': credential(ap['key_env'], 16), 'senders': set(ap['senders']),
                                   'client': ServiceClient(config['service_url'], credential(ap['token_env']),
                                                           ap['subject'], timeout=timeout)}
                subjects.add(ap['subject'])
            self.channels[channel] = cfg
        if not self.bindings:
            raise ValueError('explicit_senders_required')
        self.store = Store(directory, config)
        self.lock = threading.RLock()
        self.wait_seconds = max(0, min(wait_seconds, 10))

    def redact(self, value):
        if isinstance(value, str):
            for key in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(key, '[REDACTED]')
        elif isinstance(value, dict):
            value = {self.redact(k): self.redact(v) for k, v in value.items()}
        elif isinstance(value, list):
            value = [self.redact(v) for v in value]
        return value

    def authenticate(self, header, decision=False):
        for channel, cfg in self.channels.items():
            source = cfg['approval'] if decision else cfg
            if source and hmac.compare_digest(header.encode(), ('Bearer ' + source['key']).encode()):
                return channel
        raise ChannelError('invalid_channel_credential', 401)

    def dispatch(self, route, payload, channel):
        try:
            if route not in {'/messages', '/tasks/query', '/tasks/decision'}:
                raise ChannelError('not_found', 404)
            fields = {'channel', 'sender_id', 'message_id', 'text'} if route == '/messages' else {'channel', 'sender_id', 'task_id'}
            if route == '/tasks/decision':
                fields |= {'decision_id', 'approval_id', 'decision'}
            if (not isinstance(payload, dict) or not fields <= set(payload)
                    or set(payload) - fields - ({'reason'} if route == '/tasks/decision' else set())):
                raise ChannelError('invalid_channel_request', 400)
            for name in fields - {'text', 'decision'}:
                if not isinstance(payload[name], str) or not ID.fullmatch(payload[name]):
                    raise ChannelError('invalid_identifier', 400)
            owner = payload['channel'], payload['sender_id']
            if owner[0] != channel or owner not in self.bindings:
                raise ChannelError('sender_not_allowed', 403)
            with self.lock:
                if route == '/messages':
                    return self.submit(owner, payload)
                if route == '/tasks/decision':
                    return self.decision(owner, payload)
                record = self.record(owner, payload['task_id'])
                self.refresh(record, owner)
                return self.view(record, query=True)
        except ChannelError as exc:
            return exc.status, {'status': 'unknown' if exc.uncertain else 'error', 'error': {'code': exc.code}}

    def record_key(self, owner, message_id):
        return 'message:' + digest([*owner, message_id])

    def record(self, owner, task_id):
        value = self.store.get(self.record_key(owner, task_id))
        if value is None:
            raise ChannelError('task_not_found', 404)
        return value

    def save(self, record, owner, *, extra=None):
        state = self.store.get('owner:' + digest(owner)) or {}
        state.update(session_id=record.get('session_id'), active=record['external_id'] if record['unresolved'] or record.get('decision_hold') else None)
        if record.get('upstream_status') in {'cancelled', 'timed_out', 'failed'}:
            state['session_id'] = None
        self.store.put_many({self.record_key(owner, record['external_id']): record, 'owner:' + digest(owner): state, **(extra or {})})

    def submit(self, owner, payload):
        text = payload['text']
        if not isinstance(text, str) or not text.strip() or len(json.dumps(text, ensure_ascii=False).encode()) > 4096:
            raise ChannelError('task_input_too_large_or_empty', 413)
        if self.redact(text) != text:
            raise ChannelError('credential_in_input_rejected', 400)
        old = self.store.get(self.record_key(owner, payload['message_id']))
        fingerprint = digest(text)
        if old:
            if old['fingerprint'] != fingerprint:
                raise ChannelError('message_id_conflict', 409)
            if old.get('official_id'):
                self.refresh(old, owner)
            code, reply = self.view(old)
            return code, dict(reply, duplicate=True)
        state = self.store.get('owner:' + digest(owner)) or {}
        if state.get('active'):
            active = self.record(owner, state['active'])
            self.refresh(active, owner)
            if active['unresolved'] or active.get('decision_hold'):
                raise ChannelError('active_or_unknown_task_requires_query', 409)
            state = self.store.get('owner:' + digest(owner))
        record = {'external_id': payload['message_id'], 'fingerprint': fingerprint,
                  'key': digest([self.namespace, *owner, payload['message_id']]),
                  'official_id': None, 'session_id': state.get('session_id'),
                  'status': 'unknown', 'unresolved': True, 'http_status': 504,
                  'error': 'submission_not_confirmed', 'decisions': []}
        # Commit identity BEFORE submission; interrupted/unknown submissions are never replayed.
        self.save(record, owner)
        binding = self.bindings[owner]
        body = {'input': text, 'model': binding['model']}
        if self.task_timeout_seconds is not None:
            body['timeout_seconds'] = self.task_timeout_seconds
        if record['session_id']:
            body['session_id'] = record['session_id']
        try:
            task = binding['client'].submit(body, record['key'])
            self.snapshot(record, owner, task)
            until = time.monotonic() + self.wait_seconds
            while record['status'] == 'processing' and time.monotonic() < until:
                time.sleep(0.02)
                self.refresh(record, owner)
        except ChannelError as exc:
            record.update(status='unknown' if exc.uncertain else 'error', error=exc.code,
                          http_status=exc.status, unresolved=bool(record.get('official_id')) or exc.uncertain)
            self.save(record, owner)
        return self.view(record)

    def refresh(self, record, owner):
        if not record.get('official_id'):
            return  # A crashed submission with no official ID cannot safely be recreated.
        try:
            task = self.bindings[owner]['client'].task(record['official_id'])
            self.snapshot(record, owner, task)
        except ChannelError as exc:
            record.update(status='unknown' if exc.status not in {401, 403} else 'error',
                          error=exc.code, http_status=exc.status, unresolved=True)
            self.save(record, owner)

    def snapshot(self, record, owner, task):
        tid, sid = task.get('id'), task.get('session_id')
        if (not isinstance(tid, str) or not re.fullmatch(r'resp_[a-f0-9]{32}', tid)
                or not isinstance(sid, str) or not re.fullmatch(r'sess_[a-f0-9]{32}', sid)
                or (record.get('official_id') and tid != record['official_id'])
                or (record.get('session_id') and sid != record['session_id'])
                or task.get('object') != 'localpilot.task' or task.get('status') not in STATUSES
                or type(task.get('quiescent')) is not bool
                or task.get('service', {}).get('client_subject') != self.bindings[owner]['client'].subject):
            raise ChannelError('task_identity_or_protocol_mismatch', 504)
        record.update(official_id=tid, session_id=sid, upstream_status=task['status'])
        state = task['status']
        unknown = (task.get('recovery') or {}).get('class') == 'UNKNOWN_BLOCKED'
        status = ('unknown' if unknown else 'processing' if not task['quiescent'] or state in {'queued', 'running', 'cancelling'}
                  else 'pending_approval' if state == 'requires_approval' else 'requires_human' if state == 'requires_human'
                  else 'error' if state in {'failed', 'incomplete'} else state)
        if record.get('rejected') and state in TERMINAL and task['quiescent']:
            status = 'rejected'
        action = task.get('required_action') or {}
        if status == 'pending_approval' and (not isinstance(action.get('id'), str) or not ID.fullmatch(action['id'])):
            raise ChannelError('approval_evidence_missing', 504)
        record.update(status=status, unresolved=unknown or state not in TERMINAL or not task['quiescent'],
                      http_status=409 if status == 'pending_approval' else 200,
                      error='official_task_' + state if state in {'failed', 'incomplete'} else None,
                      approval_id=action.get('id') if status == 'pending_approval' else None,
                      approval=self.redact(action.get('requests', [])) if status == 'pending_approval' else None)
        result = task.get('result') or {}
        text = result.get('text')
        record['reply'] = self.redact(text)[:16000] if isinstance(text, str) else ''
        record['audit'] = self.audit(task)
        record['evidence'] = self.evidence(task, record['audit'])
        self.save(record, owner)

    def evidence(self, task, audit):
        # A model's final text and a successful receipt are separate observations.
        # Independent verification is only attached by an authenticated verifier;
        # this ingress has no verifier authority and never infers it from text.
        completion = task.get('completion') or {}
        if not isinstance(completion, dict):
            completion = {}
        return {'task_status': task['status'],
                'successful_tool_receipts': audit['successful_non_reused_receipts'],
                'final_text': 'present' if isinstance((task.get('result') or {}).get('text'), str) else 'absent',
                'delivery_status': completion.get('status') if completion.get('status') in
                    {'delivered', 'blocked', 'failed', 'pending'} else 'NOT_VERIFIED',
                'independent_verification': 'NOT_RUN'}

    def audit(self, task):
        rows = task.get('tools', [])
        if not isinstance(rows, list):
            raise ChannelError('tool_evidence_invalid', 504)
        seen, executed, reused = set(), 0, 0
        for row in rows:
            rid, name = row.get('receipt_id'), row.get('name')
            if not isinstance(rid, str) or not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,80}', name):
                raise ChannelError('tool_evidence_invalid', 504)
            if self.redact(name) != name:
                raise ChannelError('tool_evidence_invalid', 504)
            if rid in seen:
                raise ChannelError('duplicate_tool_receipt', 504)
            seen.add(rid)
            payload = row.get('payload') or {}
            result = payload.get('result') or {}
            result = result if isinstance(result, dict) else {}
            reuse = bool(row.get('receipt_reused') or (row.get('read_receipt') or {}).get('reused'))
            # These are host receipts, not model text or invented execution-start events.
            success = (payload.get('ok') is True and row.get('receipt_reused') is False and not reuse
                       and row.get('side_effect_status') == 'completed'
                       and result.get('stage') != 'not_dispatched' and result.get('status') not in {'denied', 'approval_required'})
            executed += int(success)
            reused += int(reuse)
            self.store.event({'type': 'official_tool_receipt_observed', 'official_task_id': task['id'],
                              'session_id': task['session_id'], 'receipt_fingerprint': digest(rid),
                              'tool': name, 'success_evidence': success, 'reused': reuse})
        self.store.event({'type': 'official_task_state_observed', 'official_task_id': task['id'],
                          'session_id': task['session_id'], 'task_status': task['status'], 'quiescent': task['quiescent']})
        return {'source': 'official_task_receipts', 'official_task_id': task['id'], 'session_id': task['session_id'],
                'receipt_count': len(seen), 'successful_non_reused_receipts': executed, 'reused_receipts': reused,
                'task_status': task['status'], 'status': 'recorded'}

    def decision(self, owner, payload):
        approval = self.channels[owner[0]]['approval']
        if not approval or owner[1] not in approval['senders']:
            raise ChannelError('approval_permission_denied', 403)
        action, reason = payload['decision'], payload.get('reason', '')
        if action not in {'approve', 'reject'} or not isinstance(reason, str) or len(reason) > 500 or (action == 'reject' and not reason.strip()):
            raise ChannelError('invalid_decision', 400)
        if self.redact(reason) != reason:
            raise ChannelError('credential_in_input_rejected', 400)
        record = self.record(owner, payload['task_id'])
        decision_key = 'decision:' + digest([*owner, payload['decision_id']])
        fingerprint = digest(payload)
        previous = self.store.get(decision_key)
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise ChannelError('decision_id_conflict', 409)
            if previous['outcome'] == 'unknown':
                raise ChannelError('decision_outcome_unknown_query_only', 504)
            if previous['outcome'] == 'refused':
                raise ChannelError(previous['error'], previous['http_status'])
            self.refresh(record, owner)
            code, reply = self.view(record)
            return code, dict(reply, duplicate=True)
        if record.get('decision_hold'):
            raise ChannelError('decision_outcome_unknown_query_only', 504)
        self.refresh(record, owner)
        if record['status'] != 'pending_approval' or record.get('approval_id') != payload['approval_id']:
            raise ChannelError('approval_not_current', 409)
        entry = {'fingerprint': fingerprint, 'outcome': 'unknown'}
        record['decision_hold'] = payload['decision_id']
        self.save(record, owner, extra={decision_key: entry})
        try:
            task = approval['client'].decide(record['official_id'], action, payload['approval_id'], reason)
            # Validate the authenticated snapshot/audit before acknowledging a decision.
            # The durable hold remains during snapshot persistence, including on crashes.
            self.snapshot(record, owner, task)
            record['decisions'].append({'decision_id': payload['decision_id'], 'approval_id': payload['approval_id'],
                                        'decision': action, 'reason': self.redact(reason), 'outcome': 'applied'})
            record['rejected'] = record.get('rejected', False) or action == 'reject'
            if record.get('rejected') and record['upstream_status'] in TERMINAL and not record['unresolved']:
                record['status'] = 'rejected'
            record.pop('decision_hold', None)
            self.save(record, owner, extra={decision_key: dict(entry, outcome='applied')})
        except ChannelError as exc:
            entry.update(outcome='unknown' if exc.uncertain else 'refused', error=exc.code, http_status=exc.status)
            if not exc.uncertain:
                record.pop('decision_hold', None)
            self.save(record, owner, extra={decision_key: entry})
            if exc.uncertain:
                record.update(status='unknown', unresolved=True, error='decision_outcome_unknown', http_status=504)
                self.save(record, owner)
            raise
        return self.view(record)

    def view(self, record, *, query=False):
        data = {'task_id': record['external_id'], 'message_id': record['external_id'], 'status': record['status'],
                'official_task_id': record.get('official_id'), 'session_id': record.get('session_id'),
                'reply': record.get('reply', ''), 'decisions': record['decisions']}
        for key in ('audit', 'approval_id', 'approval', 'upstream_status', 'decision_hold', 'evidence'):
            if record.get(key) is not None:
                data[key] = record[key]
        if record.get('error'):
            data['error'] = {'code': record['error']}
        if query:
            data['task_http_status'] = record['http_status']
        return (200 if query and record['http_status'] not in {401, 403} else record['http_status']), self.redact(data)

    def close(self):
        self.store.close()
