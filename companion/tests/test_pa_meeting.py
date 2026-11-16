from concurrent.futures import Future
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from companion.config import Config
from companion.observers.meeting import parse_message
from companion.runtime.service import Companion


class MeetingControllerTests(unittest.TestCase):
    """The process boundary is real; the fixture emits text, never captures audio."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.config = Config(data_dir=str(self.root / "state"), backend="disabled", localpilot_endpoint="", low_power_policy="off")
        self.app = Companion(self.config)

    def close_app(self):
        self.app.meetings.stop()
        self.app.native.stop()
        self.app.observer.stop()
        self.app.model.unload()
        self.app.channel.stop()
        self.app.store.close()
        self.app.lock.close()

    def tearDown(self):
        self.close_app()
        self.temp.cleanup()

    def helper(self, messages=(), final=(), terminal="stopped", wait=True, exit_code=None):
        path = self.root / ("fixture-"+str(time.monotonic_ns()))
        content = f"""#!{sys.executable}
import json, sys, time, uuid
uuid.UUID(sys.argv[sys.argv.index('--session')+1])
def emit(value):
    print(json.dumps(value), flush=True)
emit({{'type':'status','state':'recording','detail':'fixture_only','source':'all','at':time.time()}})
for row in {list(messages)!r}: emit(row)
if {wait!r}:
    for line in sys.stdin:
        if line.strip() == 'stop': break
for row in {list(final)!r}: emit(row)
if {terminal is not None!r}: emit({{'type':'status','state':{terminal!r},'detail':'fixture_terminal','source':'all','at':time.time()}})
sys.exit({exit_code if exit_code is not None else 0 if terminal == 'stopped' else 1})
"""
        path.write_text(content)
        path.chmod(0o700)
        return path

    def segment(self, text, source="mic", segment="segment-1", final=True):
        return {"type":"transcript", "text":text, "source":source, "segment":segment,
                "started_at":time.time()-1, "ended_at":time.time(), "final":final}

    def start(self, helper, capture="both"):
        def launcher(config, selected, locale, session, private):
            return [str(helper), '--session', session], None, {}
        with patch("companion.observers.meeting.meeting_launch", side_effect=launcher):
            return self.app.command({"command":"meeting_start", "capture":capture, "label":"Synthetic meeting"})

    def until(self, condition):
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            self.app.meetings.drain()
            if condition():
                return
            time.sleep(.01)
        self.fail("Meeting process condition was not reached: " + json.dumps(self.app.meetings.status()))

    def test_default_does_not_build_start_or_capture(self):
        result = self.app.command({"command":"meeting_status"})
        self.assertEqual(result["meeting"]["state"], "idle")
        self.assertIsNone(self.app.meetings.process)
        self.assertFalse((self.root / "state" / "meetings").exists())
        self.assertEqual(self.app.sources.list()["sources"], [])

    @unittest.skipIf(sys.platform == "darwin", "Do not request actual OS permissions in the portable suite")
    def test_unconfigured_linux_explicit_start_is_unavailable_without_source_or_process(self):
        result = self.app.command({"command":"meeting_start", "capture":"both"})
        self.assertEqual(result["status"], "unavailable")
        self.assertIn('linux_meeting_requires:' if sys.platform.startswith('linux') else 'macos_required', result['meeting']['detail'])
        self.assertIsNone(self.app.meetings.process)
        self.assertEqual(self.app.sources.list()["sources"], [])

    def test_two_audio_sources_create_reported_text_and_stop_flushes_final(self):
        helper = self.helper([self.segment("Synthetic microphone phrase"), self.segment("Synthetic system phrase", "system", "system-1")],
                             [self.segment("Synthetic final phrase", segment="mic-2")])
        result = self.start(helper)
        self.assertEqual(result["status"], "active")
        self.until(lambda:self.app.meetings.state["segments"] == 2)
        process = self.app.meetings.process
        answer = self.app.ask("会议说了什么？")
        self.assertEqual(len(answer["items"]), 2)
        self.assertTrue(all(row["evidence_type"] == "MODEL_INFERRED" for row in answer["items"]))
        self.assertEqual({row["role"] for row in answer["items"]}, {"automatic_transcript:mic", "automatic_transcript:system"})
        stopped = self.app.command({"command":"meeting_stop"})
        self.assertEqual(stopped["meeting"]["state"], "stopped")
        self.assertEqual(process.poll(), 0)
        self.assertIsNone(self.app.meetings.process)
        self.assertEqual(stopped["meeting"]["segments"], 3)
        self.assertIn("Synthetic final phrase", self.app.ask("会议说了什么？")["text"])
        self.assertEqual(len(list(self.app.meetings.output.root.glob('segment-*.jsonl'))), 3)
        self.assertEqual(len(list(self.app.meetings.output.root.iterdir())), 4)
        self.assertIn('ended_at', stopped['meeting'])
        self.assertFalse(stopped["meeting"]["raw_audio_saved"])
        self.assertFalse(stopped["meeting"]["cloud_fallback"])
        self.assertEqual(self.app.model.inferences, 0)
        self.assertEqual(self.app.localpilot.network_calls, 0)

    def test_start_is_idempotent_while_active_and_repeated_segments_are_not_persisted_twice(self):
        event = self.segment("Repeated synthetic phrase")
        helper = self.helper([event, event])
        first = self.start(helper)
        self.until(lambda:self.app.meetings.state["segments"] == 1)
        process = self.app.meetings.process
        again = self.start(helper)
        self.assertEqual(first["meeting"]["session_id"], again["meeting"]["session_id"])
        self.assertIs(process, self.app.meetings.process)
        self.assertEqual(len(list(self.app.meetings.output.root.glob('segment-*.jsonl'))), 1)

    def test_stop_request_reaches_process_before_the_service_queue_is_serviced(self):
        self.start(self.helper())
        self.until(lambda:self.app.meetings.state["state"] == "recording")
        process = self.app.meetings.process
        future = Future()
        self.app.enqueue_command({"command":"meeting_stop"}, future)
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertFalse(future.done())
        self.app.command({"command":"meeting_stop"})
        self.assertEqual(self.app.meetings.state["state"], "stopped")

    def test_permission_denied_stays_denied_and_does_not_fall_back(self):
        result = self.start(self.helper(terminal="denied", wait=False))
        self.until(lambda:self.app.meetings.state.get("exit_code") == 1)
        self.assertEqual(self.app.meetings.state["state"], "denied")
        self.assertEqual(self.app.meetings.state["capture"], "both")
        self.assertEqual(self.app.observation_memory.records(), [])
        self.assertEqual(self.app.meetings.state["segments"], 0)

    def test_invalid_partial_protocol_stops_and_does_not_store_text(self):
        self.start(self.helper([self.segment("MUST_NOT_BE_PERSISTED", final=False)]))
        self.until(lambda:self.app.meetings.state.get("exit_code") == 0)
        self.assertEqual(self.app.meetings.state["state"], "failed")
        self.assertEqual(self.app.meetings.state["detail"], "invalid_helper_protocol")
        self.assertEqual(self.app.meetings.state["segments"], 0)
        self.assertNotIn("MUST_NOT_BE_PERSISTED", "\n".join(self.app.store.db.iterdump()))
        self.assertEqual(list(self.app.meetings.output.root.glob('*.jsonl')), [])

    def test_pause_stops_capture_and_discards_pending_final_without_resuming_on_unpause(self):
        self.start(self.helper(final=[self.segment("DISCARDED_ON_PAUSE")]))
        self.until(lambda:self.app.meetings.state["state"] == "recording")
        process = self.app.meetings.process
        self.app.command({"command":"pause_observation", "paused":True})
        self.assertEqual(process.poll(), 0)
        self.assertEqual(self.app.meetings.state["segments"], 0)
        self.assertEqual(list(self.app.meetings.output.root.glob('*.jsonl')), [])
        self.app.command({"command":"pause_observation", "paused":False})
        self.assertIsNone(self.app.meetings.process)

    def test_later_segments_keep_prior_sources_and_reviewed_examples_current(self):
        helper = self.helper([self.segment('First immutable segment')],
                             [self.segment('Second immutable segment', segment='segment-2')])
        self.start(helper)
        self.until(lambda:self.app.meetings.state['segments'] == 1)
        prior = self.app.observation_memory.records(kind='imported.meeting')[0]
        self.app.training.add('第一段写了什么？', '来源写了 First immutable segment。', 'activity_qa', [prior['id']])
        self.app.meetings.stop()
        self.assertTrue(self.app.observation_memory.is_current(prior['id']))
        self.assertTrue(self.app.training.list()['examples'][0]['available'])
        self.assertEqual(self.app.store.db.execute('SELECT count(*) FROM observation_events').fetchone()[0], 2)
        self.assertEqual(self.app.store.db.execute('SELECT count(*) FROM observation_versions').fetchone()[0], 2)
        self.assertEqual(self.app.meetings.state['last_sync']['files'], 1)

    def test_long_protocol_run_has_linear_records_and_never_truncates_prior_segments(self):
        segments = [self.segment(f'Synthetic segment {n}', segment=f'mic-{n}') for n in range(80)]
        self.start(self.helper(segments))
        self.until(lambda:self.app.meetings.state['segments'] == len(segments))
        self.app.meetings.stop()
        self.assertEqual(self.app.store.db.execute('SELECT count(*) FROM observation_events').fetchone()[0], 80)
        self.assertEqual(self.app.store.db.execute('SELECT count(*) FROM observation_versions').fetchone()[0], 80)
        self.assertEqual(len(self.app.observation_memory.records(limit=100, kind='imported.meeting')), 80)
        self.assertEqual(self.app.meetings.state['last_sync']['files'], 1)
        self.assertEqual(self.app.meetings.state['state'], 'stopped')

    def test_process_exit_must_agree_with_terminal_state(self):
        for terminal in (False, True):
            with self.subTest(terminal=terminal):
                helper = self.helper(wait=False, terminal='stopped' if terminal else None, exit_code=3 if terminal else 0)
                self.start(helper)
                self.until(lambda:self.app.meetings.state.get('exit_code') is not None)
                self.assertEqual(self.app.meetings.state['state'], 'failed')
                self.assertEqual(self.app.meetings.state['detail'], 'helper_exit_nonzero' if terminal else 'helper_exited_without_terminal_status')

    def test_disabling_or_revoking_current_source_stops_its_process(self):
        for command in ("source_set_enabled", "source_revoke"):
            with self.subTest(command=command):
                self.start(self.helper([self.segment("Synthetic granted text")]))
                self.until(lambda:self.app.meetings.state["segments"] == 1)
                process = self.app.meetings.process
                source_id = self.app.meetings.state["source_id"]
                self.app.command({"command":command, "source_id":source_id, "enabled":False})
                self.assertEqual(process.poll(), 0)
                self.assertEqual(self.app.observation_memory.records(), [])

    def test_clear_removes_owned_transcript_and_leaves_external_file_unchanged(self):
        external = self.root / "external.txt"
        external.write_text("User-owned transcript")
        self.app.sources.connect("meeting", str(external))
        self.start(self.helper([self.segment("Synthetic owned transcript")]))
        self.until(lambda:self.app.meetings.state["segments"] == 1)
        self.app.command({"command":"clear", "confirmation":"DELETE_COMPANION_MEMORY"})
        self.assertEqual(self.app.meetings.state["state"], "idle")
        self.assertFalse((self.root / "state" / "meetings").exists())
        self.assertEqual(external.read_text(), "User-owned transcript")

    def test_restart_reconciles_recording_state_without_starting_a_process(self):
        self.app.store.set("meeting_capture", {"state":"recording", "segments":4, "sources":{}, "session_id":"prior"})
        self.close_app()
        self.app = Companion(self.config)
        self.assertEqual(self.app.meetings.state["state"], "interrupted")
        self.assertEqual(self.app.meetings.state["segments"], 4)
        self.assertIsNone(self.app.meetings.process)

    def test_protocol_rejects_incomplete_or_nonfinite_timestamps_and_redacts_credentials(self):
        event = self.segment("api_key=sk-abcdefghijklmn")
        parsed = parse_message((json.dumps(event)+"\n").encode())
        self.assertNotIn("sk-", parsed["text"])
        for broken in (event | {"ended_at":float("nan")}, event | {"source":"camera"}, {k:v for k,v in event.items() if k != "started_at"}):
            with self.assertRaises(ValueError):
                parse_message((json.dumps(broken)+"\n").encode())
        with self.assertRaises(ValueError):
            parse_message(b"x"*32769)


if __name__ == "__main__":
    unittest.main()
