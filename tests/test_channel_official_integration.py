"""Actual official service/SQLite/Agent tools; synthetic model and platform HTTP only."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import sqlite3
from unittest.mock import patch

from localpilot_channels.adapter import Adapter
from localpilot_channels.client import ChannelError, ServiceClient
from localpilot_channels.server import make_server
from tests.channel_fixtures import ENV, QA, QQ, WA, WX, RealOfficial, configuration
from tests.test_channel_adapter import run_scenario


@unittest.skipIf(os.name == 'nt', 'Official Core imports fcntl and uses POSIX file handles; run this integration in WSL/Linux')
class OfficialChannelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.host = RealOfficial(self.root)
        self.config = configuration(self.host.url)
        self.adapter = Adapter(self.config, self.root/'channels', environment=ENV, wait_seconds=.2)

    def tearDown(self):
        self.adapter.close()
        self.host.close()
        self.tmp.cleanup()

    def send(self, text='list', mid='one', channel=QQ, sender=QA):
        return self.adapter.dispatch('/messages', {'channel':channel,'sender_id':sender,'message_id':mid,'text':text}, channel)

    def done(self, mid='one', channel=QQ, sender=QA):
        result = None
        for _ in range(100):
            code, result = self.adapter.dispatch('/tasks/query', {'channel':channel,'sender_id':sender,'task_id':mid}, channel)
            if result['status'] != 'processing':
                return code, result
            time.sleep(.02)
        self.fail('scripted official task did not settle')

    def decide(self, aid, did='yes', mid='one'):
        return self.adapter.dispatch('/tasks/decision', {'channel':WX,'sender_id':WA,'task_id':mid,
            'approval_id':aid,'decision_id':did,'decision':'approve'}, WX)

    def test_real_tools_and_both_node_bridges_with_synthetic_platform_http(self):
        server = make_server(self.adapter, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.02}, daemon=True)
        thread.start()
        try:
            run_scenario(self, {'adapter':'http://127.0.0.1:'+str(server.server_port),'state':str(self.root/'platforms'),
                               'qkey':ENV['QIN'],'wkey':ENV['WIN'],'approval':ENV['APPROVE']})
            self.assertEqual(self.host.executions.count('list_directory'), 4)
            self.assertEqual((self.host.workspace/'approved.txt').read_text(), 'OK')
            self.assertFalse((self.host.workspace/'rejected.txt').exists())
            rows = self.adapter.store.db.execute("SELECT data FROM audit WHERE data LIKE '%official_tool_receipt_observed%'").fetchall()
            self.assertEqual(len(rows), 6)  # Four reads, an approved patch and a denied patch receipt.
            self.assertNotIn('PRIVATE_CONTENT', str(rows))
        finally:
            server.shutdown(); thread.join(3); server.server_close()

    def test_official_sqlite_and_channel_mapping_survive_service_and_adapter_restart(self):
        self.send()
        first = self.done()[1]
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(first['audit']['successful_non_reused_receipts'], 1)
        port = self.host.server.server_port
        self.adapter.close()
        self.host.stop()
        self.host.start(port)
        self.adapter = Adapter(self.config, self.root/'channels', environment=ENV, wait_seconds=0)
        same = self.send()[1]
        self.assertEqual(same['official_task_id'], first['official_task_id'])
        self.assertEqual(same['session_id'], first['session_id'])
        self.assertEqual(self.host.executions, ['list_directory'])

    def test_restarted_approval_uses_fresh_action_id_and_ordinary_client_cannot_approve(self):
        self.send('approval', channel=WX, sender=WA)
        waiting = self.done(channel=WX, sender=WA)[1]
        self.assertEqual(waiting['status'], 'pending_approval')
        self.assertFalse((self.host.workspace/'approved.txt').exists())
        with self.assertRaises(ChannelError) as caught:
            ServiceClient(self.host.url, ENV['WA'], 'wa').decide(waiting['official_task_id'], 'approve', waiting['approval_id'], '')
        self.assertEqual(caught.exception.status, 403)
        with self.assertRaises(ChannelError) as caught:
            ServiceClient(self.host.url, ENV['QA'], 'qa').task(waiting['official_task_id'])
        self.assertEqual(caught.exception.status, 404)
        port = self.host.server.server_port
        self.host.stop(); self.host.start(port)
        current = self.done(channel=WX, sender=WA)[1]
        self.assertNotEqual(current['approval_id'], waiting['approval_id'])
        self.assertEqual(self.decide(waiting['approval_id'])[0], 409)
        self.assertFalse((self.host.workspace/'approved.txt').exists())
        self.decide(current['approval_id'], 'fresh')
        done = self.done(channel=WX, sender=WA)[1]
        self.assertEqual(done['status'], 'completed')
        self.assertEqual((self.host.workspace/'approved.txt').read_text(), 'OK')
        self.assertEqual(done['audit']['successful_non_reused_receipts'], 1)

    def test_official_idempotency_conflict_cannot_execute_a_second_task(self):
        client = ServiceClient(self.host.url, ENV['QA'], 'qa')
        first = client.submit({'input':'list'}, 'stable-key')
        self.host.service.wait(first['id'])
        duplicate = client.submit({'input':'list'}, 'stable-key')
        self.assertEqual(first['id'], duplicate['id'])
        with self.assertRaises(ChannelError) as caught:
            client.submit({'input':'changed'}, 'stable-key')
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.host.executions, ['list_directory'])

    def test_native_sqlite_receipt_write_failure_quarantines_without_replaying_real_tool(self):
        client = self.adapter.bindings[(QQ, QA)]['client']
        original = client.submit
        def accepted_then_readonly(*args):
            task = original(*args)
            self.host.service.wait(task['id'])
            self.adapter.store.db.execute('PRAGMA query_only=ON')
            return task
        with patch.object(client, 'submit', side_effect=accepted_then_readonly):
            with self.assertRaises(sqlite3.OperationalError):
                self.send()
        self.assertEqual(self.host.executions, ['list_directory'])
        self.adapter.close()
        self.adapter = Adapter(self.config, self.root/'channels', environment=ENV, wait_seconds=0)
        self.assertEqual(self.send()[1]['status'], 'unknown')
        self.assertEqual(self.send(mid='must-not-run')[0], 409)
        self.assertEqual(self.host.executions, ['list_directory'])

    def test_expired_approval_cannot_write_or_accept_old_action(self):
        client = ServiceClient(self.host.url, ENV['WA'], 'wa')
        task = client.submit({'input':'approval', 'model':'localpilot', 'timeout_seconds':1}, 'expiry-test')
        waiting = self.host.service.wait(task['id'])
        self.assertEqual(waiting['status'], 'requires_approval')
        aid = waiting['required_action']['id']
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            ended = client.task(task['id'])
            if ended['status'] == 'timed_out' and ended['quiescent']:
                break
            time.sleep(.02)
        self.assertEqual(ended['status'], 'timed_out')
        with self.assertRaises(ChannelError) as caught:
            ServiceClient(self.host.url, ENV['OP'], 'op').decide(task['id'], 'approve', aid, '')
        self.assertEqual(caught.exception.status, 409)
        self.assertFalse((self.host.workspace/'approved.txt').exists())
