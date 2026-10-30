from typing import Protocol
import re
import time
import json
from .reliability import provenance


class Retriever(Protocol):
    def retrieve(self, query: str, limit: int, max_chars: int) -> list[dict]: ...


def terms(text):
    latin = re.findall(r"[a-z0-9_]{2,}", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    return set(latin + [w[i:i+2] for w in chinese for i in range(max(1, len(w)-1))])


SYNONYMS = (("经费", "预算"), ("费用额度", "预算"), ("负责人员", "负责人"),
            ("到期时间", "截止日期"), ("供货商", "供应商"), ("阻碍", "阻塞"))


def expand_query(query, aliases=None):
    # Explicit local dictionary only. No learned aliases or cloud/embedding lookup.
    for alias, project in sorted((aliases or {}).items(), key=lambda p: -len(p[0])):
        query = query.replace(alias, project)
    additions = [target for original, target in SYNONYMS if original in query]
    return query + (" " + " ".join(additions) if additions else "")


def document_project(row):
    from pathlib import Path
    body = row["metadata"].get("index_text", row["summary"])
    match = re.search(r"(?:项目|project)\s*[:：]\s*([^\n；;]+)", body, re.I)
    return match.group(1).strip() if match else Path(row["source_reference"]).parent.name


class LexicalRetriever:
    """Bounded lexical search. Replace through Retriever for vectors later."""
    def __init__(self, store, source_allowed=None, aliases=None):
        self.store = store
        self.source_allowed = source_allowed or (lambda row: True)
        self.aliases = aliases or {}

    def retrieve(self, query, limit=5, max_chars=4000):
        query = expand_query(query, self.aliases)
        tokens = terms(query)
        recent = any(w in query for w in ("最近", "忙什么", "recent", "working on"))
        ranked = []
        candidates = {row["id"]:row for row in self.store.candidates(tokens)}
        if recent:
            candidates.update({row["id"]:row for row in self.store.records(2000, ["document","project","computer_event"])})
        for row in candidates.values():
            if not self.source_allowed(row) or not self.store.is_current(row) or row["source"] in {"companion_model", "companion_greeting_rule", "companion_fact_guard"}:
                continue
            text = row["metadata"].get("index_text", row["summary"]) + " " + row["source_reference"]
            overlap = len(tokens & terms(text))
            score = overlap * 3 + (1 if row["epistemic"] == "factual" else 0)
            if recent and row["type"] in {"document", "project", "computer_event"}:
                score += 5 / (1 + max(0, time.time() - row["timestamp"]) / 86400)
            if overlap or (recent and row["type"] in {"document", "project", "computer_event"}):
                ranked.append((score, row["timestamp"], row))
        ranked.sort(key=lambda v: (v[0], v[1]), reverse=True)
        return self.pack([r[2] for r in ranked], tokens, limit, max_chars)

    def pack(self, ranked, tokens, limit, max_chars):
        out, used = [], 0
        for row in ranked:
            if len(out) >= limit or used >= max_chars:
                break
            # All injected fields count against the budget, including source paths.
            fulltext = row["metadata"].get("index_text", "")
            if fulltext and not (tokens & terms(row["summary"])):
                positions = [fulltext.lower().find(t) for t in tokens if fulltext.lower().find(t) >= 0]
                if positions:
                    pos = max(0, min(positions)-120)
                    row["summary"] = "[检索原文片段] " + fulltext[pos:pos+1200]
            evidence = provenance(row, tokens)
            # Detection timestamps and DB row numbers stay in the audit database.
            # Keep both memory pointers and values in injected context; redundant
            # bookkeeping must not squeeze the fourth source into a few characters.
            conflicts = [{k:c[k] for k in ("claim_key", "older_id", "newer_id", "older_value", "newer_value")}
                         for c in self.store.active_conflicts(row["id"])]
            from .evidence import describe
            identity = describe(row)
            row = {k: row[k] for k in ("id", "type", "timestamp", "source_reference", "summary", "confidence", "epistemic")}
            evidence.pop("derived_summary")
            row.update(provenance=evidence, conflicts=conflicts, evidence_type=identity)
            overhead = len(str({k: v for k, v in row.items() if k != "summary"}))
            room = max_chars - used - overhead - 32
            if room <= 0:
                break
            row["summary"] = row["summary"][:room]
            used += len(str(row))
            out.append(row)
        return out


class BM25Retriever(LexicalRetriever):
    """SQLite FTS5 with Chinese bigrams; the same provenance and budget as baseline."""
    def retrieve(self, query, limit=5, max_chars=4000):
        query = expand_query(query, self.aliases)
        tokens = terms(query)
        if not tokens:
            return []
        expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in sorted(tokens)[:64])
        rows = self.store.db.execute("SELECT m.*,bm25(memory_fts) AS relevance FROM memory_fts JOIN memories m ON m.id=memory_fts.id LEFT JOIN source_versions v ON v.memory_id=m.id WHERE memory_fts MATCH ? AND (v.id IS NULL OR v.current=1) ORDER BY relevance LIMIT 2000", (expression,)).fetchall()
        ranked = [dict(r) | {"metadata":json.loads(r["metadata"])} for r in rows]
        ranked = [r for r in ranked if self.source_allowed(r) and self.store.is_current(r) and r["source"] not in {"companion_model", "companion_greeting_rule", "companion_fact_guard"}]
        from pathlib import Path
        # A named directory project is a relevance constraint, not a new factual claim.
        projects = {document_project(r) for r in ranked
                    if r["type"] == "document" and len(document_project(r)) >= 2 and document_project(r) in query}
        if len(projects) == 1:
            ranked = [r for r in ranked if document_project(r) in projects]
        fields = {field for field, labels in (("budget", ("预算", "budget")), ("owner", ("负责人", "owner")), ("deadline", ("截止日期", "deadline"))) if any(label in query.lower() for label in labels)}
        field_ids = {r[0] for r in self.store.db.execute("SELECT DISTINCT memory_id FROM claims WHERE " + " OR ".join("claim_key LIKE ?" for _ in fields), tuple("%:" + field for field in fields))} if fields else set()
        ranked.sort(key=lambda r: (r["epistemic"] != "factual",
                                  not r["source_reference"] or Path(r["source_reference"]).name not in query,
                                  bool(fields) and r["id"] not in field_ids,
                                  r["relevance"], -r["timestamp"]))
        if not ranked and any(w in query for w in ("最近", "忙什么", "recent", "working on")):
            return LexicalRetriever(self.store, self.source_allowed).retrieve(query, limit, max_chars)
        return self.pack(ranked, tokens, limit, max_chars)

    def pack(self, ranked, tokens, limit, max_chars):
        # Choose a query-rich window even when a generic project name occurs in the prefix.
        # Exact source locations still refer to the original extracted text.
        selected = []
        for original in ranked:
            row = dict(original)
            fulltext = row["metadata"].get("index_text", "")
            if len(fulltext) > 1200 and tokens:
                lower = fulltext.lower()
                positions = set()
                for token in tokens:
                    # All occurrences up to a fixed host budget, not just the first.
                    start = 0
                    for _ in range(512):
                        pos = lower.find(token, start)
                        if pos < 0: break
                        positions.add(max(0, pos - 100))
                        start = pos + max(1, len(token))
                if positions:
                    ordered = sorted(positions, key=lambda p: (len(tokens & terms(fulltext[p:p+600])), p), reverse=True)
                    chosen = []
                    for pos in ordered:
                        if all(abs(pos - old) >= 600 for old in chosen):
                            chosen.append(pos)
                        if len(chosen) == 2: break
                    row["summary"] = "[检索原文片段] " + "\n[另一命中]\n".join(fulltext[p:p+600] for p in sorted(chosen))
                    row["metadata"] = row["metadata"] | {"matched_windows": [(p, p+600) for p in chosen]}
            selected.append(row)
        return super().pack(selected, tokens, limit, max_chars)
