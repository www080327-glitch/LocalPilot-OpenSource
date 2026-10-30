"""V0.4.1 isolated observer regressions; only synthetic providers/processes."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from companion.config import Config
from companion.memory.store import MemoryStore
from companion.observers.events import ObservationPrivacy
from companion.observers.native import (
    SOURCE, SHARED_CORE, SHARED_FILES, HelperRebuildRequired, NativeObserver,
    build_native_helper, filter_native_event, helper_environment, native_options,
    shared_core_manifest, trusted_helper,
)


BUNDLE = "org.localpilot.synthetic"
MARKER = "SYNTHETIC_PRIVATE_MARKER_041"


def config(**values):
    defaults = {"native_observation_enabled": True, "native_ax_enabled": True,
                "native_app_allowlist": (BUNDLE,), "native_content_app_allowlist": (BUNDLE,)}
    defaults.update(values)
    return Config(**defaults)


def raw_event(nodes, **evidence):
    return {"timestamp": "2026-10-11T12:00:00Z", "source": "macos.ax", "kind": "ax.snapshot",
            "object": {"bundle_id": BUNDLE, "pid": 123},
            "evidence": {"nodes": nodes, **evidence}}


class ObserverBoundaryV041Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp.name) / "memory.sqlite")
        self.config = config()
        self.privacy = ObservationPrivacy(self.config, self.store, Mock(allowed=lambda _: True))
        self.privacy.authorize(True)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def pipeline(self, event):
        accepted = filter_native_event(event, native_options(self.config))
        return self.privacy.filter_native(accepted) if accepted else None

    def test_secure_role_only_and_nested_descendants_are_removed_at_both_boundaries(self):
        event = raw_event([
            {"id": 0, "role": "AXWindow"},
            {"id": 1, "parent": 0, "role": "AXSecureTextField", "title": MARKER},
            {"id": 2, "parent": 1, "role": "AXStaticText", "text": MARKER},
            {"id": 3, "parent": 2, "role": "AXStaticText", "text": MARKER},
            {"id": 4, "parent": 0, "role": "AXStaticText", "text": "safe"},
        ])
        output = self.pipeline(event)
        self.assertNotIn(MARKER, json.dumps(output))
        self.assertEqual([n["id"] for n in output["evidence"]["nodes"]], [0, 4])
        # Exercise the second boundary independently of native.py sanitization.
        normalized = {**event, "source": "accessibility", "timestamp": 1.0}
        output = self.privacy.filter_native(normalized)
        self.assertNotIn(MARKER, json.dumps(output))

    def test_malformed_and_unknown_roles_fail_closed_without_exception(self):
        for changes in ({"role": "AXUnknown"}, {"role": []}, {"role": "malformed"},
                        {"role": "AXGroup", "subrole": []}, {"role": "AXGroup", "subrole": "bad"}):
            nodes = [{"id": 0, **changes}, {"id": 1, "parent": 0, "role": "AXStaticText", "text": MARKER}]
            self.assertNotIn(MARKER, json.dumps(self.pipeline(raw_event(nodes))))

    def test_partial_failure_survives_pipeline_with_path_and_retry_class(self):
        errors = [{"attribute": "AXChildren", "path": [0, 2], "scope": "AXFocusedWindow",
                   "status": "READ_FAILED", "error": -25204, "structural": True,
                   "retry_allowed": True, "retry_class": "fresh_read_allowed_no_action_replay",
                   "value": MARKER}]
        output = self.pipeline(raw_event([{"id": 0, "role": "AXWindow"}], read_status="READ_PARTIAL",
                                        complete=True, read_errors=errors))
        proof = output["evidence"]
        self.assertEqual(proof["read_status"], "READ_PARTIAL")
        self.assertFalse(proof["complete"])
        self.assertEqual(proof["read_errors"][0]["path"], [0, 2])
        self.assertTrue(proof["read_errors"][0]["retry_allowed"])
        self.assertNotIn(MARKER, json.dumps(output))

    def test_missing_completeness_is_unknown_and_never_promoted(self):
        output = self.pipeline(raw_event([]))
        self.assertEqual(output["evidence"]["read_status"], "UNKNOWN")
        self.assertFalse(output["evidence"]["complete"])

    def test_bounded_failure_evidence_does_not_overflow_memory(self):
        error = {"attribute": "AXChildren", "path": list(range(20)), "scope": "AXFocusedWindow",
                 "status": "READ_FAILED", "error": -25204, "retry_allowed": True,
                 "retry_class": "fresh_read_allowed_no_action_replay"}
        output = self.pipeline(raw_event([], read_status="READ_FAILED", complete=False, read_errors=[error] * 200))
        self.assertLessEqual(len(json.dumps(output["evidence"]).encode()), 8192)
        self.assertLessEqual(len(output["evidence"]["read_errors"]), 16)

    def test_window_exclusion_is_in_options_consent_and_filters_output(self):
        old = self.privacy.consent_id()
        self.config.native_window_exclusions = ("Synthetic excluded",)
        self.assertNotEqual(old, self.privacy.consent_id())
        self.assertFalse(self.privacy.native_allowed())
        self.privacy.authorize(True)
        self.assertEqual(native_options(self.config)["window_exclusions"], ["Synthetic excluded"])
        self.assertIsNone(self.pipeline(raw_event([], window_title="Synthetic excluded")))

    def test_legacy_consent_migrates_only_exact_empty_exclusion_scope(self):
        legacy = self.privacy.scope_description()
        legacy.pop("excluded_windows")
        old = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
        self.store.set("native_observation_consent", old)
        self.assertTrue(self.privacy.native_allowed())
        self.assertEqual(self.store.get("native_observation_consent"), self.privacy.consent_id())
        self.store.set("native_observation_consent", old)
        self.config.native_window_exclusions = ("Excluded",)
        self.assertFalse(self.privacy.native_allowed())
        self.assertEqual(self.store.get("native_observation_consent"), old)

    def test_legacy_consent_does_not_migrate_permission_expansion(self):
        legacy = self.privacy.scope_description()
        legacy.pop("excluded_windows")
        self.store.set("native_observation_consent", hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest())
        self.config.native_app_allowlist = (BUNDLE, "org.localpilot.additional")
        self.assertFalse(self.privacy.native_allowed())

    def test_acquisition_scope_tag_is_current_and_metric_changes_do_not_duplicate_memory(self):
        first = raw_event([{"id": 0, "role": "AXWindow"}], elapsed_ms=1.0, snapshot_count=1,
                          read_status="READ_SUCCESS_NONEMPTY", complete=True)
        second = deepcopy(first)
        second["evidence"].update(elapsed_ms=8.0, snapshot_count=2)
        first, second = self.pipeline(first), self.pipeline(second)
        self.assertEqual(first["object"]["acquisition_scope"], self.privacy.consent_id())
        self.assertEqual(first["dedupe_key"], second["dedupe_key"])

    def test_window_exclusions_are_bounded_and_old_configuration_loads(self):
        filename = Path(self.temp.name) / "config.json"
        filename.write_text('{}')
        self.assertEqual(Config.load(filename).native_window_exclusions, ())
        for values in (["x"] * 101, [""], ["line\nbreak"], [1], ["x" * 301]):
            filename.write_text(json.dumps({"native_window_exclusions": values}))
            with self.assertRaises(ValueError):
                Config.load(filename)

    def test_missing_shared_core_explicitly_downgrades_without_launch(self):
        with patch("companion.observers.native.SHARED_MANIFEST", Path(self.temp.name) / "missing.json"):
            with self.assertRaises(HelperRebuildRequired):
                shared_core_manifest()
        observer = NativeObserver(self.config, Mock())
        observer.config.native_helper_path = "/synthetic/helper"
        with patch("companion.observers.native.trusted_helper", side_effect=HelperRebuildRequired("missing")), \
                patch("companion.observers.native.subprocess.Popen") as create:
            self.assertEqual(observer.start()["state"], "MANUAL_REQUIRED")
        create.assert_not_called()

    def test_reader_rejects_malformed_protocol_identity_and_continues(self):
        valid = raw_event([])
        malformed = [dict(valid, source=[]), dict(valid, kind={}),
                     dict(valid, object={"bundle_id": [BUNDLE]})]
        stream = b"".join(json.dumps(event).encode() + b"\n" for event in [*malformed, valid])
        callback = Mock()
        observer = NativeObserver(self.config, callback)
        process = Mock(stdout=io.BytesIO(stream))
        process.poll.return_value = 0
        observer._read(process)
        self.assertEqual(observer.status()["rejected_events"], 3)
        self.assertEqual(observer.status()["accepted_events"], 1)
        callback.assert_called_once()
        process.terminate.assert_not_called()

    def test_sources_contain_shared_engine_and_no_duplicate_walkers(self):
        text = SOURCE.read_text()
        self.assertIn("AXReadEngine(", text)
        self.assertNotIn("func visit(", text)
        self.assertNotIn("fixtureNodes(", text)
        for file in [SOURCE, *(SHARED_CORE / n for n in SHARED_FILES)]:
            for forbidden in ("AXUIElementPerformAction(", "AXUIElementSetAttributeValue(", "CGEventPost(",
                              "NSAppleScript(", ".activate(", "Process()", "posix_spawn(", "Darwin.system("):
                self.assertNotIn(forbidden, file.read_text())


@unittest.skipUnless(sys.platform == "darwin" and Path("/usr/bin/xcrun").exists(), "macOS Swift fixture required")
class CompiledObserverV041Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = SOURCE.parents[1] / ".data"
        base.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="native-v041-", dir=base)
        cls.binary = build_native_helper(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, tree, **config_values):
        options = {"allowlist": [BUNDLE], "ax_enabled": True, "content_allowlist": [BUNDLE]}
        options.update(config_values)
        value = {"config": options, "trace": True, "events": [{"bundle_id": BUNDLE, "tree": tree, "title": "Synthetic fixture"}]}
        process = subprocess.run([self.binary, "--fixture"], input=json.dumps(value).encode(),
                                 capture_output=True, timeout=10, env=helper_environment())
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        return [json.loads(line) for line in process.stdout.splitlines()]

    def test_compiled_role_only_secure_prunes_before_sensitive_getters(self):
        tree = {"role": "AXWindow", "children": [
            {"role": "AXSecureTextField", "fixture_id": "private", "value": MARKER,
             "title": MARKER, "children": [{"role": "AXStaticText", "fixture_id": "private-child", "value": MARKER}]},
            {"role": "AXStaticText", "fixture_id": "public", "value": "Visible"}]}
        row = self.fixture(tree)[0]
        self.assertNotIn(MARKER, json.dumps(row))
        private = [r["attribute"] for r in row["evidence"]["getter_trace"] if r["node"] == "private"]
        self.assertEqual(private, ["AXRole"])
        self.assertFalse(any(r["node"] == "private-child" for r in row["evidence"]["getter_trace"]))

    def test_compiled_nested_secure_subrole_and_input_prune_preacquisition(self):
        tree = {"role": "AXWindow", "children": [{"role": "AXGroup", "children": [
            {"role": "AXGroup", "subrole": "AXSecureTextField", "fixture_id": "secure-subrole", "value": MARKER,
             "children": [{"role": "AXStaticText", "value": MARKER}]},
            {"role": "AXTextArea", "fixture_id": "input", "value": MARKER}]}]}
        row = self.fixture(tree)[0]
        self.assertNotIn(MARKER, json.dumps(row))
        for name, expected in (("secure-subrole", ["AXRole", "AXSubrole"]), ("input", ["AXRole"])):
            self.assertEqual([g["attribute"] for g in row["evidence"]["getter_trace"] if g["node"] == name], expected)

    def test_compiled_unknown_malformed_and_failed_identity_prune_preacquisition(self):
        for values in ({"role": "AXUnknown"}, {"role": 42}, {"role": "malformed"},
                       {"role": "AXGroup", "subrole": 42}, {"role": "AXGroup", "subrole": "malformed"},
                       {"role": "AXGroup", "read_failures": {"AXSubrole": -25204}}):
            row = self.fixture({"role": "AXWindow", "children": [{"fixture_id": "private", "value": MARKER,
                               "children": [{"role": "AXStaticText", "fixture_id": "hidden", "value": MARKER}], **values}]})[0]
            self.assertNotIn(MARKER, json.dumps(row))
            getters = row["evidence"]["getter_trace"]
            self.assertFalse(any(g["node"] == "hidden" for g in getters))
            self.assertFalse(any(g["node"] == "private" and g["attribute"] in {"AXTitle", "AXValue", "AXChildren"} for g in getters))
            self.assertFalse(row["evidence"]["complete"])

    def test_compiled_child_failure_partial_and_empty_success_are_distinct(self):
        failed = self.fixture({"role": "AXWindow", "read_failures": {"AXChildren": -25204}})[0]["evidence"]
        empty = self.fixture({"role": "AXWindow", "children": []})[0]["evidence"]
        self.assertEqual(failed["read_status"], "READ_PARTIAL")
        self.assertFalse(failed["complete"])
        self.assertEqual(failed["read_errors"][0]["attribute"], "AXChildren")
        self.assertTrue(failed["read_errors"][0]["retry_allowed"])
        self.assertEqual(empty["read_status"], "READ_SUCCESS_NONEMPTY")
        self.assertTrue(empty["complete"])

    def test_compiled_root_failure_is_failed_not_success_empty(self):
        proof = self.fixture({"role": "AXWindow", "application_read_failures": {"AXFocusedWindow": -25204}})[0]["evidence"]
        self.assertEqual(proof["read_status"], "READ_FAILED")
        self.assertFalse(proof["complete"])
        self.assertEqual(proof["node_count"], 0)

    def test_compiled_metadata_reads_no_content_except_authorized_exclusion_comparison(self):
        tree = {"role": "AXWindow", "children": [{"role": "AXStaticText", "value": MARKER}]}
        proof = self.fixture(tree, content_allowlist=[])[0]["evidence"]
        self.assertFalse(any(g["attribute"] in {"AXTitle", "AXValue"} for g in proof["getter_trace"]))
        proof = self.fixture(tree, content_allowlist=[], window_exclusions=["Synthetic fixture"])[0]["evidence"]
        self.assertEqual(proof["node_count"], 0)
        self.assertNotIn("window_title", proof)
        self.assertFalse(any(g["attribute"] in {"AXChildren", "AXValue"} for g in proof["getter_trace"]))

    def test_compiled_unauthorized_app_is_not_read(self):
        self.assertEqual(self.fixture({"role": "AXWindow", "value": MARKER}, allowlist=[]), [])
        self.assertEqual(self.fixture({"role": "AXWindow", "value": MARKER}, exclusions=[BUNDLE]), [])

    def test_compiled_target_identity_rejects_closed_switched_reused_pid(self):
        valid = {"pid": 123, "bundle": BUNDLE, "live_pid": 123, "live_bundle": BUNDLE,
                 "terminated": False, "front_pid": 123, "front_bundle": BUNDLE}
        for changes, expected in (({}, True), ({"terminated": True}, False), ({"live_pid": 124}, False),
                                  ({"live_bundle": "org.other.app"}, False), ({"front_pid": 124}, False),
                                  ({"front_bundle": "org.other.app"}, False), ({"live_bundle": None}, False)):
            process = subprocess.run([self.binary, "--fixture-target"], input=json.dumps({**valid, **changes}).encode(),
                                     capture_output=True, timeout=10, env=helper_environment())
            self.assertEqual(process.returncode, 0)
            self.assertEqual(json.loads(process.stdout)["evidence"]["target_allowed"], expected)

    def test_compiled_target_changes_stop_getters_and_discard_partial_content(self):
        tree = {"role": "AXWindow", "children": [{"role": "AXStaticText", "value": MARKER}]}
        for changes in ({"fixture_target_valid": False}, {"fixture_target_changes_after_getters": 2},
                        {"fixture_target_changes_after_getters": 8}):
            proof = self.fixture({**tree, **changes})[0]["evidence"]
            self.assertEqual(proof["node_count"], 0)
            self.assertEqual(proof["read_status"], "UNKNOWN")
            self.assertFalse(proof["complete"])
            self.assertNotIn(MARKER, json.dumps(proof))
            if changes.get("fixture_target_valid") is False:
                self.assertEqual(proof["getter_trace"], [])

    def test_compiled_capabilities_and_actual_unknown_actions_rejected(self):
        process = subprocess.run([self.binary, "--capabilities"], capture_output=True, timeout=10, env=helper_environment())
        capabilities = json.loads(process.stdout)
        self.assertEqual(capabilities["profile"], "observer")
        self.assertEqual(capabilities["actions"], [])
        self.assertEqual(capabilities["os_sandbox"], "NOT_IMPLEMENTED")
        for action in ("click", "type", "keypress", "drag", "scroll", "focus", "AXPress", "set", "shell"):
            process = subprocess.run([self.binary, "--" + action], input=b'{"operation":"action"}', capture_output=True,
                                     timeout=10, env=helper_environment())
            self.assertEqual(process.returncode, 2)
            self.assertEqual(process.stdout, b"")
        undefined = subprocess.run(["/usr/bin/nm", "-u", self.binary], capture_output=True, timeout=10).stdout.decode()
        for symbol in ("_AXUIElementPerformAction", "_AXUIElementSetAttributeValue", "_CGEventPost", "_CGEventCreateKeyboardEvent"):
            self.assertNotIn(symbol, undefined)

    def test_pinned_manifest_and_old_helper_requires_rebuild(self):
        self.assertEqual(trusted_helper(self.binary), self.binary)
        manifest = Path(self.binary).with_name("NativeObserver.manifest.json")
        original = manifest.read_text()
        try:
            manifest.write_text(json.dumps({"protocol": 1, "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                                            "binary_sha256": hashlib.sha256(Path(self.binary).read_bytes()).hexdigest()}))
            with self.assertRaises(HelperRebuildRequired):
                trusted_helper(self.binary)
        finally:
            manifest.write_text(original)


if __name__ == "__main__":
    unittest.main()
