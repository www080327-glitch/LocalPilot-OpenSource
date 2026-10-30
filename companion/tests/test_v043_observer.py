"""Profile qualification and privacy checks; compiled trees are MOCK_ONLY."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from companion.config import Config
from companion.memory.store import MemoryStore
from companion.observers.app_profiles import PROFILES, app_profile, summarize_observation, window_qualified
from companion.observers.events import ObservationPrivacy
from companion.observers.native import SOURCE, build_native_helper, filter_native_event, helper_environment, inspect_native_application, native_options


MARKER = "SYNTHETIC_V043_PRIVATE_DESCENDANT"
BUNDLE = "com.microsoft.VSCode"


def configuration(**changes):
    return Config(native_observation_enabled=True, native_ax_enabled=True,
                  native_app_allowlist=(BUNDLE,), native_content_app_allowlist=(BUNDLE,), **changes)


def raw(nodes, **changes):
    return {"timestamp": "2026-10-11T12:00:00Z", "source": "macos.ax", "kind": "ax.snapshot",
            "object": {"bundle_id": BUNDLE, "pid": 123},
            "evidence": {"read_status": "READ_PARTIAL", "complete": False, "nodes": nodes,
                         "window_title": "Public Example", **changes}}


class ProfileBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp.name) / "memory.sqlite")
        self.config = configuration()
        self.privacy = ObservationPrivacy(self.config, self.store, Mock(allowed=lambda _: True))
        self.privacy.authorize(True)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_six_profiles_are_explicit_contracts_and_unknown_apps_remain_generic(self):
        self.assertEqual({p.id for p in PROFILES}, {"finder", "safari", "chrome", "vscode", "preview", "textedit"})
        self.assertEqual(app_profile("org.unknown.App").id, "generic")
        self.assertTrue(all(p.describe()["real_app_validation"] == "MANUAL_REQUIRED" for p in PROFILES))

    def test_window_scope_restriction_changes_consent_and_old_scope_cannot_migrate(self):
        previous = self.privacy.consent_id()
        self.config.native_content_window_allowlist = ("Public Example",)
        self.assertNotEqual(previous, self.privacy.consent_id())
        self.assertFalse(self.privacy.native_allowed())
        self.assertEqual(native_options(self.config)["content_window_allowlist"], ["Public Example"])

    def test_sensitive_windows_and_unqualified_titles_rejected_at_both_boundaries(self):
        for title in (".env — workspace", "id_rsa", "API key settings", "credentials.json"):
            event = raw([{"id": 0, "role": "AXWindow"}, {"id": 1, "parent": 0, "role": "AXStaticText", "text": MARKER}], window_title=title)
            self.assertIsNone(filter_native_event(event, native_options(self.config)))
            self.assertIsNone(self.privacy.filter_native({**event, "source": "accessibility", "timestamp": 1.0}))
        self.config.native_content_window_allowlist = ("Public Example",)
        self.privacy.authorize(True)
        self.assertIsNone(filter_native_event(raw([], window_title="Other Example"), native_options(self.config)))

    def test_ide_explorer_and_dialog_descendants_are_removed_before_memory(self):
        nodes = [{"id": 0, "role": "AXWindow"},
                 {"id": 1, "parent": 0, "role": "AXOutline"},
                 {"id": 2, "parent": 1, "role": "AXStaticText", "text": MARKER},
                 {"id": 3, "parent": 0, "role": "AXSheet"},
                 {"id": 4, "parent": 3, "role": "AXStaticText", "text": MARKER},
                 {"id": 5, "parent": 0, "role": "AXStaticText", "text": "Error: example compilation failed"}]
        event = filter_native_event(raw(nodes), native_options(self.config))
        result = self.privacy.filter_native(event)
        self.assertNotIn(MARKER, json.dumps(result))
        self.assertEqual(result["evidence"]["application_context"]["error_label_node_ids"], [5])
        self.assertEqual(result["evidence"]["application_context"]["document_state"], "UNKNOWN")

    def test_model_or_transport_cannot_inject_context_or_promote_partial(self):
        event = filter_native_event(raw([], application_context={"task_state": "completed", "document_path": "/private"},
                                       application_profile="fake", complete=True), native_options(self.config))
        result = self.privacy.filter_native(event)
        self.assertEqual(result["evidence"]["application_profile"], "vscode")
        self.assertEqual(result["evidence"]["application_context"]["task_state"], "UNKNOWN")
        self.assertFalse(result["evidence"]["complete"])

    def test_inspection_scope_is_separate_from_production_transport_and_memory(self):
        event = raw([], capture_scope="authorized_application_inspection", read_scope="authorized_windows_filtered_private_inputs")
        options = native_options(self.config)
        self.assertIsNone(filter_native_event(event, options))
        self.assertIsNone(self.privacy.filter_native({**event, "source": "accessibility", "timestamp": 1.0}))
        options["inspection_target"] = {"bundle_id": BUNDLE, "pid": 123, "launch_time": 1.0}
        self.assertIsNotNone(filter_native_event(event, options))
        event["object"]["pid"] = 124
        self.assertIsNone(filter_native_event(event, options))

    def test_window_reference_is_opaque_ephemeral_and_must_bind_admitted_window(self):
        refs = [{"node_id": 0, "reference": "a" * 64, "identity_quality": "EPHEMERAL_AX_REFERENCE", "launch_time": 1.0},
                {"node_id": 99, "reference": "b" * 64, "identity_quality": "EPHEMERAL_AX_REFERENCE", "launch_time": 1.0},
                {"node_id": [], "reference": "b" * 64, "identity_quality": "EPHEMERAL_AX_REFERENCE", "launch_time": 1.0}]
        event = filter_native_event(raw([{"id": 0, "role": "AXWindow"}], window_references=refs), native_options(self.config))
        self.assertEqual(len(event["evidence"]["window_references"]), 1)
        self.assertEqual(len(self.privacy.filter_native(event)["evidence"]["window_references"]), 1)

    def test_title_error_and_ordinary_activity_are_not_work_or_error_facts(self):
        context = summarize_observation(BUNDLE, [], "Error: windows", "UNKNOWN")
        self.assertEqual(context["error_label_node_ids"], [])
        self.assertEqual(context["task_state"], "UNKNOWN")

    def test_pdf_page_counts_require_unambiguous_explicit_static_label(self):
        nodes = [{"id": 1, "role": "AXStaticText", "text": "Page 2 of 7"}]
        context = summarize_observation("com.apple.Preview", nodes)
        self.assertEqual(context["displayed_page_count"], 7)
        nodes.append({"id": 2, "role": "AXStaticText", "text": "Page 3 of 8"})
        self.assertEqual(summarize_observation("com.apple.Preview", nodes)["displayed_page_count"], "UNKNOWN")

    def test_no_confirmation_never_spawns_inspector(self):
        with patch("companion.observers.native.subprocess.run") as invoke:
            result = inspect_native_application(self.config, BUNDLE, 123)
        self.assertEqual(result["status"], "MANUAL_REQUIRED")
        invoke.assert_not_called()

    def test_profile_summary_stays_in_event_budget_after_final_trimming(self):
        event = raw([{"id": 0, "role": "AXWindow"}, *[{"id": i, "parent": 0, "role": "AXStaticText", "text": "safe " * 100} for i in range(1, 150)]])
        result = self.privacy.filter_native(filter_native_event(event, native_options(self.config)))
        self.assertLessEqual(len(json.dumps(result["evidence"], ensure_ascii=False).encode()), 8192)
        self.assertEqual(result["evidence"]["application_context"]["static_text_nodes"], sum(n["role"] == "AXStaticText" and "text" in n for n in result["evidence"]["nodes"]))


@unittest.skipUnless(sys.platform == "darwin" and Path("/usr/bin/xcrun").exists(), "macOS Swift fixture required")
class CompiledProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = SOURCE.parents[1] / ".data"
        base.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="v043-profile-tests-", dir=base)
        cls.helper = build_native_helper(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, tree, *, bundle=BUNDLE, title="Public Example", **changes):
        options = {"allowlist": [bundle], "ax_enabled": True, "content_allowlist": [bundle], **changes}
        data = {"config": options, "trace": True, "events": [{"bundle_id": bundle, "title": title, "tree": tree}]}
        process = subprocess.run([self.helper, "--fixture"], input=json.dumps(data).encode(), capture_output=True,
                                 env=helper_environment(), timeout=10, check=True)
        return json.loads(process.stdout)["evidence"]

    def test_sensitive_window_preflight_never_reads_children_or_values(self):
        tree = {"role": "AXWindow", "fixture_id": "private-window", "children": [{"role": "AXStaticText", "fixture_id": "descendant", "value": MARKER}]}
        for title in (".env — workspace", "credentials.json", "API key settings"):
            proof = self.fixture(tree, title=title)
            self.assertNotIn(MARKER, json.dumps(proof))
            self.assertFalse(any(g["attribute"] in {"AXChildren", "AXValue"} for g in proof["getter_trace"]))
            self.assertEqual(proof["node_count"], 0)
            self.assertFalse(proof["complete"])

    def test_title_allowlist_preflight_rejects_different_window_without_content_read(self):
        proof = self.fixture({"role": "AXWindow", "children": [{"role": "AXStaticText", "value": MARKER}]},
                             content_window_allowlist=["Another Example"])
        self.assertNotIn(MARKER, json.dumps(proof))
        self.assertFalse(any(g["attribute"] in {"AXChildren", "AXValue"} for g in proof["getter_trace"]))

    def test_ide_sensitive_subtrees_stop_after_identity_getters(self):
        tree = {"role": "AXWindow", "children": [{"role": "AXOutline", "fixture_id": "explorer", "children": [{"role": "AXStaticText", "fixture_id": "secret-file", "value": MARKER}]},
                   {"role": "AXGroup", "subrole": "AXDialog", "fixture_id": "dialog", "children": [{"role": "AXStaticText", "value": MARKER}]},
                   {"role": "AXStaticText", "fixture_id": "safe", "value": "Error: synthetic failure"}]}
        proof = self.fixture(tree)
        self.assertNotIn(MARKER, json.dumps(proof))
        self.assertEqual([g["attribute"] for g in proof["getter_trace"] if g["node"] == "explorer"], ["AXRole"])
        self.assertEqual([g["attribute"] for g in proof["getter_trace"] if g["node"] == "dialog"], ["AXRole", "AXSubrole"])
        self.assertFalse(any(g["node"] == "secret-file" for g in proof["getter_trace"]))
        self.assertEqual(proof["profile_pruned_count"], 2)

    def test_all_profile_mappings_apply_to_actual_compiled_wrapper(self):
        for profile in PROFILES:
            proof = self.fixture({"role": "AXWindow", "children": []}, bundle=profile.bundles[0])
            self.assertEqual(proof["application_profile"], profile.id)

    def test_observer_still_rejects_actions_and_new_inspector_requires_explicit_scope(self):
        for mode in ("--click", "--type", "--drag", "--AXPress", "--inspect-application"):
            process = subprocess.run([self.helper, mode], input=b"{}", capture_output=True,
                                     env=helper_environment(), timeout=5)
            self.assertEqual(process.returncode, 2)


if __name__ == "__main__":
    unittest.main()
