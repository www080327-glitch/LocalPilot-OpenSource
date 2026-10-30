"""No live user app inspection: JSON/AppKit fixtures and helper boundary tests."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import select
import unittest
from unittest.mock import Mock, patch

from companion.config import Config
from companion.observers.native import (SOURCE, NativeObserver, build_native_helper,
    filter_native_event, helper_environment, native_options, trusted_helper)


def config(**values):
    return Config(native_app_allowlist=("org.localpilot.synthetic",), **values)


def event(**values):
    result = {"timestamp": "2026-10-10T12:00:00Z", "source": "macos.ax", "kind": "ax.snapshot",
              "object": {"bundle_id": "org.localpilot.synthetic", "pid": 123},
              "evidence": {"coverage": "PARTIAL", "window_title": "Synthetic plan", "nodes": [
                  {"id": 0, "role": "AXWindow"},
                  {"id": 1, "parent": 0, "role": "AXStaticText", "text": "Synthetic project ready"}]}}
    result.update(values)
    return result


class NativeBoundaryTests(unittest.TestCase):
    def test_default_observer_is_disabled_without_process(self):
        obj = NativeObserver(Config(low_power_policy="off", localpilot_endpoint=""), Mock())
        with patch("companion.observers.native.subprocess.Popen") as create:
            self.assertEqual(obj.start()["state"], "disabled")
        create.assert_not_called()
        self.assertFalse(obj.status()["os_read_only_sandbox"])

    def test_metadata_never_includes_title_or_value(self):
        result = filter_native_event(event(), native_options(config(native_ax_enabled=True)))
        self.assertNotIn("window_title", result["evidence"])
        self.assertFalse(any("text" in n for n in result["evidence"]["nodes"]))
        self.assertIsInstance(result["timestamp"], float)
        self.assertEqual(result["source"], "accessibility")

    def test_ax_disabled_has_no_tree(self):
        result = filter_native_event(event(), native_options(config()))
        self.assertNotIn("nodes", result["evidence"])

    def test_explicit_content_keeps_only_static_text(self):
        raw = event()
        raw["evidence"]["value"] = "must not emit"
        result = filter_native_event(raw, native_options(config(native_ax_enabled=True,
                   native_content_app_allowlist=("org.localpilot.synthetic",))))
        self.assertEqual(result["evidence"]["nodes"][1]["text"], "Synthetic project ready")
        self.assertNotIn("value", result["evidence"])

    def test_secure_and_input_subtrees_are_dropped(self):
        raw = event(evidence={"nodes": [
            {"id": 0, "role": "AXWindow"},
            {"id": 1, "parent": 0, "role": "AXTextField", "subrole": "AXSecureTextField", "value": "secret"},
            {"id": 2, "parent": 1, "role": "AXStaticText", "text": "hidden"},
            {"id": 3, "parent": 2, "role": "AXStaticText", "text": "hidden child"},
            {"id": 4, "parent": 0, "role": "AXTextArea", "text": "user typing"},
            {"id": 5, "parent": 0, "role": "AXStaticText", "text": "safe"}]})
        result = filter_native_event(raw, native_options(config(native_ax_enabled=True,
                   native_content_app_allowlist=("org.localpilot.synthetic",))))
        self.assertEqual([n["id"] for n in result["evidence"]["nodes"]], [0, 5])

    def test_known_secrets_are_not_collected(self):
        raw = event(evidence={"window_title": "password: synthetic-credential", "nodes": [
            {"id": 0, "role": "AXWindow"},
            {"id": 1, "parent": 0, "role": "AXStaticText", "text": "Bearer synthetic-token"},
            {"id": 2, "parent": 0, "role": "AXStaticText", "text": "Cookie: test"}]})
        result = filter_native_event(raw, native_options(config(native_ax_enabled=True,
                   native_content_app_allowlist=("org.localpilot.synthetic",))))
        # V0.4.3 rejects a sensitive window as a target before descendants.
        self.assertIsNone(result)
        raw["evidence"]["window_title"] = "Synthetic public window"
        result = filter_native_event(raw, native_options(config(native_ax_enabled=True,
                   native_content_app_allowlist=("org.localpilot.synthetic",))))
        self.assertFalse(any("text" in n for n in result["evidence"]["nodes"]))

    def test_application_allowlist_and_exclusions(self):
        self.assertIsNone(filter_native_event(event(object={"bundle_id": "org.other.app"}), native_options(config())))
        self.assertIsNone(filter_native_event(event(), native_options(config(native_app_exclusions=("org.localpilot.synthetic",)))))

    def test_credential_app_is_denied_even_if_allowlisted(self):
        value = Config(low_power_policy="off", localpilot_endpoint="", native_app_allowlist=("com.apple.keychainaccess",))
        self.assertIsNone(filter_native_event(event(object={"bundle_id": "com.apple.keychainaccess"}), native_options(value)))

    def test_content_allowlist_cannot_extend_metadata_scope(self):
        with self.assertRaises(ValueError):
            native_options(config(native_content_app_allowlist=("org.other.app",)))

    def test_traversal_bounds_and_identifier_validation(self):
        for values in ({"native_ax_max_nodes": 513}, {"native_ax_max_depth": 17}):
            with self.assertRaises(ValueError):
                native_options(config(**values))
        with self.assertRaises(ValueError):
            native_options(Config(low_power_policy="off", localpilot_endpoint="", native_app_allowlist=("../arbitrary",)))
        result = filter_native_event(event(), native_options(config(native_ax_enabled=True, native_ax_max_nodes=1)))
        self.assertEqual(len(result["evidence"]["nodes"]), 1)

    def test_protocol_rejects_invalid_timestamp_and_source(self):
        for values in ({"timestamp": "invalid"}, {"timestamp": "2026-10-10T10:00:00"},
                       {"source": "shell"}, {"kind": "execute"}, {"evidence": "text"}):
            self.assertIsNone(filter_native_event(event(**values), native_options(config())))

    def test_dedupe_is_independent_of_clock_and_rejected_values(self):
        opts = native_options(config(native_ax_enabled=True))
        first = filter_native_event(event(), opts)
        second = filter_native_event(event(timestamp="2026-10-10T12:01:00Z"), opts)
        self.assertEqual(first["dedupe_key"], second["dedupe_key"])
        self.assertEqual(len(first["dedupe_key"]), 64)

    def test_system_state_does_not_claim_lock(self):
        value = event(source="macos.workspace", kind="session.resigned_active", object={"type": "system"},
                      evidence={"lock_state": "UNKNOWN", "session_state": "inactive"})
        result = filter_native_event(value, native_options(config()))
        self.assertEqual(result["source"], "session")
        self.assertEqual(result["evidence"]["lock_state"], "UNKNOWN")

    def test_helper_environment_does_not_inherit_tokens_or_proxies(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-secret", "HTTPS_PROXY": "synthetic-proxy"}):
            self.assertNotIn("OPENAI_API_KEY", helper_environment())
            self.assertNotIn("HTTPS_PROXY", helper_environment())

    def test_missing_helper_is_manual_required(self):
        obj = NativeObserver(config(native_observation_enabled=True), Mock())
        with patch("companion.observers.native.sys.platform", "darwin"):
            self.assertEqual(obj.start()["state"], "MANUAL_REQUIRED")

    def test_pause_does_not_restart_until_resume(self):
        obj = NativeObserver(config(native_observation_enabled=True), Mock())
        obj.pause()
        self.assertEqual(obj.start()["state"], "paused")
        self.assertEqual(obj.status()["lock_state"], "UNKNOWN")

    def test_reader_has_line_budget(self):
        obj = NativeObserver(config(), Mock())
        fake = Mock(stdout=io.BytesIO(b"x" * (128 * 1024 + 1) + b"\n"))
        obj._read(fake)
        fake.terminate.assert_called_once()
        self.assertEqual(obj.status()["state"], "error")
        obj.callback.assert_not_called()

    def test_observer_contains_no_app_control_protocol(self):
        text = SOURCE.read_text()
        for forbidden in ("AXUIElementPerformAction(", "AXUIElementSetAttributeValue(",
                          "CGEvent(", "CGEventPost(", "NSAppleScript(", ".activate(", ".launchApplication("):
            self.assertNotIn(forbidden, text)


@unittest.skipUnless(sys.platform == "darwin" and Path("/usr/bin/xcrun").exists(), "native fixture requires macOS Swift")
class CompiledNativeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = SOURCE.parents[1] / ".data"
        base.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="native-v04-", dir=base)
        cls.binary = build_native_helper(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, tree, **values):
        cfg = {"allowlist": ["org.localpilot.synthetic"], "ax_enabled": True,
               "content_allowlist": ["org.localpilot.synthetic"], "max_nodes": 80, "max_depth": 5}
        cfg.update(values)
        raw = {"config": cfg, "events": [{"bundle_id": "org.localpilot.synthetic", "tree": tree, "title": "Synthetic plan"}]}
        result = subprocess.run([self.binary, "--fixture"], input=json.dumps(raw).encode(),
                                capture_output=True, timeout=10, env=helper_environment())
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_compiled_json_fixture_does_not_emit_input_values(self):
        result = self.run_fixture({"role": "AXWindow", "children": [
            {"role": "AXTextArea", "value": "synthetic-editor-hidden", "children": [{"role": "AXStaticText", "value": "hidden-child"}]},
            {"role": "AXTextField", "subrole": "AXSecureTextField", "value": "synthetic-secure-hidden"},
            {"role": "AXStaticText", "value": "Visible synthetic project"}]})[0]
        text = json.dumps(result)
        self.assertNotIn("synthetic-editor-hidden", text)
        self.assertNotIn("synthetic-secure-hidden", text)
        self.assertNotIn("hidden-child", text)
        self.assertEqual(result["evidence"]["coverage"], "MOCK_ONLY")
        self.assertEqual(result["evidence"]["node_count"], 2)

    def test_compiled_default_metadata_only_and_allowlist(self):
        tree = {"role": "AXWindow", "children": [{"role": "AXStaticText", "value": "body"}]}
        result = self.run_fixture(tree, content_allowlist=[])[0]
        self.assertNotIn("window_title", result["evidence"])
        self.assertFalse(any("text" in n for n in result["evidence"]["nodes"]))
        self.assertEqual(self.run_fixture(tree, allowlist=[]), [])
        self.assertEqual(self.run_fixture(tree, exclusions=["org.localpilot.synthetic"]), [])

    def test_compiled_node_and_depth_budgets(self):
        result = self.run_fixture({"role": "AXWindow", "children": [{"role": "AXGroup", "children": [{"role": "AXStaticText", "value": "deep"}]}]}, max_depth=1)[0]
        self.assertEqual(result["evidence"]["node_count"], 2)
        result = self.run_fixture({"role": "AXWindow", "children": [{"role": "AXStaticText", "value": str(i)} for i in range(10)]}, max_nodes=3)[0]
        self.assertEqual(result["evidence"]["node_count"], 3)
        self.assertTrue(result["evidence"]["truncated"])

    def test_compiled_appkit_fixture_has_no_displayed_window(self):
        raw = {"config": {"allowlist": ["org.localpilot.synthetic"], "ax_enabled": True,
                           "content_allowlist": ["org.localpilot.synthetic"]}}
        result = subprocess.run([self.binary, "--fixture-snapshot"], input=json.dumps(raw).encode(),
                                capture_output=True, timeout=10, env=helper_environment())
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        text = result.stdout.decode()
        self.assertIn("Synthetic project status ready", text)
        self.assertNotIn("MUST NOT EMIT", text)
        self.assertEqual(json.loads(text)["evidence"]["fixture_origin"], "synthetic_appkit_controls")

    def test_compiled_known_credentials_are_rejected(self):
        result = self.run_fixture({"role": "AXWindow", "children": [
            {"role": "AXStaticText", "value": "api key: synthetic-token"},
            {"role": "AXStaticText", "value": "password: synthetic-secret"}]})[0]
        self.assertFalse(any("text" in n for n in result["evidence"]["nodes"]))

    def test_session_wake_cannot_clear_inactive_session(self):
        sequence = ["session.resigned_active", "system.screens_sleep", "system.will_sleep",
                    "system.did_wake", "system.screens_wake", "session.became_active"]
        result = subprocess.run([self.binary, "--fixture-session"], input=json.dumps({"events": sequence}).encode(),
                                capture_output=True, timeout=10, env=helper_environment())
        self.assertEqual(result.returncode, 0)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r["evidence"]["reason"] for r in rows], ["suspended"] * 5 + ["active"])
        self.assertTrue(all(r["evidence"]["lock_state"] == "UNKNOWN" for r in rows))

    def test_trust_rejects_changed_binary_and_wrong_manifest(self):
        self.assertEqual(trusted_helper(self.binary), self.binary)
        with tempfile.TemporaryDirectory(dir=SOURCE.parents[1] / ".data") as folder:
            binary = Path(folder) / "NativeObserver"
            binary.write_bytes(b"synthetic untrusted executable")
            binary.chmod(0o700)
            manifest = binary.with_name("NativeObserver.manifest.json")
            manifest.write_text(json.dumps({"protocol": 1, "source_sha256": "wrong", "binary_sha256": "wrong"}))
            manifest.chmod(0o600)
            with self.assertRaises(ValueError):
                trusted_helper(binary)
            binary.chmod(0o722)
            with self.assertRaises(ValueError):
                trusted_helper(binary)

    def test_arbitrary_helper_and_symlink_are_refused(self):
        with self.assertRaises(ValueError):
            trusted_helper(sys.executable)
        with tempfile.TemporaryDirectory(dir=SOURCE.parents[1] / ".data") as folder:
            linked = Path(folder) / "NativeObserver"
            linked.symlink_to(self.binary)
            with self.assertRaises(ValueError):
                trusted_helper(linked)

    def test_kernel_parent_exit_monitor_only_uses_new_synthetic_processes(self):
        import psutil
        script = """import json,os,subprocess,sys,time
child=subprocess.Popen([sys.argv[1], '--fixture-parent-watch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
child.stdin.write(json.dumps({'parent_pid':os.getpid()}).encode()); child.stdin.close()
ready=child.stdout.readline()
print(json.dumps({'helper_pid':child.pid,'ready':json.loads(ready)}),flush=True)
time.sleep(30)
"""
        parent = subprocess.Popen([sys.executable, "-c", script, self.binary], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=helper_environment())
        try:
            readable, _, _ = select.select([parent.stdout], [], [], 5)
            self.assertTrue(readable, "synthetic parent monitor was not ready")
            ready = json.loads(parent.stdout.readline())
            self.assertEqual(ready["ready"]["evidence"]["reason"], "parent_watch_ready")
            helper = psutil.Process(ready["helper_pid"])
            self.assertTrue(helper.is_running())
            parent.terminate(); parent.wait(timeout=3)
            deadline = time.monotonic() + 3
            def helper_exited():
                # Exit can race between is_running() and status(); disappearance
                # and a reaped/zombie child satisfy the original exit contract.
                try:
                    return not helper.is_running() or helper.status() == psutil.STATUS_ZOMBIE
                except psutil.NoSuchProcess:
                    return True
            while not helper_exited() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(helper_exited())
        finally:
            if parent.poll() is None:
                parent.terminate(); parent.wait(timeout=3)
            parent.stdout.close()


if __name__ == "__main__":
    unittest.main()
