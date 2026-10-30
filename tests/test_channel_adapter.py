"""Windows/POSIX portable contract and failure tests using isolated HTTP services."""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest

from localpilot_channels.adapter import Adapter
from localpilot_channels.client import ChannelError, ServiceClient
from localpilot_channels.server import make_server
from localpilot_channels.store import Store
from tests.channel_fixtures import ENV, QA, QB, QQ, WA, WB, WX, FakeOfficial, configuration, receipt


class ChannelAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.host = FakeOfficial()
        self.config = configuration(self.host.url)
        self.adapter = Adapter(self.config, self.root / 'state', environment=ENV, timeout=.2, wait_seconds=0)

    def tearDown(self):
        self.adapter.close()
        self.host.close()
        self.tmp.cleanup()

    def message(self, text='list', mid='message', channel=QQ, sender=QA):
        return self.adapter.dispatch('/messages', {'channel': channel, 'sender_id': sender, 'message_id': mid, 'text': text}, channel)

    def query(self, mid='message', channel=QQ, sender=QA):
        return self.adapter.dispatch('/tasks/query', {'channel': channel, 'sender_id': sender, 'task_id': mid}, channel)

    def decide(self, mid='message', *, action='approve', aid=None, did='decision-1', sender=WA):
        if aid is None:
            aid = self.query(mid, WX, sender)[1].get('approval_id', 'missing')
        return self.adapter.dispatch('/tasks/decision', {'channel': WX, 'sender_id': sender, 'task_id': mid,
            'approval_id': aid, 'decision_id': did, 'decision': action, 'reason': 'test'}, WX)

    def test_both_channels_and_two_senders_have_independent_official_tasks_and_sessions(self):
        replies = [self.message(mid='same', channel=c, sender=s)[1] for c, s in ((QQ, QA), (QQ, QB), (WX, WA), (WX, WB))]
        self.assertEqual(len({r['official_task_id'] for r in replies}), 4)
        self.assertEqual(len({r['session_id'] for r in replies}), 4)
        self.assertTrue(all(r['task_id'] == 'same' and r['status'] == 'completed' for r in replies))
        self.assertEqual({p[0] for p in self.host.posts}, {'qa', 'qb', 'wa', 'wb'})
        self.assertEqual(self.query('same', QQ, WA)[0], 403)

    def test_task_timeout_is_explicit_and_default_is_unchanged(self):
        self.message(mid='default')
        self.adapter.close()
        self.adapter = Adapter(self.config, self.root / 'state', environment=ENV,
                               wait_seconds=0, task_timeout_seconds=900)
        self.message(mid='long')
        self.assertNotIn('timeout_seconds', self.host.posts[0][2])
        self.assertEqual(self.host.posts[1][2]['timeout_seconds'], 900)

    def test_task_timeout_rejects_invalid_values(self):
        for value in (True, 0, 3601):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid_task_timeout'):
                Adapter(self.config, self.root / 'invalid', environment=ENV, task_timeout_seconds=value)
        self.assertEqual(len(self.host.posts), 0)

    def test_duplicates_are_durable_and_changed_text_conflicts_without_second_submission(self):
        first = self.message()[1]
        self.assertTrue(self.message()[1]['duplicate'])
        self.assertEqual(self.message('changed')[0], 409)
        self.adapter.close()
        self.adapter = Adapter(self.config, self.root/'state', environment=ENV, wait_seconds=0)
        again = self.message()[1]
        self.assertEqual(again['official_task_id'], first['official_task_id'])
        self.assertEqual(len(self.host.posts), 1)

    def test_same_sender_reuses_session_but_new_message_gets_new_idempotency_key(self):
        a = self.message(mid='one')[1]
        b = self.message(mid='two')[1]
        self.assertEqual(a['session_id'], b['session_id'])
        self.assertNotEqual(self.host.posts[0][1], self.host.posts[1][1])
        self.assertEqual(self.host.posts[1][2]['session_id'], a['session_id'])

    def test_queued_running_completed_and_unknown_are_not_confused(self):
        reply = self.message()[1]
        task = self.host.tasks[reply['official_task_id']]
        for state in ('queued', 'running'):
            task.update(status=state, quiescent=False)
            self.assertEqual(self.query()[1]['status'], 'processing')
        task.update(status='requires_human', quiescent=True, recovery={'class': 'UNKNOWN_BLOCKED'})
        self.assertEqual(self.query()[1]['status'], 'unknown')
        self.assertEqual(self.message(mid='new')[0], 409)
        task.update(status='completed', recovery=None)
        self.assertEqual(self.query()[1]['status'], 'completed')

    def test_authoritative_failed_and_incomplete_tasks_never_report_completed(self):
        reply = self.message()[1]
        task = self.host.tasks[reply['official_task_id']]
        for state, local in [('failed', 'error'), ('incomplete', 'error'), ('timed_out', 'timed_out'), ('requires_human','requires_human')]:
            task.update(status=state)
            result = self.query()[1]
            self.assertEqual(result['status'], local)
            self.assertEqual(result['upstream_status'], state)

    def test_permission_conflict_and_unavailable_errors_do_not_retry_submission(self):
        for code in (401, 403, 409, 429, 503):
            with self.subTest(code=code):
                self.host.failure = code
                response = self.message(mid='fail-' + str(code))
                self.assertEqual(response[0], code)
                self.assertEqual(response[1]['status'], 'unknown' if code >= 500 else 'error')
                self.message(mid='fail-' + str(code))
        self.assertEqual(len(self.host.posts), 5)

    def test_lost_submission_response_blocks_replay_even_after_restart(self):
        self.host.drop_submit = True
        self.assertEqual(self.message()[1]['status'], 'unknown')
        self.assertEqual(len(self.host.tasks), 1)
        self.adapter.close()
        self.adapter = Adapter(self.config, self.root/'state', environment=ENV, wait_seconds=0)
        self.assertEqual(self.message()[1]['status'], 'unknown')
        self.assertEqual(self.message(mid='new')[0], 409)
        self.assertEqual(len(self.host.posts), 1)

    def test_query_failure_keeps_known_task_and_later_query_recovers_without_resubmission(self):
        first = self.message()[1]
        self.host.task_failure = 503
        self.assertEqual(self.query()[1]['status'], 'unknown')
        self.host.task_failure = None
        result = self.query()[1]
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['official_task_id'], first['official_task_id'])
        self.assertEqual(len(self.host.posts), 1)

    def test_real_http_timeout_retains_unknown_submission_and_never_retries(self):
        self.host.submit_delay = .4
        self.assertEqual(self.message()[0], 504)
        self.assertEqual(self.message()[1]['status'], 'unknown')
        self.assertEqual(len(self.host.posts), 1)

    def test_query_timeout_can_be_recovered_with_a_read_only_query(self):
        self.message()
        self.host.query_delay = .4
        self.assertEqual(self.query()[1]['status'], 'unknown')
        self.host.query_delay = 0
        self.assertEqual(self.query()[1]['status'], 'completed')
        self.assertEqual(len(self.host.posts), 1)

    def test_subject_mismatch_stops_before_submission(self):
        self.host.health_subject = 'other'
        self.assertEqual(self.message()[0], 403)
        self.assertEqual(len(self.host.posts), 0)

    def test_mismatched_task_or_session_is_unknown_not_success(self):
        first = self.message()[1]
        task = self.host.tasks[first['official_task_id']]
        task['session_id'] = 'sess_' + 'f'*32
        self.assertEqual(self.query()[1]['status'], 'unknown')

    def test_client_rejects_nonloopback_paths_redirects_and_wrong_keys(self):
        for url in ('http://example.com', 'http://127.0.0.1/v1', 'http://u:p@127.0.0.1'):
            with self.assertRaises(ValueError):
                ServiceClient(url, ENV['QA'], 'qa')
        with self.assertRaises(ChannelError) as caught:
            ServiceClient(self.host.url, 'WRONG_'+'x'*30, 'qa').identity()
        self.assertEqual(caught.exception.status, 401)
        self.host.failure = 302
        self.assertEqual(self.message()[1]['status'], 'unknown')
        self.assertEqual(self.message()[1]['status'], 'unknown')
        self.assertEqual(len(self.host.posts), 1)

    def test_wechat_approval_rejection_duplicates_stale_ticket_and_unauthorized_sender(self):
        waiting = self.message('approval', channel=WX, sender=WA)[1]
        self.assertEqual(waiting['status'], 'pending_approval')
        self.assertEqual(len(self.host.decisions), 0)
        self.assertEqual(self.decide(aid='stale')[0], 409)
        self.assertEqual(self.decide(sender=WB)[0], 403)
        success = self.decide(aid=waiting['approval_id'])
        self.assertEqual(success[1]['status'], 'completed')
        self.assertTrue(self.decide(aid=waiting['approval_id'])[1]['duplicate'])
        self.assertEqual(len(self.host.decisions), 1)
        self.assertEqual(self.decide(aid=waiting['approval_id'], did='different')[0], 409)
        rejected = self.message('reject', mid='no', channel=WX, sender=WA)[1]
        self.assertEqual(self.decide('no', action='reject', aid=rejected['approval_id'], did='no-1')[1]['status'], 'rejected')

    def test_decision_timeout_never_reapplies_and_query_can_reconcile_task_only(self):
        waiting = self.message('approval', channel=WX, sender=WA)[1]
        self.host.drop_decision = True
        self.assertEqual(self.decide(aid=waiting['approval_id'])[0], 504)
        self.assertEqual(self.decide(aid=waiting['approval_id'])[0], 504)
        self.assertEqual(self.query(channel=WX, sender=WA)[1]['status'], 'completed')
        self.assertEqual(len(self.host.decisions), 1)

    def test_inbound_authentication_binds_channel_and_separates_approval_credentials(self):
        self.assertEqual(self.adapter.authenticate('Bearer ' + ENV['QIN']), QQ)
        self.assertEqual(self.adapter.authenticate('Bearer ' + ENV['APPROVE'], True), WX)
        for key in ('QIN', 'WIN', 'QA'):
            with self.assertRaises(ChannelError):
                self.adapter.authenticate('Bearer ' + ENV[key], True)
        payload = {'channel': WX, 'sender_id': WA, 'message_id': 'forged', 'text': 'list'}
        self.assertEqual(self.adapter.dispatch('/messages', payload, QQ)[0], 403)
        forged = {'channel':QQ, 'sender_id':QA, 'message_id':'forged', 'text':'list'}
        self.assertEqual(self.adapter.dispatch('/messages', forged, WX)[0], 403)
        payload['subject'] = 'op'
        self.assertEqual(self.adapter.dispatch('/messages', payload, WX)[0], 400)
        self.assertEqual(len(self.host.posts), 0)

    def test_no_qq_operator_can_be_configured_and_credentials_cannot_be_shared(self):
        for mutate in ('approval', 'token'):
            config = deepcopy(self.config)
            if mutate == 'approval':
                config['channels'][0]['approval'] = config['channels'][1]['approval']
            else:
                config['channels'][0]['senders'][1]['token_env'] = 'QA'
            with self.assertRaises(ValueError):
                Adapter(config, self.root/'invalid', environment=ENV)

    def test_audit_counts_host_receipts_not_model_claims_or_cached_results(self):
        first = self.message()[1]
        task = self.host.tasks[first['official_task_id']]
        task.update(tools=[], result={'text':'I executed 100 tools ' + ENV['QA']})
        result = self.query()[1]
        self.assertEqual(result['audit']['successful_non_reused_receipts'], 0)
        self.assertNotIn(ENV['QA'], json.dumps(result))
        task['tools'] = [dict(receipt(), receipt_id='cached', receipt_reused=True),
                         dict(receipt(), receipt_id='read-cache', read_receipt={'reused':True}),
                         dict(receipt(), receipt_id='failed', payload={'ok':False}),
                         dict(receipt(), receipt_id='pending', payload={'ok':False,'result':{'status':'approval_required'}})]
        audit = self.query()[1]['audit']
        self.assertEqual(audit['successful_non_reused_receipts'], 0)
        self.assertEqual(audit['reused_receipts'], 2)
        raw = ''.join(row[0] for row in self.adapter.store.db.execute('SELECT data FROM audit'))
        self.assertNotIn('PRIVATE_CONTENT', raw)
        self.assertNotIn(ENV['QA'], raw)
        self.assertNotIn('arguments', raw)
        self.assertIn(first['official_task_id'], raw)

    def test_audit_storage_failure_never_returns_recorded_success(self):
        original = self.adapter.store.event
        self.adapter.store.event = lambda event: (_ for _ in ()).throw(sqlite3.OperationalError('fake disk failure'))
        with self.assertRaises(sqlite3.Error):
            self.message()
        self.adapter.store.event = original
        self.assertEqual(self.message()[1]['status'], 'unknown')
        self.assertEqual(len(self.host.posts), 1)

    def test_state_single_owner_and_configuration_changes_fail_closed(self):
        with self.assertRaises(sqlite3.Error):
            Store(self.root/'state', self.config)
        self.adapter.close()
        changed = deepcopy(self.config)
        changed['instance_id'] = 'other-environment'
        with self.assertRaises(ValueError):
            Adapter(changed, self.root/'state', environment=ENV)
        self.adapter = Adapter(self.config, self.root/'state', environment=ENV)

    def test_oversized_input_is_rejected_before_submission(self):
        self.assertEqual(self.message('x'*4097)[0], 413)
        self.assertEqual(len(self.host.posts), 0)

    def test_http_credentials_cannot_cross_channels_or_obtain_operator_privileges(self):
        server = make_server(self.adapter, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.02}, daemon=True)
        thread.start()
        try:
            message = {'channel':WX,'sender_id':WA,'message_id':'forged','text':'list'}
            qq = dict(message, channel=QQ, sender_id=QA)
            decision = {'channel':WX,'sender_id':WB,'task_id':'one','approval_id':'ticket','decision_id':'decision','decision':'approve'}
            cases = [('QIN','/messages',message,403), ('WIN','/messages',qq,403),
                     ('QIN','/tasks/decision',decision,401), ('WIN','/tasks/decision',decision,401),
                     ('APPROVE','/messages',message,401), ('APPROVE','/tasks/decision',decision,403)]
            for key, route, body, expected in cases:
                c = http.client.HTTPConnection('127.0.0.1', server.server_port)
                c.request('POST', route, json.dumps(body), {'Authorization':'Bearer '+ENV[key], 'Content-Type':'application/json'})
                response = c.getresponse()
                self.assertEqual(response.status, expected)
                response.read(); c.close()
            self.assertEqual(len(self.host.posts), 0)
        finally:
            server.shutdown(); thread.join(3); server.server_close()

    def test_http_authentication_and_live_dual_channel_bridges_use_only_mock_platforms(self):
        server = make_server(self.adapter, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.02}, daemon=True)
        thread.start()
        try:
            c = http.client.HTTPConnection('127.0.0.1', server.server_port)
            c.request('POST', '/messages', '{}', {'Content-Type':'application/json'})
            response = c.getresponse()
            self.assertEqual(response.status, 401)
            response.read(); c.close()
            scenario = {'adapter':'http://127.0.0.1:'+str(server.server_port), 'state':str(self.root/'platforms'),
                        'qkey':ENV['QIN'], 'wkey':ENV['WIN'], 'approval':ENV['APPROVE']}
            run_scenario(self, scenario)
            self.assertEqual(len(self.host.posts), 6)
            self.assertEqual(len(self.host.decisions), 2)
        finally:
            server.shutdown(); thread.join(3); server.server_close()


def run_scenario(case, scenario):
    import os
    node = shutil.which('node')
    case.assertIsNotNone(node, 'Node is required for dual-channel integration')
    env = {k:os.environ[k] for k in ('PATH','SystemRoot','WINDIR','TEMP','TMP','HOME','USERPROFILE','LANG') if k in os.environ}
    env['LP_TEST_SCENARIO'] = json.dumps(scenario)
    run = subprocess.run([node, 'tests/channel_bridge_scenario.mjs'], cwd=Path(__file__).resolve().parents[1],
                         env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
    for key in ENV.values():
        case.assertNotIn(key, run.stdout + run.stderr)
    case.assertEqual(run.returncode, 0, run.stderr)
    case.assertEqual(json.loads(run.stdout)['dual_channel'], 'PASS')
