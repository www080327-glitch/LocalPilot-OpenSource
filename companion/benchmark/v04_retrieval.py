"""Synthetic, measured FTS/local-alias retrieval diagnostic, with raw rows.

Run: python -m companion.benchmark.v04_retrieval --output PATH
This tests retrieval only. It does not measure model semantics, AX coverage or
real-user helpfulness. Unsupported paraphrases are reported rather than hidden.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time

from companion.memory import MemoryStore
from companion.memory import observations
from companion.memory.observations import ObservationMemory, _tokens


def run():
    now = time.time()
    with tempfile.TemporaryDirectory(prefix="companion-v04-retrieval-") as folder:
        store = MemoryStore(Path(folder) / "memory.sqlite3")
        memory = ObservationMemory(store, aliases={"旧代号": "天河"})
        ids = {}

        def add(label, summary, project="天河", **fields):
            event = {"timestamp": now, "source": "synthetic_document_observer", "kind": "document_updated",
                     "object": {"document": label}, "evidence": {"summary": summary, "project": project},
                     "confidence": 1.0, "sensitivity": "private", "dedupe_key": label, **fields}
            ids[label] = memory.add(event)["id"]

        add("budget", "天河预算为12万元")
        add("slides", "天河演示文稿正在编辑")
        add("spreadsheet", "海河电子表格的数据校验完成", project="海河")
        add("error", "天河应用出现错误：文件无法打开")
        add("deadline", "天河截止日期为2026年11月1日")
        add("owner", "天河负责人是李明")
        add("single-character", "架构图已保存", project="绘图")
        add("old-version", "天河验收状态未完成", source_reference="/synthetic/status.txt", version_id="v1", timestamp=now-100)
        add("current-version", "天河验收状态已完成", source_reference="/synthetic/status.txt", version_id="v2")
        add("expired", "失效独有标识到期", expires_at=now-1, project="过期")
        add("other-budget", "海河预算为98万元", project="海河")
        add("inference", "猜测天河预算为100万元", source="companion_model", epistemic="inferred")
        for i in range(1000):
            add("noise-" + str(i), "天气气温记录第" + str(i) + "项", project="噪声", timestamp=now+i/1000)
        # Project-related noise forces alias retrieval to rank a field, rather
        # than receiving only a single candidate for a project-name keyword.
        for i in range(30):
            add("project-noise-" + str(i), "天河讨论记录第" + str(i) + "项")

        cases = [
            ("lexical-budget", "天河预算", {"budget"}, "lexical"),
            ("lexical-owner", "天河负责人", {"owner"}, "lexical"),
            ("single-character", "图", {"single-character"}, "short_chinese"),
            ("budget-synonym", "天河经费", {"budget"}, "local_alias"),
            ("presentation-synonym", "天河幻灯片", {"slides"}, "local_alias"),
            ("presentation-english", "presentation", {"slides"}, "local_alias"),
            ("spreadsheet-synonym", "海河表格", {"spreadsheet"}, "local_alias"),
            ("error-synonym", "天河报错", {"error"}, "local_alias"),
            ("deadline-synonym", "天河到期时间", {"deadline"}, "local_alias"),
            ("project-alias", "旧代号预算", {"budget"}, "project_alias"),
            ("version-filter", "天河验收状态", {"current-version"}, "version"),
            ("negative-coffee", "咖啡豆品牌", set(), "negative"),
            ("negative-travel", "冰岛酒店", set(), "negative"),
            ("negative-expired", "失效独有标识", set(), "negative_expiry"),
            ("unsupported-paraphrase", "银子花到哪了", {"budget"}, "unsupported_semantic"),
        ]

        def baseline(query):
            tokens = sorted(set(_tokens(query)))[:64]
            if not tokens:
                return []
            expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
            rows = store.db.execute("SELECT e.*,bm25(observation_fts) AS rank FROM observation_fts JOIN observation_events e ON e.id=observation_fts.id WHERE observation_fts MATCH ? ORDER BY rank LIMIT 2000", (expression,)).fetchall()
            rows = [memory._decode(dict(r)) for r in rows]
            named = {r[0] for r in store.db.execute("SELECT DISTINCT project FROM observation_events WHERE project<>''") if len(r[0]) >= 2 and r[0] in query}
            rows = [r for r in rows if memory.is_current(r, now=now) and (len(named) != 1 or r["project"] in named)]
            rows.sort(key=lambda r: r["epistemic"] != "observed")
            return [r["id"] for r in rows[:3]]

        reverse = {mid: label for label, mid in ids.items()}
        results = []
        for label, query, expected, category in cases:
            base_start = time.perf_counter()
            base = baseline(query)
            base_ms = (time.perf_counter()-base_start)*1000
            improved_start = time.perf_counter()
            retrieved = memory.retrieve(query, limit=3, max_chars=4000, now=now)
            improved_ms = (time.perf_counter()-improved_start)*1000
            returned = [reverse[row["id"]] for row in retrieved]
            baseline_labels = [reverse[mid] for mid in base]
            results.append({"id": label, "query": query, "category": category, "expected": sorted(expected),
                            "lexical": baseline_labels, "fts_local_alias": returned,
                            "lexical_hit": bool(expected & set(baseline_labels)) if expected else not baseline_labels,
                            "alias_hit": bool(expected & set(returned)) if expected else not returned,
                            "lexical_ms": base_ms, "alias_ms": improved_ms})
        scored = [r for r in results if r["category"] != "unsupported_semantic"]
        positives = [r for r in scored if r["expected"]]
        negatives = [r for r in scored if not r["expected"]]
        output = {"status": "MEASURED_SYNTHETIC_RETRIEVAL", "timestamp": now, "records": memory.status()["records"],
                  "fixture_sha256": hashlib.sha256(json.dumps(cases, default=sorted, ensure_ascii=False).encode()).hexdigest(),
                  "implementation_sha256": hashlib.sha256(Path(observations.__file__).read_bytes()).hexdigest(),
                  "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "comparison_scope": "FTS exact tokens vs FTS with explicit local synonyms/project aliases; same synthetic corpus/current filters/top3",
                  "positive_count": len(positives), "negative_count": len(negatives),
                  "lexical_recall_at_3": sum(r["lexical_hit"] for r in positives)/len(positives),
                  "alias_recall_at_3": sum(r["alias_hit"] for r in positives)/len(positives),
                  "lexical_top1_accuracy": sum(bool(r["lexical"] and r["lexical"][0] in r["expected"]) for r in positives)/len(positives),
                  "alias_top1_accuracy": sum(bool(r["fts_local_alias"] and r["fts_local_alias"][0] in r["expected"]) for r in positives)/len(positives),
                  "lexical_returned_precision": sum(len(set(r["lexical"]) & set(r["expected"])) for r in positives)/sum(len(r["lexical"]) for r in positives),
                  "alias_returned_precision": sum(len(set(r["fts_local_alias"]) & set(r["expected"])) for r in positives)/sum(len(r["fts_local_alias"]) for r in positives),
                  "lexical_negative_correct": sum(r["lexical_hit"] for r in negatives),
                  "alias_negative_correct": sum(r["alias_hit"] for r in negatives),
                  "alias_median_ms": statistics.median(r["alias_ms"] for r in results),
                  "alias_max_ms": max(r["alias_ms"] for r in results),
                  "unsupported_semantic": [r for r in results if r["category"] == "unsupported_semantic"],
                  "general_semantic_similarity": "UNKNOWN; no embedding or learned model tested",
                  "limitation": "OR-token queries still return some project-related noise; top3 source-target precision is reported and remains limited",
                  "model_calls": 0, "raw_results": results,
                  "integrity_check": store.db.execute("PRAGMA integrity_check").fetchone()[0]}
        store.close()
        return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
