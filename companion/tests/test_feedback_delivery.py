import json
from pathlib import Path
import tempfile
import time
import unittest
from companion.config import Config
from companion.runtime.service import Companion
from companion.triggers.policy import expire_notices
from companion.observers.native import native_options, app_scope_allowed, content_scope_allowed, filter_native_event


class FeedbackDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Companion(Config(low_power_policy="off", localpilot_endpoint="", data_dir=str(Path(self.temp.name).resolve()/"state"), backend="disabled",
            quiet_start_hour=0,quiet_end_hour=0))
    def tearDown(self):
        self.app.native.stop();self.app.observer.stop();self.app.model.unload();self.app.channel.stop()
        self.app.store.close();self.app.lock.close();self.temp.cleanup()
    def test_invisible_queue_expiry_never_counts_negative_feedback(self):
        for mode in ("popup_available","silent_evaluation","submitted_visibility_unverified"):
            self.app.policy.record("project_help",mode,"fixture",delivery=mode,now=time.time()-7200)
        expire_notices(self.app.store)
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices WHERE status='expired_unseen'").fetchone()[0],3)
        self.assertEqual(self.app.store.get("notice_feedback",{}),{})
        self.assertEqual(self.app.store.get("runtime_totals",{}).get("ignored",0),0)
    def test_presentation_receipt_is_separate_from_positive_feedback(self):
        nid=self.app.policy.record("project_help","fixture","fixture",now=time.time()-1)
        self.app.command({"command":"notice_presented","id":nid,"channel":"native_banner"})
        row=self.app.store.db.execute("SELECT * FROM notices WHERE id=?",(nid,)).fetchone()
        self.assertEqual(row["delivery"],"displayed_native_banner")
        self.assertIn(nid,self.app.store.get("notice_presented_times"))
        self.assertIsNone(self.app.policy.summary()["useful_rate"])
        self.app.command({"command":"notice_presented","id":nid,"channel":"native_banner"})
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices").fetchone()[0],1)
    def test_invalid_presentation_channel_does_not_upgrade_delivery(self):
        nid=self.app.policy.record("greeting","f","fixture")
        with self.assertRaises(ValueError):self.app.command({"command":"notice_presented","id":nid,"channel":"arbitrary"})
        self.assertEqual(self.app.store.db.execute("SELECT delivery FROM notices WHERE id=?",(nid,)).fetchone()[0],"popup_available")
    def test_health_does_not_call_configured_but_idle_observer_complete(self):
        report=self.app.feedback_health()
        self.assertEqual(report["ax_reads"],0)
        self.assertIn("原生观察范围尚未确认",report["blockers"])
        self.assertIn("未设置文件观察目录",report["blockers"])
        self.assertFalse(report["localpilot_available"])
    def test_manual_feedback_check_is_not_a_work_fact_or_model_call(self):
        reply=self.app.command({"command":"feedback_check"})
        self.assertTrue(reply["manual_check"])
        self.assertEqual(self.app.model.inferences,0)
        self.assertEqual(self.app.store.records(10,["user_fact"]),[])
        self.assertEqual(self.app.store.db.execute("SELECT count(*) FROM notices").fetchone()[0],0)
    def test_all_app_scope_still_preserves_exclusions_secrets_and_self(self):
        c=Config(low_power_policy="off", localpilot_endpoint="", native_all_apps_enabled=True,native_all_apps_content_enabled=True,native_ax_enabled=True,
            native_app_exclusions=("com.example.Excluded",))
        opt=native_options(c)
        self.assertTrue(app_scope_allowed("com.example.NewApp",opt))
        self.assertTrue(content_scope_allowed("com.example.NewApp",opt))
        for bundle in ["com.example.Excluded","com.1password.1password","io.localpilot.companion.ui","not a bundle"]:
            self.assertFalse(app_scope_allowed(bundle,opt))
    def test_all_app_permission_change_invalidates_old_consent(self):
        self.app.command({"command":"authorize_observation","confirmed":True})
        old=self.app.privacy.consent_id()
        self.app.config.native_all_apps_enabled=True
        self.app.config.native_observation_enabled=True
        self.assertNotEqual(old,self.app.privacy.consent_id())
        self.assertFalse(self.app.privacy.native_allowed())
    def test_all_content_requires_explicit_all_app_configuration(self):
        with self.assertRaises(ValueError):native_options(Config(low_power_policy="off", localpilot_endpoint="", native_all_apps_content_enabled=True))
    def test_recently_presented_old_notice_has_full_feedback_window(self):
        nid=self.app.policy.record("deadline","old","fixture",now=time.time()-3500)
        self.app.command({"command":"notice_presented","id":nid,"channel":"native_banner"})
        expire_notices(self.app.store, time.time()+200)
        self.assertEqual(self.app.store.db.execute("SELECT status FROM notices WHERE id=?",(nid,)).fetchone()[0],"pending")
    def test_context_offer_needs_actual_static_text_and_duration(self):
        from companion.triggers.workflow import WorkflowSignals
        tracker=WorkflowSignals()
        start=time.time()
        for n,title in enumerate(["first","second","first"]):
            event={"kind":"ax.snapshot","timestamp":start+n*310,"object":{"bundle_id":"com.example.NewApp"},
                "evidence":{"window_title":title,"nodes":[{"role":"AXStaticText","text":("synthetic ordinary document context "+str(n))*4}]}}
            result=tracker.accept(event,str(n))
        self.assertEqual(result["kind"],"context_review")
        self.assertEqual(result["context_count"],2)
        self.assertNotIn("same_error", result)
        empty=WorkflowSignals()
        for n in range(6):
            self.assertIsNone(empty.accept({"kind":"app.activated","timestamp":start+n*180,
                "object":{"bundle_id":"com.example.NewApp"},"evidence":{"window_title":"metadata only"}},str(n)))
    def test_chat_does_not_promise_an_unsaved_reminder(self):
        result=self.app.ask("提醒我明天检查项目")
        self.assertEqual(result["status"],"reminder_setup_required")
        self.assertEqual(self.app.model.inferences,0)
        self.assertEqual(self.app.store.get("explicit_reminders",[]),[])


if __name__=='__main__':unittest.main()
