"""Real Agent Service HTTP/SQLite with synthetic texts and a scripted model."""
import json
import time
import unittest

import companion.tests.test_v044_service as service_fixtures
from companion.escalation.provider import EscalationRequest
from companion.runtime.service import Companion


class SourceLineageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = service_fixtures.ServiceContractTests(methodName='test_result_written_to_real_sqlite_with_unverified_identity')
        self.fixture.setUp()
        from tests.test_runtime_api import Backend, answer
        self.fixture.backend = Backend(*(answer(text) for text in ('First synthetic answer', 'Inherited synthetic answer', 'Fresh synthetic answer')))
        self.app = Companion(self.fixture.config)
        self.app.controls._test_bypass = True

    def tearDown(self):
        self.app.meetings.stop()
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()
        self.fixture.tearDown()

    def source(self):
        path = self.fixture.root / 'selected.jsonl'
        path.write_text(json.dumps({'type':'transcript', 'text':'SYNTHETIC_MEETING_EVIDENCE',
            'source':'system', 'segment':'fixture-system-1', 'started_at':time.time()-2,
            'ended_at':time.time()-1, 'final':True}) + '\n')
        source = self.app.sources.connect('meeting', str(path), 'Selected synthetic meeting')['source']
        row = self.app.observation_context('SYNTHETIC_MEETING_EVIDENCE')[0]
        return source['id'], row, path

    def submit(self, rows=(), question='Explain the selected synthetic evidence.', **extra):
        request = EscalationRequest(question, 'manual', 'synthetic analysis', [], [],
            [dict(row, observation_id=row['id']) for row in rows], {'local_only':True}, '')
        pending = self.app.prepare_escalation(request)
        result = self.app.command({'command':'submit_escalation', 'approved':True,
            'expected_digest':pending['review_digest'], 'defer_monitor':True, **extra})
        if result.get('task_id'):
            self.fixture.service.wait(result['task_id'])
            result = self.app.localpilot.status(result['task_id'])
            self.app.receive_task_update(result['task_id'], result)
        return result

    def test_retrieved_sources_keep_identity_and_epistemic_through_actual_http(self):
        _, row, _ = self.source()
        result = self.submit([row])
        self.assertEqual(result['status'], 'completed')
        messages = self.fixture.backend.requests[0]['messages']
        payload = json.loads(next(message.content for message in messages if message.role == 'user' and message.content.startswith('{')))
        source = payload['source_context']['recent_events'][0]
        for key in ('id', 'source_reference', 'version_id', 'evidence_type', 'evidence_epistemic', 'evidence_digest', 'raw_state'):
            self.assertEqual(source[key], row[key])
        self.assertEqual(source['evidence_type'], 'MODEL_INFERRED')
        self.assertEqual(source['evidence_epistemic'], 'reported_unverified_text')
        self.assertEqual(source['evidence']['capture_source'], 'system')
        self.assertEqual(source['evidence']['read_status'], 'READ_SUCCESS_NONEMPTY')
        self.assertIn('fixture-system-1', source['evidence']['locator'])
        self.assertFalse(source['evidence']['completion_verified'])

    def test_revocation_starts_fresh_session_without_erasing_original_receipts(self):
        source_id, row, _ = self.source()
        first = self.submit([row])
        self.app.command({'command':'source_revoke', 'source_id':source_id})
        second = self.submit(question='Give a new answer without previous sources.')
        self.assertNotEqual(first['session_id'], second['session_id'])
        current_input = '\n'.join(message.content or '' for message in self.fixture.backend.requests[-1]['messages'])
        self.assertNotIn('SYNTHETIC_MEETING_EVIDENCE', current_input)
        self.assertNotIn('First synthetic answer', current_input)
        self.assertEqual(self.app.localpilot.status(first['task_id'])['status'], 'completed')
        self.assertIn(first['task_id'], self.app.store.get('localpilot_tasks'))
        self.assertTrue(self.app.store.db.execute("SELECT 1 FROM observation_events WHERE kind='task_result' AND task_id=?", (first['task_id'],)).fetchone())
        self.assertFalse(any(row['task_id'] == first['task_id'] for row in self.app.observation_memory.records()))

    def test_followup_result_inherits_earlier_session_source_revocation(self):
        source_id, row, _ = self.source()
        first = self.submit([row])
        second = self.submit(question='Explain the previous answer further.')
        self.assertEqual(first['session_id'], second['session_id'])
        self.assertEqual(len(self.app.observation_memory.records(kind='task_result')), 2)
        self.app.command({'command':'source_set_enabled', 'source_id':source_id, 'enabled':False})
        self.assertEqual(self.app.observation_memory.records(kind='task_result'), [])
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM observation_events WHERE kind='task_result'").fetchone()[0], 2)
        rejected = self.submit(session_id=second['session_id'])
        self.assertEqual(rejected['status'], 'unavailable')
        self.assertEqual(len(self.fixture.backend.requests), 2)

    def test_changed_file_blocks_pending_excerpt_and_old_session_reuse(self):
        _, row, path = self.source()
        first = self.submit([row])
        path.write_text('invalid replacement, no usable transcript')
        rejected = self.submit([row])
        self.assertEqual(rejected['status'], 'unavailable')
        self.assertEqual(len(self.fixture.backend.requests), 1)
        second = self.submit(question='A fresh unrelated synthetic question.')
        self.assertNotEqual(first['session_id'], second['session_id'])


if __name__ == '__main__':
    unittest.main()
