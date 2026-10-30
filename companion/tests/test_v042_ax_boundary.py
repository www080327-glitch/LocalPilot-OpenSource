"""Validation background scope must never expand ordinary foreground consent."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from companion.config import Config
from companion.memory.store import MemoryStore
from companion.observers.events import ObservationPrivacy
from companion.observers.native import (controlled_target_descriptor, controlled_target_digest,
    native_options, filter_native_event, NativeObserver)

BUNDLE = "org.localpilot.companion.validation.axv042"
TARGET = {"pid": 123, "bundle_id": BUNDLE, "bundle_url": "/tmp/Controlled.app", "launch_time": 1234.125, "owner_pid": 99}


class ControlledObservationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp.name) / "memory.sqlite")
        self.config = Config(low_power_policy="off", localpilot_endpoint="", native_observation_enabled=True, native_ax_enabled=True,
            native_app_allowlist=(BUNDLE,), native_content_app_allowlist=(BUNDLE,))
        self.privacy = ObservationPrivacy(self.config, self.store, Mock())
        self.privacy.authorize(True)

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def event(self):
        return {"timestamp": "2026-10-11T04:00:00Z", "source": "macos.ax", "kind": "ax.snapshot",
            "object": {"bundle_id": BUNDLE, "pid": TARGET["pid"]},
            "evidence": {"nodes": [{"id": 0, "role": "AXWindow"}], "read_status": "READ_PARTIAL", "complete": False,
                "read_scope": "authorized_windows_filtered_private_inputs", "capture_scope": "controlled_owned_application",
                "target_descriptor_sha256": controlled_target_digest(TARGET)}}

    def enable(self):
        self.config.native_controlled_target = deepcopy(TARGET)
        self.privacy.authorize(True)

    def test_default_scope_does_not_change_legacy_consent(self):
        self.assertNotIn("controlled_target", self.privacy.scope_description())
        consent = self.privacy.consent_id()
        self.config.native_controlled_target = None
        self.assertEqual(consent, self.privacy.consent_id())

    def test_controlled_scope_requires_new_consent_with_all_identity_fields(self):
        self.config.native_controlled_target = deepcopy(TARGET)
        self.assertFalse(self.privacy.native_allowed())
        self.assertEqual(self.privacy.scope_description()["controlled_target"], TARGET)
        self.privacy.authorize(True)
        for key, value in (("pid", 124), ("owner_pid", 100), ("launch_time", 1234.126),
                           ("bundle_url", "/tmp/Other.app"), ("bundle_id", BUNDLE + "2")):
            old = self.config.native_controlled_target[key]
            self.config.native_controlled_target[key] = value
            self.assertFalse(self.privacy.native_allowed(), key)
            self.config.native_controlled_target[key] = old

    def test_foreground_transport_rejects_controlled_callback_forgery(self):
        raw = self.event()
        self.assertIsNone(filter_native_event(raw, native_options(self.config)))
        normalized = {**raw, "timestamp": 123.0, "source": "accessibility"}
        self.assertIsNone(self.privacy.filter_native(normalized))
        raw["evidence"].pop("capture_scope"); raw["evidence"].pop("target_descriptor_sha256")
        self.assertIsNone(filter_native_event(raw, native_options(self.config)))
        self.assertIsNone(self.privacy.filter_native({**raw, "timestamp": 123.0, "source": "accessibility"}))

    def test_controlled_event_requires_exact_scope_pid_bundle_and_digest(self):
        self.enable()
        event = self.event()
        options = native_options(self.config)
        self.assertIsNotNone(filter_native_event(event, options))
        for section, key, value in (("object", "pid", 124), ("object", "bundle_id", BUNDLE + "2"),
            ("evidence", "capture_scope", "frontmost_authorized_focused_window"),
            ("evidence", "target_descriptor_sha256", "0" * 64)):
            malformed = deepcopy(event); malformed[section][key] = value
            self.assertIsNone(filter_native_event(malformed, options))
            self.assertIsNone(self.privacy.filter_native({**malformed, "timestamp": 123.0, "source": "accessibility"}))

    def test_correct_controlled_event_keeps_provenance_without_getter_trace(self):
        self.enable(); event = self.event()
        event["evidence"]["getter_trace"] = [{"attribute": "AXRole"}]
        accepted = filter_native_event(event, native_options(self.config))
        accepted = self.privacy.filter_native(accepted)
        self.assertEqual(accepted["object"]["acquisition_scope"], self.privacy.consent_id())
        self.assertEqual(accepted["object"]["capture_scope"], "controlled_owned_application")
        self.assertEqual(accepted["evidence"]["capture_scope"], "controlled_owned_application")
        self.assertNotIn("getter_trace", accepted["evidence"])
        self.assertFalse(accepted["evidence"]["complete"])

    def test_controlled_scope_cannot_include_another_application(self):
        self.enable(); self.config.native_app_allowlist += ("org.other.app",)
        with self.assertRaises(ValueError):
            native_options(self.config)

    def test_workspace_metadata_is_also_bound_to_controlled_pid(self):
        self.enable()
        event = self.event(); event.update(source="macos.workspace", kind="app.launched")
        event["object"]["pid"] += 1
        self.assertIsNone(filter_native_event(event, native_options(self.config)))
        self.assertIsNone(self.privacy.filter_native({**event, "timestamp": 123.0, "source": "nsworkspace"}))

    def test_malformed_lifetimes_and_unowned_namespaces_rejected(self):
        for changes in ({"pid": True}, {"owner_pid": 0}, {"launch_time": float("nan")},
            {"launch_time": float("inf")}, {"bundle_id": "com.apple.TextEdit"},
            {"bundle_url": "/tmp/../App.app"}, {"bundle_url": "/tmp/App\n.app"}):
            with self.assertRaises(ValueError):
                controlled_target_descriptor({**TARGET, **changes})
        with self.assertRaises(ValueError):
            controlled_target_descriptor({**TARGET, "unexpected": True})

    def test_start_checks_owned_source_provenance_before_creating_helper(self):
        self.enable(); self.config.native_helper_path = "/synthetic/NativeObserver"
        observer = NativeObserver(self.config, Mock())
        with patch("companion.observers.native.trusted_helper", return_value=self.config.native_helper_path), \
             patch("companion.observers.native.verify_controlled_target", side_effect=ValueError("unowned app")), \
             patch("companion.observers.native.subprocess.Popen") as launch:
            self.assertEqual(observer.start()["state"], "error")
        launch.assert_not_called()

    def test_config_roundtrip_accepts_only_complete_descriptor(self):
        config = Path(self.temp.name) / "config.json"
        config.write_text(json.dumps({"native_controlled_target": TARGET, "native_app_allowlist": [BUNDLE]}))
        self.assertEqual(Config.load(config).native_controlled_target, TARGET)
        config.write_text(json.dumps({"native_controlled_target": TARGET, "native_app_allowlist": [BUNDLE, "org.other.app"]}))
        with self.assertRaises(ValueError):
            Config.load(config)

    def test_native_metrics_accumulate_reads_without_changing_callback_evidence(self):
        self.enable(); first = self.event(); second = deepcopy(first)
        first["evidence"].update(elapsed_ms=12.0, snapshot_count=1)
        second["evidence"].update(elapsed_ms=8.0, snapshot_count=2)
        callback = Mock(); observer = NativeObserver(self.config, callback)
        process = Mock(stdout=io.BytesIO((json.dumps(first) + "\n" + json.dumps(second) + "\n").encode()))
        process.poll.return_value = 0
        observer._read(process)
        self.assertEqual(observer.status()["metrics"]["total_read_ms"], 20.0)
        self.assertEqual(observer.status()["metrics"]["max_read_ms"], 12.0)
        self.assertEqual(observer.status()["metrics"]["read_state_counts"], {"READ_PARTIAL": 2})
        self.assertEqual(observer.status()["metrics"]["recent_read_ms"], [
            {"read_index": 1, "snapshot_count": 1, "elapsed_ms": 12.0, "read_status": "READ_PARTIAL"},
            {"read_index": 2, "snapshot_count": 2, "elapsed_ms": 8.0, "read_status": "READ_PARTIAL"}])
        self.assertTrue(all("elapsed_ms" not in call.args[0]["evidence"] for call in callback.call_args_list))

    def test_native_read_metrics_are_bounded_and_status_does_not_share_mutable_state(self):
        self.enable(); event = self.event(); event["evidence"]["elapsed_ms"] = 1.0
        process = Mock(stdout=io.BytesIO(((json.dumps(event) + "\n") * 300).encode()))
        process.poll.return_value = 0
        observer = NativeObserver(self.config, Mock()); observer._read(process)
        status = observer.status()["metrics"]
        self.assertEqual(len(status["recent_read_ms"]), 256)
        self.assertEqual(status["read_count"], 300)
        status["recent_read_ms"][0]["elapsed_ms"] = 999
        status["read_state_counts"]["READ_PARTIAL"] = 0
        self.assertEqual(observer.status()["metrics"]["recent_read_ms"][0]["elapsed_ms"], 1.0)
        self.assertEqual(observer.status()["metrics"]["read_state_counts"]["READ_PARTIAL"], 300)


if __name__ == "__main__":
    unittest.main()
