import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

from companion.benchmark.holdout import build_fixture, close, load_holdout, source_claim
from companion.config import Config
from companion.memory.retention import retain
from companion.model.backend import ModelManager
from companion.model.structured import TokenLanguage, decide, language, parse
from companion.runtime.routing import needs_agent
from companion.triggers.active import candidate, verify


class StructuredTests(unittest.TestCase):
    def test_missing_fields(self):
        self.assertIsNone(parse({"status":"ok","text":'{"action":"quiet"}'}, "active"))

    def test_extra_fields(self):
        self.assertIsNone(parse({"status":"ok","text":'{"action":"quiet","confidence":1,"why":"x"}'}, "active"))

    def test_illegal_label(self):
        self.assertIsNone(parse({"status":"ok","text":'{"action":"interrupt","confidence":1}'}, "active"))

    def test_explanation_text(self):
        self.assertIsNone(parse({"status":"ok","text":'答案：{"action":"quiet","confidence":1}'}, "active"))

    def test_truncation_and_incomplete_json(self):
        for status, text in (("truncated", '{"action":"quiet","confidence":1}'), ("ok", '{"action":"quiet",')):
            self.assertIsNone(parse({"status":status,"text":text}, "active"))

    def test_natural_language(self):
        self.assertIsNone(parse({"status":"ok","text":"应该沉默。"}, "active"))

    def test_empty_output(self):
        for text in ("", " ", None):
            self.assertIsNone(parse({"status":"ok","text":text}, "active"))

    def test_duplicate_bool_nan_nested_injection(self):
        for text in ('{"action":"quiet","action":"notify","confidence":1}',
                     '{"action":"quiet","confidence":true}', '{"action":"quiet","confidence":NaN}',
                     '{"action":[],"confidence":1}', '[{"action":"quiet","confidence":1}]',
                     '{"action":"quiet","confidence":1e309}', '```json\n{"action":"quiet","confidence":1}\n```'):
            self.assertIsNone(parse({"status":"ok","text":text}, "active"))

    def test_all_finite_languages_validate(self):
        for schema in ("active", "route", "support"):
            for text in language(schema):
                self.assertIsNotNone(parse({"status":"ok","text":text}, schema))

    def test_bounded_repair_and_failed_closed(self):
        model = Mock()
        model.complete.side_effect = [{"status":"ok","text":"bad"}, {"status":"ok","text":'{"route":"agent","confidence":1}'}]
        result = decide(model, [], "route")
        self.assertEqual(result["status"], "valid")
        self.assertEqual(len(result["attempts"]), 2)
        model.complete.side_effect = None
        model.complete.return_value = {"status":"ok","text":"bad"}
        self.assertIsNone(decide(model, [], "route")["decision"])
        self.assertEqual(model.complete.call_count, 4)
        with self.assertRaises(ValueError):
            decide(model, [], "route", repairs=2)

    def test_token_trie_cannot_escape_or_terminate_early(self):
        trie = TokenLanguage([[10,20,30], [10,21]], [99])
        self.assertEqual(trie.allowed([]), {10})
        self.assertEqual(trie.allowed([10]), {20,21})
        self.assertEqual(trie.allowed([10,21]), {99})
        self.assertEqual(trie.allowed([10,21,99]), {99})
        with self.assertRaises(ValueError):
            trie.allowed([10,99])
        with self.assertRaises(ValueError):
            trie.allowed([10,21,99,20])
        with self.assertRaises(ValueError):
            trie.allowed([10,22])


class V02Tests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / ".data"
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.obj, self.docs = build_fixture(self.root)
        self.obj.config.low_power_policy = "off"
        self.obj.config.localpilot_endpoint = ""
        from companion.escalation.service_v491 import LocalPilotProvider
        self.obj.localpilot = LocalPilotProvider(self.obj.config)
        self.suite, _ = load_holdout()

    def tearDown(self):
        close(self.obj)
        self.temp.cleanup()

    def claim(self, name):
        return source_claim(self.obj, next(c for c in self.suite["cases"] if c["id"] == name))

    def test_source_correct_wrong_cell_page_stale_fabricated_conflict(self):
        for case in self.suite["cases"]:
            if case["category"] != "source":
                continue
            with self.subTest(case=case["id"]):
                self.assertEqual(self.obj.verifier.verify(source_claim(self.obj, case))["status"], case["expected"])

    def test_source_reads_live_hash_without_file_event(self):
        claim = self.claim("v-txt-ok")
        Path(claim["source_file"]).write_text("项目：松岚\n预算：18万\n")
        self.assertEqual(self.obj.verifier.verify(claim)["reason"], "current_bytes_changed")

    def test_source_scope_revoke(self):
        claim = self.claim("v-txt-ok")
        self.obj.scope.excludes.append(self.docs)
        self.assertEqual(self.obj.verifier.verify(claim)["status"], "UNVERIFIED")

    def test_source_unsupported_does_not_upgrade_observation(self):
        claim = self.claim("v-semantic")
        result = self.obj.verifier.verify(claim)
        self.assertEqual(result["evidence_class"], "INFERRED")
        self.assertEqual(result["status"], "UNVERIFIED")

    def test_source_rejects_foreign_context_memory_id(self):
        self.assertEqual(self.obj.verifier.verify(self.claim("v-txt-ok"), {"other"})["status"], "UNVERIFIED")

    def test_xlsx_same_value_wrong_field_column(self):
        claim = self.claim("v-xlsx-ok") | {"location":"sheet Costs cell C2"}
        self.assertEqual(self.obj.verifier.verify(claim)["status"], "CONTRADICTED")

    def test_model_answer_wrong_location_is_withheld(self):
        self.obj.model = Mock()
        self.obj.model.complete.return_value = {"status":"ok","text":"预算是 170000，来自 budget.xlsx sheet Costs cell B1。"}
        answer = self.obj.ask("只根据budget.xlsx简短说明内容")
        self.assertEqual(answer["status"], "unverified")
        self.assertNotIn("170000", answer["text"])
        self.assertEqual(answer["source_verification"][0]["status"], "CONTRADICTED")

    def test_model_answer_no_citation_remains_unverified(self):
        self.obj.model = Mock()
        self.obj.model.complete.return_value = {"status":"ok","text":"资料已经审阅完毕。"}
        answer = self.obj.ask("简短总结notes.docx")
        self.assertEqual(answer["source_verification"][0]["status"], "UNVERIFIED")
        self.assertIn("未验证", answer["text"])

    def test_host_scalar_answer_verified_and_unit_equivalence(self):
        self.obj.model = Mock()
        answer = self.obj.ask("松松经费是多少")
        self.assertIn("17万", answer["text"])
        self.assertNotIn("冲突", answer["text"])
        self.assertTrue(all(v["status"] == "SUPPORTED" for v in answer["source_verification"]))
        self.obj.model.complete.assert_not_called()

    def test_alias_scopes_do_not_cross_projects(self):
        rows = self.obj.retrieve("赤赤预算")
        self.assertTrue(rows)
        self.assertTrue(all("赤湾" in r["source_reference"] for r in rows))

    def test_synonym_owner_deadline_and_second_long_hit(self):
        for query, value in (("松岚负责人员", "小陶"), ("松岚到期时间", "11月16日"),
                             ("松岚供货商第二次核对", "银杉印刷"), ("松岚供应商第二处验收结论", "最终验收：通过")):
            rows = self.obj.retrieve(query)
            self.assertTrue(any(value in r["summary"] for r in rows), query)

    def test_new_old_and_multi_project_retrieval(self):
        # Four complete provenance records require a bounded budget independent
        # of checkout path length; pack() still enforces the configured budget.
        self.obj.config.retrieval_chars = 6000
        self.obj.config.model_context_tokens = 16384
        for _ in range(20):
            self.obj.store.add("conversation", "松岚和赤湾预算是多少", "user_chat")
        rows = self.obj.retrieve("同时查看松岚和赤湾的预算")
        files = {Path(r["source_reference"]).name for r in rows}
        self.assertTrue({"budget.txt", "budget.xlsx", "a.txt", "b.txt"}.issubset(files))
        self.assertTrue(any("170000" in r["summary"] for r in rows if r["source_reference"].endswith("budget.xlsx")))
        self.assertFalse(any("12万" in r["summary"] for r in rows))

    def test_missing_named_source_does_not_summarize_another_file(self):
        self.obj.model = Mock()
        answer = self.obj.ask("只看absent.md，提取三点。")
        self.assertIn("找不到", answer["text"])
        self.obj.model.complete.assert_not_called()

    def test_candidate_filters_before_model(self):
        self.obj.model = Mock()
        for event in ({"kind":"batch","count":400}, {"kind":"edits","count":80,"initial_index":True},
                      {"kind":"error","errors":5,"same_error":True,"busy":True}):
            self.assertEqual(self.obj.consider_event(event)["action"], "quiet")
        self.obj.model.complete.assert_not_called()

    def test_host_error_invitation_does_not_depend_on_model_json(self):
        self.obj.model = Mock()
        self.obj.model.complete.return_value = {"status":"ok","text":'{"action":"quiet","confidence":0.95}'}
        event = {"kind":"error","same_error":True,"errors":3,"hour":12}
        result = self.obj.consider_event(event)
        self.assertEqual(result["action"], "ask-help")
        self.assertEqual(result["origin"], "host_evidence")
        self.obj.last_candidate.clear()
        self.obj.store.db.execute("DELETE FROM notices")
        self.obj.store.db.commit()
        self.obj.model.complete.return_value = {"status":"ok","text":"bad"}
        self.assertEqual(self.obj.consider_event(event)["action"], "ask-help")
        self.obj.model.complete.assert_not_called()
        self.assertIsNone(self.obj.store.get("pending_escalation"))

    def test_normal_editing_cannot_be_promoted_without_evidence(self):
        item = candidate({"kind":"edits","count":10,"minutes":80,"hour":12})
        self.assertEqual(verify(item, {"action":"ask-help","confidence":1})["action"], "quiet")
        self.assertIsNone(candidate({"kind":"error","errors":4,"same_error":True,"hour":2}))

    def test_production_repeated_error_and_bulk_file_changes(self):
        self.obj.model = Mock()
        self.obj.model.complete.return_value = {"status":"ok","text":'{"action":"quiet","confidence":1}'}
        with unittest.mock.patch("companion.runtime.service.datetime") as clock:
            from datetime import datetime
            clock.fromtimestamp.side_effect = lambda t: datetime(2026,10,3,12)
            for i in range(3):
                self.obj.record_event(str(self.docs / "松岚" / "error.txt"), "modified", "松岚", {"error_signature":"same parser error"})
        self.assertEqual(self.obj.store.get("last_active_decision")["verdict"]["origin"], "host_evidence")

    def test_feedback_not_needed_raises_threshold_and_backoff(self):
        policy = self.obj.policy
        baseline = policy.settings("repeated_error")
        nid = policy.record("repeated_error", "feedback-1", "hello")
        policy.respond(nid, "not_needed")
        settings = policy.settings("repeated_error")
        self.assertGreater(settings["threshold"], baseline["threshold"])
        self.assertGreater(settings["ignore_backoff"], baseline["ignore_backoff"])

    def test_feedback_more_changes_frequency_with_safety_caps(self):
        policy = self.obj.policy
        before = policy.settings("repeated_error")
        nid = policy.record("repeated_error", "feedback-2", "hello")
        policy.respond(nid, "more")
        after = policy.settings("repeated_error")
        self.assertLess(after["cooldown_seconds"], before["cooldown_seconds"])
        self.assertGreater(after["daily_limit"], before["daily_limit"])
        self.assertGreaterEqual(after["threshold"], self.obj.config.relevance_threshold)
        self.obj.store.set("dnd", True)
        self.assertFalse(policy.allowed("repeated_error", "new", time.time()+86400))

    def test_feedback_mute_help_and_duplicate_response(self):
        nid = self.obj.policy.record("deadline", "mute", "hello")
        self.obj.policy.respond(nid, "mute")
        self.assertFalse(self.obj.policy.allowed("deadline", "later", time.time()+86400))
        with self.assertRaises(ValueError):
            self.obj.policy.respond(nid, "more")
        nid = self.obj.policy.record("help", "help", "hello")
        result = self.obj.command({"command":"notice_action","id":nid,"action":"help","text":"整理问题"})
        self.assertEqual(result["escalation"]["status"], "unavailable")
        self.assertEqual(self.obj.store.get("runtime_totals")["accepted_help"], 1)

    def test_feedback_timeout_is_counted_once(self):
        policy = self.obj.policy
        policy.record("deadline", "age", "hello", delivery="displayed_native_banner", now=time.time()-7200)
        policy.allowed("other", "now")
        ignored = self.obj.store.get("runtime_totals")["ignored"]
        policy.allowed("other", "again")
        self.assertEqual(self.obj.store.get("runtime_totals")["ignored"], ignored)

    def versions(self, count=7):
        file = self.docs / "松岚" / "many.txt"
        for i in range(count):
            file.write_text("项目：松岚\n预算：" + str(i+30) + "万\n" + "归档原文\n" * 60)
            self.obj.process_file(str(file), "initial")
        return file

    def test_retention_current_permanent_recent_and_count(self):
        file = self.versions()
        before = file.read_bytes()
        result = retain(self.obj.store, recent=2, metadata_limit=4)
        rows = [r for r in self.obj.store.records(kinds=["document"]) if r["source_reference"] == str(file)]
        self.assertEqual(len(rows), 5)
        current = next(r for r in rows if self.obj.store.is_current(r))
        self.assertIn("index_text", current["metadata"])
        self.assertEqual(sum("index_text" in r["metadata"] for r in rows), 3)
        self.assertGreater(result["compacted"], 0)
        self.assertEqual(file.read_bytes(), before)

    def test_retention_ttl_current_protection_and_pending_pin(self):
        file = self.versions(4)
        rows = [r for r in self.obj.store.records(kinds=["document"]) if r["source_reference"] == str(file)]
        oldest = rows[-1]
        self.obj.store.set("pending_escalation", {"relevant_memories":[oldest]})
        retain(self.obj.store, recent=1, full_ttl_days=1, metadata_limit=1, now=time.time()+30*86400)
        self.assertIsNotNone(self.obj.store.db.execute("SELECT 1 FROM memories WHERE id=?", (oldest["id"],)).fetchone())
        current = next(r for r in rows if self.obj.store.is_current(r))
        self.assertIn("index_text", json.loads(self.obj.store.db.execute("SELECT metadata FROM memories WHERE id=?", (current["id"],)).fetchone()[0]))

    def test_retention_activity_and_notices_bounded(self):
        for i in range(8):
            self.obj.store.add("conversation", "reply", "companion_model", epistemic="inferred")
            nid = self.obj.policy.record("kind", "notice-"+str(i), "hello")
            self.obj.policy.respond(nid, "ignore")
        retain(self.obj.store, record_limit=3)
        self.assertEqual(len(self.obj.store.records(kinds=["conversation"])), 3)
        self.assertEqual(self.obj.store.db.execute("SELECT count(*) FROM notices").fetchone()[0], 3)

    def test_retention_idempotent_and_reopen(self):
        self.versions()
        retain(self.obj.store, recent=2, metadata_limit=4)
        result = retain(self.obj.store, recent=2, metadata_limit=4)
        self.assertEqual(result["compacted"], 0)
        self.assertEqual(result["deleted"], 0)
        from companion.memory import MemoryStore
        filename = self.obj.store.db.execute("PRAGMA database_list").fetchone()[2]
        reopened = MemoryStore(filename)
        try:
            self.assertEqual(retain(reopened, recent=2, metadata_limit=4)["compacted"], 0)
            self.assertTrue(all("index_text" in r["metadata"] for r in reopened.records(kinds=["document"]) if reopened.is_current(r)))
        finally:
            reopened.close()

    def test_route_casual_and_actual_operations(self):
        self.assertFalse(needs_agent("只是随便问问，复杂跨文件风险评估通常是什么？"))
        self.assertTrue(needs_agent("我只是随便问问，但帮我修改预算文件。"))
        self.assertTrue(needs_agent("对照这些文件核对付款并制定方案。"))
        self.assertFalse(needs_agent("删除文件这个词是什么意思？"))

    def test_invalid_semantic_route_does_not_become_valid_local_decision(self):
        self.obj.model = Mock()
        self.obj.model.complete.return_value = {"status":"ok","text":"local"}
        self.assertEqual(self.obj.ask("比较两个方案的取舍")["status"], "unavailable")

    def test_telemetry_all_fields_and_counts_not_last_twenty(self):
        for i in range(25):
            self.obj.policy.record("kind", "many-"+str(i), "hello")
        state = self.obj.status()
        for key in ("totals", "notification_count", "ignored_count", "accepted_help_count", "db_bytes", "queue_depth", "old_versions_retained"):
            self.assertIn(key, state)
        self.assertEqual(state["notification_count"], 25)

    def test_cumulative_model_calls_survive_new_manager(self):
        first = ModelManager(self.obj.config, self.obj.store)
        first.complete([{"role":"user","content":"hi"}])
        second = ModelManager(self.obj.config, self.obj.store)
        self.assertEqual(second.inferences, first.inferences)

    def test_escalation_approval_not_overwritten_by_source_bytes(self):
        self.obj.ask("帮我修改松岚budget.txt")
        self.obj.agent = Mock()
        self.obj.agent.submit.return_value = {"status":"submitted"}
        result = self.obj.command({"command":"submit_escalation", "approved":True})
        self.assertEqual(result["status"], "unavailable")
        self.obj.agent.submit.assert_not_called()

    def test_v02_comparison_rejects_missing_identity_and_prompt_drift(self):
        from companion.benchmark.compare_v02 import compare
        identity = {"hardware":"synthetic"}
        report = {"status":"completed", "kind":"real_model", "suite_sha256":"suite", "fixture_sha256":{},
                  "generation":{},"pipeline_config":{},"source_sha256":{},"identity":identity,
                  "identity_sha256":hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
                  "rows":[{"id":"one","prompt_sha256":"same"}]}
        self.assertEqual(compare(report,report)["status"], "accepted_diagnostic_comparison")
        self.assertEqual(compare(report,report | {"identity_sha256":"wrong"})["status"], "BLOCKED")
        self.assertEqual(compare(report,report | {"rows":[{"id":"one","prompt_sha256":"changed"}]})["status"], "BLOCKED")

    def test_holdout_and_v01_suite_frozen_reproducible(self):
        from companion.benchmark.runner import load_suite
        _, old_hash = load_suite()
        self.assertEqual(old_hash, "1214e2aeb0ee5713a2ab25c82ae3573bed3d12e134e814687d33f084e174d02f")
        other, docs = build_fixture(self.root / "other")
        try:
            self.assertEqual({str(p.relative_to(self.docs)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.docs.rglob("*") if p.is_file()},
                             {str(p.relative_to(docs)):hashlib.sha256(p.read_bytes()).hexdigest() for p in docs.rglob("*") if p.is_file()})
        finally:
            close(other)

    def test_config_rejects_invalid_new_controls(self):
        original = json.loads((self.root / "config.json").read_text())
        for patch in ({"structured_repairs":2}, {"project_aliases":{"x":"a"}}, {"retention_metadata_limit":1},
                      {"active_sustained_minutes":float("nan")}, {"http_schema_supported":"true"}):
            file = self.root / "bad-config.json"
            file.write_text(json.dumps(original | patch))
            with self.assertRaises(ValueError):
                Config.load(file)


if __name__ == "__main__":
    unittest.main()
