"""Offline regression: synthetic identities, real receipt field shapes; no services."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import wechat_approval_final as verifier


def fixture(case='approved', preflight=True):
    # The saved redacted audit has two successful preflights, one write, or one rejection.
    tid, sid, external = 'resp_' + '1' * 32, 'sess_' + '2' * 32, 'm_' + '3' * 64
    target, sender, action = verifier.TARGETS[case], 'synthetic-sender', 'synthetic-action'
    content = b'synthetic test body'
    change = {'path': target, 'operation': 'create', 'before_sha256': None,
              'after_sha256': hashlib.sha256(content).hexdigest(), 'verification': 'passed'}
    patch = {'name': 'apply_patch', 'receipt_id': 'synthetic-patch', 'receipt_reused': False,
             'side_effect_status': 'completed' if case == 'approved' else 'not_completed',
             'payload': {'ok': case == 'approved'}}
    if case == 'approved':
        patch['payload']['result'] = {'status': 'ok', 'changes': [change]}
    else:
        patch['payload']['error'] = {'type': 'user_rejected'}
    reads = [{'name': name, 'receipt_id': 'synthetic-' + name, 'receipt_reused': False,
              'side_effect_status': 'completed', 'payload': {'ok': True, 'result': {}}}
             for name in ('file_info', 'list_directory')] if preflight else []
    tools = reads + [patch]
    task = {'id': tid, 'session_id': sid, 'object': 'localpilot.task', 'quiescent': True,
            'status': 'completed', 'service': {'client_subject': 'wechat_user'},
            'tools': tools, 'result': {'text': 'synthetic final reply'}}
    channel = {'task_id': external, 'official_task_id': tid, 'session_id': sid,
               'status': 'completed' if case == 'approved' else 'rejected',
               'reply': task['result']['text'],
               'decisions': [{'outcome': 'applied', 'decision': 'approve' if case == 'approved' else 'reject',
                              'approval_id': action}]}
    history = [{'task_id': tid, 'session_id': sid, 'data': {'required_action': {
        'id': action, 'requests': [{'kind': 'tool', 'name': 'apply_patch',
                                  'preview': {'changes': [change]}}]}}}]
    original = {'taskId': external, 'sender': sender, 'peer': 'synthetic-peer'}
    sent = {**original, 'kind': 'query', 'context': 'synthetic-context', 'delivery': 'sent',
            'status': channel['status'], 'reply': channel['reply']}
    platform = {'messages': {'original': original, 'query': sent}}
    refresh_audit(channel, task)
    return case, channel, task, history, platform, sender


def refresh_audit(channel, task):
    channel['audit'] = {'source': 'official_task_receipts', 'official_task_id': task['id'],
                        'session_id': task['session_id'], 'receipt_count': len(task['tools']),
                        'successful_non_reused_receipts': len(verifier.receipts(task)),
                        'reused_receipts': 0}


class ApprovalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        target = root / 'workspace' / verifier.TARGETS['approved']
        target.parent.mkdir(parents=True)
        target.write_bytes(b'synthetic test body')
        target.chmod(0o600)
        self.workspace = root / 'workspace'

    def validate(self, *args):
        return verifier.validate_case(*args, workspace=self.workspace, client_subject='wechat_user')

    def test_saved_preflight_shape_passes_with_one_write(self):
        result = self.validate(*fixture())
        self.assertEqual(result['actual_execution_count'], 3)
        self.assertEqual(result['readonly_execution_count'], 2)
        self.assertEqual(result['successful_write_count'], 1)

    def test_success_uses_changes_not_error_only_applied(self):
        result = self.validate(*fixture(preflight=False))
        self.assertEqual(result['actual_execution_count'], 1)

    def test_rejection_with_and_without_preflight(self):
        for preflight in (False, True):
            with self.subTest(preflight=preflight):
                result = self.validate(*fixture('rejected', preflight))
                self.assertEqual(result['successful_write_count'], 0)
                self.assertEqual(result['actual_execution_count'], 2 if preflight else 0)

    def test_rejects_extra_write_or_unexpected_tool(self):
        for name in ('apply_patch', 'write_file', 'read_file', 'run_command'):
            with self.subTest(name=name):
                args = fixture()
                extra = copy.deepcopy(args[2]['tools'][0])
                extra.update(name=name, receipt_id='synthetic-extra')
                args[2]['tools'].append(extra)
                refresh_audit(args[1], args[2])
                with self.assertRaisesRegex(RuntimeError, '^unexpected_tool_set$'):
                    self.validate(*args)

    def test_rejects_reused_failed_or_unknown_receipt(self):
        for index in (0, 2):
            for mutation in ('reused', 'failed', 'unknown', 'not_dispatched'):
                with self.subTest(index=index, mutation=mutation):
                    args = fixture()
                    row = args[2]['tools'][index]
                    if mutation == 'reused':
                        row['receipt_reused'] = True
                    elif mutation == 'failed':
                        row['payload']['ok'] = False
                    elif mutation == 'unknown':
                        row['side_effect_status'] = 'unknown'
                    else:
                        row['payload']['result']['stage'] = 'not_dispatched'
                    refresh_audit(args[1], args[2])
                    with self.assertRaises(RuntimeError):
                        self.validate(*args)

    def test_rejects_duplicate_receipt_id(self):
        args = fixture()
        args[2]['tools'][-1]['receipt_id'] = args[2]['tools'][0]['receipt_id']
        with self.assertRaisesRegex(RuntimeError, '^receipt_identity_invalid$'):
            self.validate(*args)

    def test_model_text_cannot_substitute_for_patch(self):
        args = fixture()
        args[2]['tools'].pop()
        refresh_audit(args[1], args[2])
        with self.assertRaisesRegex(RuntimeError, '^unexpected_tool_set$'):
            self.validate(*args)

    def test_rejects_incorrect_path_hash_overwrite_or_partial_result(self):
        for mutation in ('path', 'hash', 'overwrite', 'partial', 'multiple'):
            with self.subTest(mutation=mutation):
                args = fixture()
                result = args[2]['tools'][-1]['payload']['result']
                change = result['changes'][0]
                if mutation == 'path':
                    change['path'] = 'other.txt'
                elif mutation == 'hash':
                    change['after_sha256'] = '0' * 64
                elif mutation == 'overwrite':
                    change['before_sha256'] = '0' * 64
                elif mutation == 'partial':
                    result['applied'] = result.pop('changes')
                    result['status'] = 'error'
                else:
                    result['changes'].append(copy.deepcopy(change))
                with self.assertRaises(RuntimeError):
                    self.validate(*args)

    def test_rejects_unbound_decision_identity_or_audit_count(self):
        for mutation in ('action', 'session', 'count', 'success_count'):
            with self.subTest(mutation=mutation):
                args = fixture()
                if mutation == 'action':
                    args[1]['decisions'][0]['approval_id'] = 'other-action'
                elif mutation == 'session':
                    args[1]['session_id'] = 'sess_' + '4' * 32
                elif mutation == 'count':
                    args[1]['audit']['receipt_count'] = 1
                else:
                    args[1]['audit']['successful_non_reused_receipts'] = 1
                with self.assertRaises(RuntimeError):
                    self.validate(*args)

    def test_rejects_no_tool_rejection_or_file_exists(self):
        for mutation in ('error', 'file'):
            with self.subTest(mutation=mutation):
                args = fixture('rejected', False)
                if mutation == 'error':
                    args[2]['tools'][0]['payload']['error']['type'] = 'other_error'
                else:
                    (self.workspace / verifier.TARGETS['rejected']).touch()
                with self.assertRaisesRegex(RuntimeError, '^rejection_no_write_not_confirmed$'):
                    self.validate(*args)

    def test_requires_phone_delivery_to_original_peer(self):
        args = fixture()
        args[4]['messages']['query']['peer'] = 'wrong-peer'
        with self.assertRaisesRegex(RuntimeError, '^final_wechat_send_receipt_missing$'):
            self.validate(*args)

    def test_persisted_audit_matches_patch_not_first_preflight(self):
        args = fixture()
        task = args[2]
        receipt = task['tools'][-1]['receipt_id']
        digest = hashlib.sha256(json.dumps(receipt, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        linked = [{'type': 'official_tool_receipt_observed', 'official_task_id': task['id'],
                   'session_id': task['session_id'], 'tool': 'apply_patch', 'receipt_fingerprint': digest,
                   'reused': False, 'success_evidence': True},
                  {'type': 'official_task_state_observed', 'official_task_id': task['id'],
                   'session_id': task['session_id'], 'task_status': 'completed', 'quiescent': True}]
        verifier.validate_persisted_audit('approved', task, linked)
        for mutation in ('fingerprint', 'session', 'reuse', 'state'):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(linked)
                if mutation == 'fingerprint':
                    bad[0]['receipt_fingerprint'] = 'wrong'
                elif mutation == 'session':
                    bad[0]['session_id'] = 'wrong'
                elif mutation == 'reuse':
                    bad[0]['reused'] = True
                else:
                    bad.pop()
                with self.assertRaises(RuntimeError):
                    verifier.validate_persisted_audit('approved', task, bad)

    def test_report_excludes_arguments_contents_and_identity(self):
        args = fixture()
        marker = 'SYNTHETIC_SENSITIVE_MARKER'
        args[2]['tools'][-1]['arguments'] = {'content': marker, 'api_key': marker}
        output = io.StringIO()
        with mock.patch('sys.stdout', output):
            result = self.validate(*args)
        report = output.getvalue() + json.dumps(result)
        for value in (marker, args[1]['task_id'], args[2]['id'], args[2]['session_id'], args[-1]):
            self.assertNotIn(value, report)


if __name__ == '__main__':
    unittest.main()
