"""V0.4 observation controls; synthetic sources are not real AX/model trials."""
import json
from pathlib import Path
import tempfile
import unittest

from companion.memory import MemoryStore
from companion.memory.observations import ObservationMemory


class ObservationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "memory.sqlite3"
        self.store = MemoryStore(self.database)
        self.memory = ObservationMemory(self.store, aliases={"老项目": "天河"})
        self.now = 1800000000.0

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def event(self, **updates):
        return {"timestamp": self.now, "source": "workspace_observer", "kind": "window_changed",
                "object": {"app": "Keynote", "title": "天河演示文稿"},
                "evidence": {"summary": "天河演示文稿更新", "project": "天河"},
                "confidence": 1.0, "sensitivity": "private", "dedupe_key": "window-a", **updates}

    def test_reopen_preserves_ids_raw_and_fts(self):
        result = self.memory.add(self.event())
        self.store.close()
        self.store = MemoryStore(self.database)
        self.memory = ObservationMemory(self.store)
        self.assertEqual(self.memory.get(result["id"])["evidence"], self.event()["evidence"])
        self.assertEqual(self.memory.retrieve("演示文稿", now=self.now)[0]["id"], result["id"])
        self.assertEqual(self.store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_exact_replay_does_not_inflate_occurrence(self):
        first = self.memory.add(self.event())
        again = self.memory.add(self.event())
        self.assertEqual(first["id"], again["id"])
        self.assertTrue(again["merged"])
        self.assertTrue(again["replayed"])
        self.assertFalse(again["new_occurrence"])
        self.assertEqual(again["occurrences"], 1)

    def test_same_event_new_time_is_distinct_occurrence(self):
        first = self.memory.add(self.event())
        later = self.memory.add(self.event(timestamp=self.now + 5, confidence=0.7))
        self.assertEqual(first["id"], later["id"])
        self.assertTrue(later["new_occurrence"])
        self.assertEqual(later["occurrences"], 2)
        self.assertEqual(later["confidence"], 0.7)
        self.assertEqual(later["first_timestamp"], self.now)

    def test_occurrence_id_resists_replayed_timestamp_change(self):
        first = self.memory.add(self.event(occurrence_id="event-42"))
        again = self.memory.add(self.event(occurrence_id="event-42", timestamp=self.now + 200))
        self.assertEqual(first["id"], again["id"])
        self.assertTrue(again["replayed"])
        self.assertEqual(again["last_timestamp"], self.now)

    def test_thousand_occurrences_bound_tokens_preserve_aggregate(self):
        first = self.memory.add(self.event())
        for i in range(1, 1001):
            result = self.memory.add(self.event(timestamp=self.now+i))
            self.assertTrue(result["new_occurrence"])
        self.assertEqual(first["id"], result["id"])
        self.assertEqual(result["occurrences"], 1001)
        self.assertLessEqual(self.memory.status()["occurrence_tokens"], 256)
        self.assertEqual(result["occurrence_archive"]["folded_tokens"], 745)
        self.assertEqual(result["evidence"], first["evidence"])
        replay = self.memory.add(self.event(timestamp=self.now+1000))
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["archived_unknown"])
        self.assertEqual(replay["occurrences"], 1001)

    def test_archived_old_replay_and_late_new_conservatively_quiet(self):
        for i in range(300):
            result = self.memory.add(self.event(timestamp=self.now+i))
        before = result["occurrences"]
        for event in (self.event(), self.event(timestamp=self.now+1.5, occurrence_id="late-new")):
            old = self.memory.add(event)
            self.assertTrue(old["archived_unknown"])
            self.assertFalse(old["new_occurrence"])
            self.assertFalse(old["replayed"])
            self.assertEqual(old["occurrences"], before)
        self.assertEqual(old["last_timestamp"], self.now+299)

    def test_watermark_persists_across_reopen_and_cascade_delete(self):
        for i in range(300):
            result = self.memory.add(self.event(timestamp=self.now+i, source_reference="a.txt"))
        mid = result["id"]
        self.store.close(); self.store = MemoryStore(self.database)
        self.memory = ObservationMemory(self.store)
        old = self.memory.add(self.event(source_reference="a.txt"))
        self.assertTrue(old["archived_unknown"])
        self.assertEqual(old["occurrences"], 300)
        self.assertEqual(self.memory.get(mid)["occurrence_archive"]["watermark"], self.now+43)
        self.memory.forget_source("a.txt")
        self.assertEqual(self.memory.status()["archived_event_count"], 0)
        self.assertEqual(self.memory.status()["occurrence_tokens"], 0)

    def test_equal_timestamp_boundary_remains_bounded_and_unknown(self):
        for i in range(300):
            result = self.memory.add(self.event(occurrence_id="event-"+str(i)))
        self.assertLessEqual(self.memory.status()["occurrence_tokens"], 256)
        self.assertTrue(result["archived_unknown"])
        self.assertEqual(result["occurrences"], 257)
        newer = self.memory.add(self.event(timestamp=self.now+1, occurrence_id="newer"))
        self.assertTrue(newer["new_occurrence"])
        self.assertEqual(newer["occurrences"], 258)

    def test_previous_database_occurrence_rows_migrate_with_counts(self):
        mid = self.memory.add(self.event())["id"]
        for i in range(1, 400):
            self.store.db.execute("INSERT INTO observation_occurrences VALUES(?,?,?)", (mid, "legacy-"+str(i), self.now+i))
        self.store.db.execute("UPDATE observation_events SET occurrences=400,last_timestamp=? WHERE id=?", (self.now+399,mid))
        self.store.db.execute("DROP TABLE observation_occurrence_archive")
        self.store.db.commit()
        self.store.close(); self.store = MemoryStore(self.database)
        self.memory = ObservationMemory(self.store)
        self.assertEqual(self.memory.get(mid)["occurrences"], 400)
        self.assertEqual(self.memory.status()["occurrence_tokens"], 256)
        self.assertTrue(self.memory.add(self.event())["archived_unknown"])

    def test_expiry_and_clear_remove_archive(self):
        for i in range(300):
            self.memory.add(self.event(timestamp=self.now+i))
        self.memory.retain(now=self.now+31*86400)
        self.assertEqual(self.memory.status()["archived_event_count"], 0)
        for i in range(300):
            self.memory.add(self.event(timestamp=self.now+i))
        self.memory.clear()
        self.assertEqual(self.memory.status()["archived_event_count"], 0)
        self.assertEqual(self.memory.status()["occurrence_tokens"], 0)

    def test_dedupe_collision_never_overwrites_evidence(self):
        first = self.memory.add(self.event())
        changed = self.memory.add(self.event(evidence={"summary": "天河预算更新为20万", "project": "天河"}))
        self.assertTrue(changed["collision"])
        self.assertNotEqual(first["id"], changed["id"])
        self.assertEqual(self.memory.get(first["id"])["evidence"], self.event()["evidence"])

    def test_model_output_and_derivation_cannot_be_facts(self):
        with self.assertRaises(ValueError):
            self.memory.add(self.event(source="companion_model"))
        inference = self.memory.add(self.event(source="companion_model", epistemic="inferred"))
        with self.assertRaises(ValueError):
            self.memory.add(self.event(derived_from=[inference["id"]]))
        self.assertEqual(inference["provenance"], "UNVERIFIED_INFERENCE")

    def test_inference_keeps_raw_parent(self):
        raw = self.memory.add(self.event())
        inferred = self.memory.add(self.event(source="model_task_classifier", epistemic="inferred", evidence={"summary": "用户可能正在制作演讲"}, derived_from=[raw["id"]]))
        self.assertEqual(self.memory.get(raw["id"])["evidence"], self.event()["evidence"])
        self.assertEqual(inferred["derived_from"], [raw["id"]])

    def test_default_expiry_works_without_maintenance(self):
        self.memory.add(self.event())
        self.assertEqual(self.memory.records(now=self.now + 31*86400), [])
        self.assertEqual(self.memory.retrieve("演示文稿", now=self.now + 31*86400), [])

    def test_changed_ttl_persists_and_applies_before_next_maintenance(self):
        event = self.memory.add(self.event())
        self.memory.retain(now=self.now, ttl_days=2, raw_ttl_days=1)
        self.assertFalse(self.memory.is_current(event, now=self.now+3*86400))
        self.store.close(); self.store = MemoryStore(self.database)
        self.memory = ObservationMemory(self.store)
        self.assertEqual(self.memory.status()["ttl_days"], 2)
        self.assertFalse(self.memory.records(now=self.now+3*86400))

    def test_explicit_expiry_applies_to_important_record(self):
        self.memory.add(self.event(important=True, expires_at=self.now + 1))
        self.assertFalse(self.memory.records(now=self.now + 1))
        stats = self.memory.retain(now=self.now + 1)
        self.assertEqual(stats["deleted"], 1)

    def test_important_and_user_facts_survive_retention(self):
        important = self.memory.add(self.event(important=True))
        user = self.memory.add(self.event(source="explicit_user_statement", kind="preference", dedupe_key="user", evidence={"summary": "用户偏好简洁表达"}))
        self.memory.retain(now=self.now + 500*86400, record_limit=1)
        self.assertEqual(self.memory.get(important["id"])["raw_state"], "raw")
        self.assertTrue(self.memory.get(user["id"])["important"])
        self.assertEqual(len(self.memory.records(now=self.now + 500*86400)), 2)

    def test_ordinary_compression_and_later_deletion(self):
        event = self.memory.add(self.event())
        result = self.memory.retain(now=self.now + 8*86400)
        self.assertEqual(result["compressed"], 1)
        compact = self.memory.get(event["id"])
        self.assertEqual(compact["evidence"], {})
        self.assertEqual(compact["raw_state"], "compressed")
        self.assertEqual(compact["evidence_digest"], event["evidence_digest"])
        self.assertTrue(self.memory.retrieve("演示文稿", now=self.now + 8*86400))
        self.assertTrue(self.memory.add(self.event())["replayed"])
        self.assertEqual(self.memory.retain(now=self.now + 31*86400)["deleted"], 1)

    def test_compaction_is_not_reversed_on_reopen(self):
        mid = self.memory.add(self.event())["id"]
        self.memory.retain(now=self.now + 8*86400)
        self.store.close(); self.store = MemoryStore(self.database)
        self.memory = ObservationMemory(self.store)
        self.assertEqual(self.memory.get(mid)["evidence"], {})
        self.assertEqual(self.memory.get(mid)["raw_state"], "compressed")

    def test_fresh_identical_observation_restores_compressed_evidence(self):
        original = self.memory.add(self.event())
        self.memory.retain(now=self.now + 8*86400)
        fresh = self.memory.add(self.event(timestamp=self.now + 8*86400))
        self.assertEqual(original["id"], fresh["id"])
        self.assertEqual(fresh["raw_state"], "raw")
        self.assertEqual(fresh["evidence"], original["evidence"])

    def test_standalone_versions_current_and_late_event(self):
        old = self.memory.add(self.event(source_reference="/allowed/a.txt", version_id="v1"))
        new = self.memory.add(self.event(source_reference="/allowed/a.txt", version_id="v2", timestamp=self.now+10, evidence={"summary": "天河演示文稿新版"}))
        self.memory.add(self.event(source_reference="/allowed/a.txt", version_id="v0", timestamp=self.now-10))
        self.assertEqual([r["id"] for r in self.memory.records(now=self.now+20)], [new["id"]])
        self.assertEqual(len(self.memory.records(current_only=False, now=self.now+20)), 3)
        self.assertNotEqual(old["id"], new["id"])

    def test_document_source_versions_authoritative(self):
        ref = "/allowed/a.txt"
        self.store.db.execute("INSERT INTO source_versions VALUES('d1',?,'hash1',?,1,'unused1')", (ref, self.now))
        self.store.db.commit()
        old = self.memory.add(self.event(source_reference=ref, version_id="d1"))
        self.store.db.execute("UPDATE source_versions SET current=0 WHERE id='d1'")
        self.store.db.execute("INSERT INTO source_versions VALUES('d2',?,'hash2',?,1,'unused2')", (ref, self.now+10))
        self.store.db.commit()
        self.assertFalse(self.memory.retrieve("演示文稿", now=self.now+20))
        self.assertFalse(self.memory.records(now=self.now+20))
        self.assertIsNotNone(self.memory.get(old["id"]))

    def test_removed_document_version_never_resurrects_as_local(self):
        ref = "/allowed/a.txt"
        self.store.db.execute("INSERT INTO source_versions VALUES('d1',?,'hash1',?,1,'unused1')", (ref, self.now))
        self.store.db.commit()
        old = self.memory.add(self.event(source_reference=ref, version_id="d1"))
        self.store.db.execute("DELETE FROM source_versions")
        self.store.db.commit()
        self.assertFalse(self.memory.is_current(old, now=self.now))
        self.store.close(); self.store = MemoryStore(self.database)
        self.memory = ObservationMemory(self.store)
        self.assertFalse(self.memory.is_current(old, now=self.now))

    def test_explicit_conflict_only_current_observed_records(self):
        first = self.memory.add(self.event(source_reference="a.txt", version_id="a1", claim_key="天河:budget", claim_value="10万", evidence={"summary": "天河预算10万"}))
        second = self.memory.add(self.event(source_reference="b.txt", version_id="b1", claim_key="天河:budget", claim_value="20万", evidence={"summary": "天河预算20万"}))
        self.assertEqual(len(self.memory.conflicts(second["id"], now=self.now)), 1)
        self.memory.add(self.event(source_reference="a.txt", version_id="a2", timestamp=self.now+1, claim_key="天河:budget", claim_value="20万", evidence={"summary": "天河预算20万"}))
        self.assertEqual(self.memory.conflicts(first["id"], now=self.now+1), [])
        self.assertEqual(self.memory.conflicts(second["id"], now=self.now+1), [])

    def test_inferred_claim_does_not_create_observed_conflict(self):
        self.memory.add(self.event(claim_key="budget", claim_value="10万", evidence={"summary": "预算10万"}))
        inference = self.memory.add(self.event(epistemic="inferred", source="companion_model", claim_key="budget", claim_value="20万", evidence={"summary": "猜测预算20万"}))
        self.assertEqual(self.memory.conflicts(inference["id"], now=self.now), [])

    def test_claim_requires_actual_evidence_text(self):
        with self.assertRaises(ValueError):
            self.memory.add(self.event(claim_key="budget", claim_value="20万"))

    def test_forget_source_cascades_inferences_only(self):
        raw = self.memory.add(self.event(source_reference="a.txt"))
        inference = self.memory.add(self.event(source="companion_model", epistemic="inferred", derived_from=[raw["id"]]))
        self.assertEqual(self.memory.forget_source("a.txt"), 2)
        self.assertIsNone(self.memory.get(inference["id"]))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM observation_fts").fetchone()[0], 0)

    def test_expired_parent_prevents_live_inference_retrieval(self):
        raw = self.memory.add(self.event(expires_at=self.now+1))
        self.memory.add(self.event(source="companion_model", epistemic="inferred", derived_from=[raw["id"]], important=True))
        self.assertFalse(self.memory.retrieve("演示文稿", now=self.now+2))
        self.assertEqual(self.memory.retain(now=self.now+2)["deleted"], 2)

    def test_context_and_project_alias(self):
        target = self.memory.add(self.event(task_id="task-1"))
        self.memory.add(self.event(dedupe_key="noise", object="噪声演示文稿", evidence={"summary": "噪声演示文稿", "project": "海河"}, task_id="task-2"))
        self.assertEqual(self.memory.retrieve("老项目幻灯片", now=self.now)[0]["id"], target["id"])
        self.assertEqual([r["id"] for r in self.memory.retrieve("", context={"task_id": "task-1"}, now=self.now)], [target["id"]])

    def test_short_chinese_single_character(self):
        self.memory.add(self.event(evidence={"summary": "图表"}))
        self.assertTrue(self.memory.retrieve("图", now=self.now))

    def test_local_synonym_and_negative_query(self):
        target = self.memory.add(self.event())
        self.assertEqual(self.memory.retrieve("幻灯片", now=self.now)[0]["id"], target["id"])
        self.assertEqual(self.memory.retrieve("presentation", now=self.now)[0]["id"], target["id"])
        self.assertEqual(self.memory.retrieve("摄影展咖啡豆", now=self.now), [])

    def test_budget_counts_provenance_and_conflicts(self):
        for i in range(8):
            self.memory.add(self.event(dedupe_key=str(i), evidence={"summary": "天河演示文稿" + "更新"*500}))
        for budget in (128, 900, 1800, 4000):
            rows = self.memory.retrieve("演示文稿", limit=8, max_chars=budget, now=self.now)
            self.assertLessEqual(len(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))), budget)

    def test_permission_callback_rechecked_and_conflicts_not_leaked(self):
        self.memory.add(self.event(source_reference="private.txt", claim_key="budget", claim_value="10万", evidence={"summary": "预算10万"}))
        public = self.memory.add(self.event(source_reference="public.txt", claim_key="budget", claim_value="20万", evidence={"summary": "预算20万"}))
        allowed = ObservationMemory(self.store, source_allowed=lambda row: row["source_reference"] == "public.txt")
        rows = allowed.retrieve("预算", now=self.now)
        self.assertEqual([r["id"] for r in rows], [public["id"]])
        self.assertEqual(rows[0]["conflicts"], [])

    def test_app_scope_identity_survives_pack_and_compression(self):
        mid = self.memory.add(self.event(source="accessibility", object={"bundle_id": "example.app", "title": "演示文稿", "content_authorized": True}))["id"]
        allowed = ObservationMemory(self.store, source_allowed=lambda row: row["object"].get("bundle_id") == "example.app")
        self.assertEqual(allowed.retrieve("演示文稿", now=self.now)[0]["object"]["bundle_id"], "example.app")
        self.memory.retain(now=self.now + 8*86400)
        self.assertEqual(allowed.retrieve("演示文稿", now=self.now+8*86400)[0]["id"], mid)
        self.assertNotIn("title", self.memory.get(mid)["object"])
        self.assertTrue(self.memory.get(mid)["object"]["content_authorized"])

    def test_localpilot_report_is_not_semantically_observed(self):
        event = self.memory.add(self.event(source="localpilot", kind="task_result", object={"task_id": "task-9"}, important=True,
                                           evidence={"text": "模型声称任务完成", "source_reference": "localpilot:task:task-9", "epistemic": "reported", "metadata": {"task_id": "task-9", "localpilot_status": "completed"}}))
        self.assertEqual(event["epistemic"], "observed")
        self.assertEqual(event["evidence_epistemic"], "reported_unverified_text")
        self.assertEqual(event["task_id"], "task-9")
        self.assertEqual(event["source_reference"], "localpilot:task:task-9")
        self.assertIsNone(event["claim"])
        context = self.memory.retrieve("", context={"task_id": "task-9"}, now=self.now)
        self.assertEqual(context[0]["evidence_epistemic"], "reported_unverified_text")
        with self.assertRaises(ValueError):
            self.memory.add(self.event(source="localpilot", kind="task_result", claim_key="done", claim_value="完成", evidence={"text": "模型声称完成", "epistemic": "reported"}))

    def test_retention_limit_clear_preserves_existing_memory(self):
        old = self.store.add("preference", "existing V0.3", "explicit_user_statement")
        for i in range(20):
            self.memory.add(self.event(dedupe_key=str(i), timestamp=self.now+i))
        self.memory.retain(now=self.now+20, record_limit=3)
        self.assertEqual(self.memory.status()["records"], 3)
        self.memory.clear()
        self.assertEqual(self.memory.status()["records"], 0)
        self.assertEqual(self.store.records()[0]["id"], old)

    def test_get_history_is_current_refresh_and_forget(self):
        old = self.memory.add(self.event(expires_at=self.now+1))
        self.assertIsNotNone(self.memory.get(old["id"]))
        self.assertFalse(self.memory.is_current(old, now=self.now+2))
        self.assertEqual(self.memory.records(current_only=False, now=self.now+31*86400), [])
        self.assertEqual(len(self.memory.records(current_only=False, include_expired=True, now=self.now+31*86400)), 1)
        self.assertEqual(self.memory.forget(old["id"]), 1)
        self.assertFalse(self.memory.is_current(old, now=self.now))

    def test_strict_input_limits_and_nonfinite(self):
        for updates in ({"confidence": float("nan")}, {"timestamp": float("inf")}, {"important": 1},
                        {"dedupe_key": "x"*257}, {"unknown": True}, {"evidence": {"x": "x"*9000}},
                        {"version_id": "v1"}, {"evidence": ""}, {"source": ""}, {"sensitivity": []},
                        {"epistemic": {}}, {"timestamp": 10**10000}):
            with self.subTest(updates=updates):
                with self.assertRaises(ValueError):
                    self.memory.add(self.event(**updates))
        self.assertEqual(self.memory.status()["records"], 0)


if __name__ == "__main__":
    unittest.main()
