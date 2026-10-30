import json
from pathlib import Path
import tempfile
import time
import unittest

from companion.config import Config
from companion.runtime.service import Companion
from companion.triggers.workflow import WorkflowSignals


class PresenceContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(Path(self.temp.name).resolve()/"state"), backend="disabled",
            quiet_start_hour=0, quiet_end_hour=0, native_observation_enabled=True, native_ax_enabled=True,
            native_all_apps_enabled=True, native_all_apps_content_enabled=True, native_ax_max_nodes=512, native_ax_max_depth=16))
        self.app.privacy.authorize(confirmed=True)

    def tearDown(self):
        self.app.native.stop(); self.app.observer.stop(); self.app.model.unload(); self.app.channel.stop()
        self.app.store.close(); self.app.lock.close(); self.temp.cleanup()

    def raw(self):
        nodes = [{"id":0,"role":"AXWindow"}] + [{"id":i,"parent":0,"role":"AXButton"} for i in range(1,100)]
        nodes += [{"id":100,"parent":0,"role":"AXGroup"}, {"id":101,"parent":100,"role":"AXStaticText","text":"Synthetic document body. "*15},
                  {"id":102,"parent":0,"role":"AXTextField","text":"PRIVATE_INPUT"}, {"id":103,"parent":102,"role":"AXStaticText","text":"PRIVATE_INPUT_CHILD"}]
        return {
                "timestamp":time.time(), "source":"accessibility", "kind":"ax.snapshot", "object":{"bundle_id":"com.google.Chrome"},
                "evidence":{"nodes":nodes,"read_status":"READ_SUCCESS_NONEMPTY","window_title":"Synthetic document"}}

    def test_late_body_survives_storage_budget_without_private_descendants(self):
        event = self.app.privacy.filter_native(self.raw())
        self.assertLessEqual(len(event["evidence"]["nodes"]),64)
        self.assertLessEqual(len(json.dumps(event["evidence"],ensure_ascii=False).encode()),8192)
        self.assertIn(101,[n["id"] for n in event["evidence"]["nodes"]])
        self.assertNotIn("PRIVATE_INPUT",json.dumps(event))
        self.assertEqual(event["evidence"]["read_status"],"READ_PARTIAL")
        stored = self.app.observation_memory.add(event)
        self.assertEqual(stored["evidence_type"],"OBSERVED")
        card = self.app.visible_context()[0]
        self.assertIn("Synthetic document body",card["text"])
        self.assertEqual(card["app"],"Chrome")
        self.assertNotIn("UNKNOWN",card["text"])

    def test_context_view_and_review_recheck_revoked_permission(self):
        self.app.observation_memory.add(self.app.privacy.filter_native(self.raw()))
        self.assertTrue(self.app.command({"command":"current_context"})["cards"])
        self.app.store.set("native_observation_consent", "revoked")
        self.assertEqual(self.app.command({"command":"current_context"})["cards"],[])
        self.assertEqual(self.app.command({"command":"review_context"})["model"]["status"],"not_called")

    def test_late_text_survives_actual_callback_queue_and_final_storage(self):
        self.app.enqueue_native(self.raw())
        kind,event,_ = self.app.queue.get_nowait()
        self.assertEqual(kind,"native")
        self.app.process_native(event)
        self.assertIn("Synthetic document body",self.app.visible_context()[0]["text"])
        self.assertNotIn("PRIVATE_INPUT",json.dumps(self.app.visible_context()))

    def test_high_frequency_notifications_do_not_evict_sustained_evidence(self):
        tracker=WorkflowSignals();event=self.app.privacy.filter_native(self.raw());start=time.time();offers=[]
        for n in range(401):
            event["timestamp"]=start+n*2
            result=tracker.accept(event,"same-row")
            if result:offers.append(result)
        self.assertTrue(offers)
        self.assertEqual(offers[0]["kind"],"context_review")
        self.assertLess(len(tracker.events),100)

    def test_plain_context_does_not_create_confirmed_user_facts_or_call_model(self):
        self.app.observation_memory.add(self.app.privacy.filter_native(self.raw()))
        self.app.command({"command":"ui_snapshot"})
        self.assertEqual(self.app.store.records(10,["user_fact","preference"]),[])
        self.assertEqual(self.app.model.inferences,0)

    def test_review_returns_only_selected_source_ids_with_partial_read(self):
        from unittest.mock import patch
        row=self.app.observation_memory.add(self.app.privacy.filter_native(self.raw()))
        with patch.object(self.app.inference,'complete',return_value={"status":"ok", "text":"这是合成窗口文字整理，读取不完整。", "routing":{"level":2}}):
            result=self.app.command({"command":"review_context"})
        self.assertEqual(result["status"], "escalation")
        events = self.app.store.get("pending_escalation")["recent_events"]
        self.assertEqual([r["id"] for r in events], [row["id"]])
        self.assertEqual(events[0]["evidence_type"], "OBSERVED")
        self.assertEqual(events[0]["evidence"]["read_status"], "READ_PARTIAL")
        self.assertEqual(self.app.store.records(10,["user_fact"]),[])

    def test_pause_during_review_withholds_reply_and_source_excerpt(self):
        from unittest.mock import patch
        self.app.observation_memory.add(self.app.privacy.filter_native(self.raw()))
        self.app.observation_pause_requested.set()
        def finish(*args,**kwargs):
            raise AssertionError("Paused source must not enter inference")
            return {"status":"ok", "text":"Synthetic private answer"}
        with patch.object(self.app.inference,'complete',side_effect=finish):
            result=self.app.command({"command":"review_context"})
        self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('Synthetic',json.dumps(result))
        self.assertNotIn('observation_sources',result)
        self.assertFalse([r for r in self.app.store.records(10,["conversation"]) if r['source']=='companion_model'])

    def test_single_merged_window_can_offer_help_without_model_or_agent(self):
        tracker=WorkflowSignals(); now=time.time()
        event=self.app.privacy.filter_native(self.raw())
        for offset in [0,310,620]:
            event["timestamp"]=now+offset
            result=tracker.accept(event,"merged-row")
        self.assertEqual(result["context_count"],1)
        decision=self.app.consider_event(result,now)
        self.assertEqual(decision["action"],"ask-help")
        self.assertEqual(decision["origin"],"host_evidence")
        self.assertEqual(self.app.model.inferences,0)
        self.assertIsNone(self.app.store.get("pending_escalation"))
        self.assertEqual(self.app.consider_event(result,now+1)["origin"],"daily_context_offer_limit")

    def test_replayed_timestamp_does_not_establish_duration(self):
        tracker=WorkflowSignals(); event=self.app.privacy.filter_native(self.raw())
        for _ in range(5): self.assertIsNone(tracker.accept(event,"same-row"))
        tracker.reset()
        for offset in [0,700,1400]:
            event["timestamp"]=time.time()+offset
            self.assertIsNone(tracker.accept(event,"same-row"))


if __name__ == "__main__": unittest.main()
