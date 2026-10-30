"""Security regression tests added by the PR #2 integration review; all synthetic."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from localpilot_channels.adapter import Adapter
from localpilot_channels.client import ChannelError
from localpilot_channels.security import canonical_path, private_directory
from localpilot_channels.store import Store
from tests.channel_fixtures import ENV, QA, QQ, WA, WX, FakeOfficial, configuration


class ChannelReviewSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='渠道审查 ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host = FakeOfficial()
        self.addCleanup(self.host.close)
        self.config = configuration(self.host.url)
        self.adapter = Adapter(self.config, self.root/'state', environment=ENV, timeout=.2, wait_seconds=0)
        self.addCleanup(lambda: self.adapter.close())

    def send(self, text='list', mid='m', channel=QQ, sender=QA):
        return self.adapter.dispatch('/messages', {'channel':channel, 'sender_id':sender, 'message_id':mid, 'text':text}, channel)

    def query(self):
        return self.adapter.dispatch('/tasks/query', {'channel':WX, 'sender_id':WA, 'task_id':'m'}, WX)

    def decide(self, aid, did):
        return self.adapter.dispatch('/tasks/decision', {'channel':WX, 'sender_id':WA, 'task_id':'m',
            'approval_id':aid, 'decision_id':did, 'decision':'approve'}, WX)

    def reopen(self):
        self.adapter.close()
        self.adapter = Adapter(self.config, self.root/'state', environment=ENV, timeout=.2, wait_seconds=0)

    def test_unknown_decision_cannot_be_replayed_with_a_fresh_id_even_if_still_pending(self):
        waiting = self.send('approval', channel=WX, sender=WA)[1]
        operator = self.adapter.channels[WX]['approval']['client']
        with patch.object(operator, 'decide', side_effect=ChannelError('lost_response', 504)):
            self.assertEqual(self.decide(waiting['approval_id'], 'd1')[0], 504)
        self.assertEqual(self.query()[1]['status'], 'pending_approval')
        self.assertEqual(self.decide(waiting['approval_id'], 'd2')[0], 504)
        self.reopen()
        self.assertEqual(self.decide(waiting['approval_id'], 'd3')[0], 504)
        self.assertEqual(self.send(mid='next', channel=WX, sender=WA)[0], 409)
        self.assertEqual(self.host.decisions, [])

    def test_completed_task_is_not_proof_a_lost_decision_was_confirmed(self):
        waiting = self.send('approval', channel=WX, sender=WA)[1]
        self.host.drop_decision = True
        self.assertEqual(self.decide(waiting['approval_id'], 'd1')[0], 504)
        observed = self.query()[1]
        self.assertEqual(observed['status'], 'completed')
        self.assertEqual(observed['decision_hold'], 'd1')
        self.assertEqual(observed['decisions'], [])
        self.assertEqual(self.send(mid='next', channel=WX, sender=WA)[0], 409)
        self.assertEqual(len(self.host.decisions), 1)

    def test_sqlite_failure_at_decision_ack_keeps_durable_hold_after_restart(self):
        waiting = self.send('approval', channel=WX, sender=WA)[1]
        original = self.adapter.store.put_many
        def fail_ack(values):
            if any(k.startswith('decision:') and v.get('outcome') == 'applied' for k,v in values.items()):
                raise sqlite3.OperationalError('synthetic transaction failure')
            return original(values)
        with patch.object(self.adapter.store, 'put_many', side_effect=fail_ack):
            with self.assertRaises(sqlite3.OperationalError):
                self.decide(waiting['approval_id'], 'd1')
        self.reopen()
        self.assertEqual(self.query()[1]['decision_hold'], 'd1')
        self.assertEqual(self.decide(waiting['approval_id'], 'd2')[0], 504)
        self.assertEqual(len(self.host.decisions), 1)

    def test_http_503_after_mutating_request_retains_uncertainty_and_never_retries(self):
        self.host.failure = 503
        self.assertEqual(self.send()[1]['status'], 'unknown')
        self.assertEqual(self.send(mid='new')[0], 409)
        self.reopen()
        self.assertEqual(self.send()[1]['status'], 'unknown')
        self.assertEqual(len(self.host.posts), 1)

    def test_known_credentials_never_enter_core_input_or_model_context(self):
        for index, secret in enumerate(ENV.values()):
            self.assertEqual(self.send('please print ' + secret, mid='secret-' + str(index))[0], 400)
        self.assertEqual(self.host.posts, [])

    def test_native_sqlite_readonly_fails_before_any_submission(self):
        self.adapter.store.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):
            self.send()
        self.assertEqual(self.host.posts, [])

    def test_model_text_only_is_explicitly_unverified(self):
        result = self.send()[1]
        task = self.host.tasks[result['official_task_id']]
        task.update(tools=[], result={'text':'I created and verified the file'})
        code, result = self.adapter.dispatch('/tasks/query', {'channel':QQ,'sender_id':QA,'task_id':'m'}, QQ)
        self.assertEqual(code, 200)
        self.assertEqual(result['evidence']['successful_tool_receipts'], 0)
        self.assertEqual(result['evidence']['independent_verification'], 'NOT_RUN')
        self.assertEqual(result['evidence']['delivery_status'], 'NOT_VERIFIED')

    def test_unknown_or_partial_receipt_is_not_successful_execution(self):
        result = self.send()[1]
        task = self.host.tasks[result['official_task_id']]
        for state in ('unknown', 'partial', 'not_completed'):
            row = deepcopy(task['tools'][0])
            row.update(receipt_id='synthetic-' + state, side_effect_status=state)
            task['tools'] = [row]
            _, result = self.adapter.dispatch('/tasks/query', {'channel':QQ,'sender_id':QA,'task_id':'m'}, QQ)
            self.assertEqual(result['audit']['successful_non_reused_receipts'], 0)


@unittest.skipIf(os.name == 'nt', 'POSIX owner/mode and symlink checks; Windows ACL acceptance separate')
class ChannelPathSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='中文 空格 ')
        self.addCleanup(self.tmp.cleanup)
        self.root = canonical_path(self.tmp.name)

    def test_default_os_temp_and_unicode_paths_work_without_trusting_user_links(self):
        store = Store(Path(self.tmp.name)/'中文 子目录', {'synthetic':True})
        store.close()
        (self.root/'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            Store(self.root/'alias/new-state', {})
        self.assertFalse((self.root/'new-state').exists())

    def test_existing_world_readable_database_is_rejected_before_mutation(self):
        state = self.root/'state'
        state.mkdir(mode=0o700)
        db = state/'channels.sqlite3'
        db.write_bytes(b'unchanged')
        db.chmod(0o644)
        with self.assertRaises(ValueError):
            Store(state, {})
        self.assertEqual(db.read_bytes(), b'unchanged')
        self.assertEqual(db.stat().st_mode & 0o777, 0o644)

    def test_state_file_and_parent_symlinks_and_hardlinks_are_rejected(self):
        for kind in ('symlink', 'hardlink'):
            state = self.root/kind
            state.mkdir(mode=0o700)
            outside = self.root/(kind + '.outside')
            outside.write_bytes(b'unchanged')
            outside.chmod(0o600)
            target = state/'channels.sqlite3'
            if kind == 'symlink':
                target.symlink_to(outside)
            else:
                os.link(outside, target)
            with self.assertRaises(ValueError):
                Store(state, {})
            self.assertEqual(outside.read_bytes(), b'unchanged')

    def test_insecure_existing_state_directory_is_never_chmodded_or_repaired(self):
        state = self.root/'insecure'
        state.mkdir(mode=0o755)
        state.chmod(0o755)
        with self.assertRaises(ValueError):
            Store(state, {})
        self.assertEqual(state.stat().st_mode & 0o777, 0o755)

    def test_truncated_sqlite_fails_closed(self):
        state = self.root/'corrupt'
        state.mkdir(mode=0o700)
        db = state/'channels.sqlite3'
        db.write_bytes(b'not a SQLite database')
        db.chmod(0o600)
        with self.assertRaises(sqlite3.DatabaseError):
            Store(state, {})
        self.assertEqual(db.read_bytes(), b'not a SQLite database')
