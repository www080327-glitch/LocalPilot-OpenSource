"""Bounded observation memory; facts describe evidence, never independent truth.

This owns only observation_* tables on the existing MemoryStore connection. The
service owns the connection and performs permission/sensitive-content checks
before calling add(), and must recheck permission before using retrieved rows.
No embeddings, model calls, source-file access or background workers are used.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from typing import Protocol


class ObservationRetriever(Protocol):
    def retrieve(self, query: str, limit: int = 5, max_chars: int = 4000,
                 context: dict | None = None, now: float | None = None) -> list[dict]: ...


# Auditable local aliases, not learned semantic similarity. Extension/replacement
# happens through aliases or the ObservationRetriever interface.
ALIAS_GROUPS = (
    ("演示文稿", "幻灯片", "ppt", "presentation"),
    ("电子表格", "表格", "excel", "spreadsheet"),
    ("预算", "经费", "费用额度", "budget"),
    ("负责人", "负责人员", "owner"),
    ("截止日期", "到期时间", "deadline"),
    ("错误", "报错", "异常", "error"),
    ("阻塞", "阻碍", "blocked"),
)
SENSITIVITY = {"public": 0, "normal": 1, "private": 2, "sensitive": 3, "unknown": 4}
FIELDS = {"timestamp", "source", "kind", "object", "evidence", "confidence",
          "sensitivity", "dedupe_key", "epistemic", "important", "expires_at",
          "source_reference", "version_id", "claim_key", "claim_value",
          "derived_from", "summary", "project", "task_id", "occurrence_id"}


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value, name, minimum=0):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= minimum
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"Invalid {name}")
    return float(value)


def _text(value, name, maximum, empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or "\x00" in value:
        raise ValueError(f"Invalid {name}")
    return value


def _json(value, name, maximum=8192):
    def check(part, depth=0):
        if depth > 4:
            raise ValueError(f"{name} exceeds depth limit")
        if isinstance(part, dict):
            if len(part) > 64:
                raise ValueError(f"{name} exceeds field limit")
            for key, item in part.items():
                _text(key, name + " key", 128, False)
                check(item, depth + 1)
        elif isinstance(part, list):
            if len(part) > 64:
                raise ValueError(f"{name} exceeds item limit")
            for item in part:
                check(item, depth + 1)
        elif isinstance(part, str):
            _text(part, name, maximum)
        elif part is None or type(part) is bool:
            pass
        elif type(part) in (int, float):
            if not math.isfinite(part):
                raise ValueError(f"Invalid {name} number")
        else:
            raise ValueError(f"Invalid {name} value")
    check(value)
    encoded = _dump(value)
    if len(encoded.encode("utf-8")) > maximum:
        raise ValueError(f"{name} exceeds byte limit")
    return encoded


def _flatten(value):
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value)
    return str(value) if value is not None else ""


def _tokens(text):
    lower = text.casefold()
    latin = re.findall(r"[a-z0-9_]+", lower)
    chinese = re.findall(r"[\u4e00-\u9fff]+", lower)
    return latin + [run[i:i+2] for run in chinese for i in range(max(1, len(run)-1))]


def _index(text):
    # Unigrams are used only for single-character queries; bigrams remain primary.
    return " ".join(_tokens(text) + re.findall(r"[\u4e00-\u9fff]", text) +
                    [f"alias{i}" for i, group in enumerate(ALIAS_GROUPS)
                     if any(_contains(text, word) for word in group)])


def _contains(text, word):
    lower = text.casefold()
    if re.fullmatch(r"[a-z0-9_]+", word):
        return bool(re.search(r"(?<![a-z0-9_])" + re.escape(word) + r"(?![a-z0-9_])", lower))
    return word in lower


class ObservationMemory:
    """Immutable evidence plus merged event occurrences and explicit claim edges."""
    schema_version = 1

    def __init__(self, store, aliases=None, source_allowed=None):
        self.store, self.db = store, store.db
        self.source_allowed = source_allowed or (lambda row: True)
        self.aliases = aliases or {}
        if not isinstance(self.aliases, dict) or len(self.aliases) > 100:
            raise ValueError("Invalid alias mapping")
        for key, value in self.aliases.items():
            _text(key, "alias", 80, False); _text(value, "alias target", 80, False)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS observation_schema (id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL);
        INSERT OR IGNORE INTO observation_schema VALUES(1,1);
        CREATE TABLE IF NOT EXISTS observation_retention_policy (id INTEGER PRIMARY KEY CHECK(id=1),ttl_days REAL NOT NULL);
        INSERT OR IGNORE INTO observation_retention_policy VALUES(1,30);
        CREATE TABLE IF NOT EXISTS observation_events (
          id TEXT PRIMARY KEY,dedupe_index TEXT NOT NULL UNIQUE,dedupe_key TEXT NOT NULL,
          first_timestamp REAL NOT NULL,last_timestamp REAL NOT NULL,source TEXT NOT NULL,
          kind TEXT NOT NULL,object_json TEXT NOT NULL,evidence_json TEXT NOT NULL,
          evidence_digest TEXT NOT NULL,summary TEXT NOT NULL,confidence REAL NOT NULL,
          sensitivity TEXT NOT NULL,epistemic TEXT NOT NULL,important INTEGER NOT NULL,
          expires_at REAL,source_reference TEXT NOT NULL,version_id TEXT NOT NULL,
          project TEXT NOT NULL,task_id TEXT NOT NULL,occurrences INTEGER NOT NULL,
          raw_state TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS observation_event_time ON observation_events(last_timestamp);
        CREATE INDEX IF NOT EXISTS observation_event_source ON observation_events(source_reference,version_id);
        CREATE INDEX IF NOT EXISTS observation_event_dedupe ON observation_events(source,dedupe_key);
        CREATE TABLE IF NOT EXISTS observation_occurrences (
          memory_id TEXT NOT NULL,occurrence_token TEXT NOT NULL,timestamp REAL NOT NULL,
          PRIMARY KEY(memory_id,occurrence_token));
        CREATE INDEX IF NOT EXISTS observation_occurrence_time ON observation_occurrences(memory_id,timestamp);
        CREATE TABLE IF NOT EXISTS observation_occurrence_archive (
          memory_id TEXT PRIMARY KEY,watermark REAL NOT NULL,folded_tokens INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS observation_versions (
          reference TEXT NOT NULL,version_id TEXT NOT NULL,timestamp REAL NOT NULL,current INTEGER NOT NULL,
          PRIMARY KEY(reference,version_id));
        CREATE TABLE IF NOT EXISTS observation_document_links (
          version_id TEXT NOT NULL,reference TEXT NOT NULL,PRIMARY KEY(version_id,reference));
        CREATE TABLE IF NOT EXISTS observation_claims (
          memory_id TEXT PRIMARY KEY,claim_key TEXT NOT NULL,claim_value TEXT NOT NULL,epistemic TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS observation_claim_key ON observation_claims(claim_key);
        CREATE TABLE IF NOT EXISTS observation_conflicts (
          older_id TEXT NOT NULL,newer_id TEXT NOT NULL,claim_key TEXT NOT NULL,
          PRIMARY KEY(older_id,newer_id,claim_key));
        CREATE TABLE IF NOT EXISTS observation_derivations (
          memory_id TEXT NOT NULL,parent_id TEXT NOT NULL,PRIMARY KEY(memory_id,parent_id));
        """)
        if self.db.execute("SELECT version FROM observation_schema WHERE id=1").fetchone()[0] != self.schema_version:
            raise ValueError("Unsupported observation schema version")
        self.db.execute("INSERT OR IGNORE INTO observation_document_links SELECT e.version_id,e.source_reference FROM observation_events e JOIN source_versions v ON v.id=e.version_id AND v.reference=e.source_reference")
        self.fts_available = True
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS observation_fts USING fts5(id UNINDEXED,tokens)")
        except Exception as exc:
            import sqlite3
            if not isinstance(exc, sqlite3.OperationalError) or "no such module" not in str(exc):
                raise
            self.fts_available = False
        if self.fts_available:
            for row in self.db.execute("SELECT * FROM observation_events WHERE id NOT IN (SELECT id FROM observation_fts)").fetchall():
                self._reindex(dict(row))
        # Bound token rows from pre-watermark databases without changing ids,
        # aggregate occurrence counts, raw evidence or first/last timestamps.
        for row in self.db.execute("SELECT memory_id FROM observation_occurrences GROUP BY memory_id HAVING count(*)>256").fetchall():
            self._archive_occurrences(row[0])
        self.db.commit()

    def _archive_occurrences(self, memory_id):
        overflow = self.db.execute("SELECT timestamp FROM observation_occurrences WHERE memory_id=? ORDER BY timestamp DESC,occurrence_token DESC LIMIT -1 OFFSET 256", (memory_id,)).fetchall()
        if not overflow:
            return
        watermark = max(row[0] for row in overflow)
        # Fold complete timestamp boundaries. Tokens with identical timestamps
        # can leave fewer than256 retained rows; no partial boundary is trusted.
        count = self.db.execute("DELETE FROM observation_occurrences WHERE memory_id=? AND timestamp<=?", (memory_id, watermark)).rowcount
        self.db.execute("INSERT INTO observation_occurrence_archive VALUES(?,?,?) ON CONFLICT(memory_id) DO UPDATE SET watermark=max(watermark,excluded.watermark),folded_tokens=folded_tokens+excluded.folded_tokens", (memory_id, watermark, count))

    def _reindex(self, row):
        if not self.fts_available:
            return
        body = row["summary"] + " " + _flatten(json.loads(row["object_json"])) + " " + row["source_reference"] + " " + row["project"]
        if row["raw_state"] == "raw":
            body += " " + _flatten(json.loads(row["evidence_json"]))
        self.db.execute("DELETE FROM observation_fts WHERE id=?", (row["id"],))
        self.db.execute("INSERT INTO observation_fts VALUES(?,?)", (row["id"], _index(body)))

    def add(self, event):
        if not isinstance(event, dict) or set(event) - FIELDS:
            raise ValueError("Invalid observation fields")
        for key in ("timestamp", "source", "kind", "object", "evidence", "confidence", "sensitivity", "dedupe_key"):
            if key not in event:
                raise ValueError(f"Missing observation {key}")
        timestamp = _number(event["timestamp"], "timestamp")
        source = _text(event["source"], "source", 128, False)
        kind = _text(event["kind"], "kind", 80, False)
        dedupe = _text(event["dedupe_key"], "dedupe_key", 256, False)
        confidence = _number(event["confidence"], "confidence")
        if confidence > 1 or not isinstance(event["sensitivity"], str) or event["sensitivity"] not in SENSITIVITY:
            raise ValueError("Invalid confidence/sensitivity")
        if not isinstance(event.get("epistemic", "observed"), str):
            raise ValueError("Invalid observation epistemic status")
        epistemic = {"factual": "observed", "inference": "inferred"}.get(event.get("epistemic"), event.get("epistemic", "observed"))
        if epistemic not in {"observed", "inferred"}:
            raise ValueError("Invalid observation epistemic status")
        if epistemic == "observed" and source.casefold().startswith(("model", "companion_model", "companion_reflection")):
            raise ValueError("Model output cannot be observed evidence")
        from .evidence import is_question
        if source == "explicit_user_statement" and kind == "user_fact" and is_question(event.get("summary", event["evidence"].get("summary", "") if isinstance(event["evidence"], dict) else "")):
            raise ValueError("Questions cannot become confirmed observation facts")
        important = event.get("important", False)
        if type(important) is not bool:
            raise ValueError("important must be boolean")
        # Explicit user statements are durable unless explicitly given an expiry.
        important = important or (kind in {"user_fact", "preference"} and source == "explicit_user_statement")
        expires = event.get("expires_at")
        if expires is not None:
            expires = _number(expires, "expires_at")
        obj = _json(event["object"], "object", 4096)
        evidence = _json(event["evidence"], "evidence")
        if epistemic == "observed" and not _flatten(event["evidence"]).strip():
            raise ValueError("Observation requires evidence")
        evidence_dict = event["evidence"] if isinstance(event["evidence"], dict) else {}
        object_dict = event["object"] if isinstance(event["object"], dict) else {}
        reference = _text(event.get("source_reference") or evidence_dict.get("source_reference", ""), "source_reference", 2048)
        version = _text(event.get("version_id") or evidence_dict.get("version_id", ""), "version_id", 128)
        if version and not reference:
            raise ValueError("Version requires a source reference")
        metadata = evidence_dict.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        project = _text(event.get("project", evidence_dict.get("project", object_dict.get("project", ""))), "project", 256)
        task = _text(event.get("task_id", evidence_dict.get("task_id", object_dict.get("task_id", metadata.get("task_id", "")))), "task_id", 128)
        summary = _text(event.get("summary", evidence_dict.get("summary", _flatten(event["evidence"])[:600])), "summary", 1200)
        parents = event.get("derived_from", [])
        if not isinstance(parents, list) or len(parents) > 32:
            raise ValueError("Invalid derivation parents")
        parents = sorted(set(_text(p, "parent id", 128, False) for p in parents))
        for parent in parents:
            row = self.get(parent)
            if not row or (epistemic == "observed" and row["epistemic"] != "observed"):
                raise ValueError("Inference cannot become observed evidence")
        claim_key = _text(event.get("claim_key", ""), "claim_key", 256)
        claim_value = _text(event.get("claim_value", ""), "claim_value", 512)
        if bool(claim_key) != bool(claim_value):
            raise ValueError("Claim requires both key and value")
        if claim_key and epistemic == "observed" and (evidence_dict.get("epistemic") in {"reported", "inferred"} or (source == "localpilot" and kind == "task_result")):
            raise ValueError("Reported model text cannot become an observed claim")
        if claim_key and epistemic == "observed" and claim_value not in _flatten(event["evidence"]):
            raise ValueError("Explicit claim must appear in evidence")
        digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        identity = [source, kind, dedupe, obj, digest, epistemic, reference, version, project, task, claim_key, claim_value, parents]
        index = hashlib.sha256(_dump(identity).encode("utf-8")).hexdigest()
        occurrence = event.get("occurrence_id", "")
        _text(occurrence, "occurrence_id", 256)
        token = hashlib.sha256((occurrence or _dump(timestamp)).encode("utf-8")).hexdigest()
        existing = self.db.execute("SELECT * FROM observation_events WHERE dedupe_index=?", (index,)).fetchone()
        collision = bool(self.db.execute("SELECT 1 FROM observation_events WHERE source=? AND dedupe_key=? AND dedupe_index<>?", (source, dedupe, index)).fetchone())
        with self.db:
            archived_unknown = False
            if existing:
                mid = existing["id"]
                replayed = bool(self.db.execute("SELECT 1 FROM observation_occurrences WHERE memory_id=? AND occurrence_token=?", (mid, token)).fetchone())
                archive = self.db.execute("SELECT watermark FROM observation_occurrence_archive WHERE memory_id=?", (mid,)).fetchone()
                archived_unknown = bool(not replayed and archive and timestamp <= archive[0])
                if not replayed and not archived_unknown:
                    # A differing confidence never promotes the original evidence.
                    sensitive = max((event["sensitivity"], existing["sensitivity"]), key=SENSITIVITY.get)
                    expiry_values = [v for v in (expires, existing["expires_at"]) if v is not None]
                    self.db.execute("UPDATE observation_events SET first_timestamp=min(first_timestamp,?),last_timestamp=max(last_timestamp,?),occurrences=occurrences+1,confidence=min(confidence,?),sensitivity=?,important=max(important,?),expires_at=? WHERE id=?", (timestamp, timestamp, confidence, sensitive, int(important), min(expiry_values) if expiry_values else None, mid))
                    if existing["raw_state"] == "compressed" and timestamp > existing["last_timestamp"]:
                        # Same digest/identity proves this fresh observation has
                        # the identical raw evidence, never substituted inference.
                        self.db.execute("UPDATE observation_events SET evidence_json=?,object_json=?,summary=?,raw_state='raw' WHERE id=?", (evidence, obj, summary, mid))
                        self._reindex(dict(self.db.execute("SELECT * FROM observation_events WHERE id=?", (mid,)).fetchone()))
                merged = True
            else:
                mid, replayed, merged = uuid.uuid4().hex, False, False
                self.db.execute("INSERT INTO observation_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (mid, index, dedupe, timestamp, timestamp, source, kind, obj, evidence, digest, summary, confidence, event["sensitivity"], epistemic, int(important), expires, reference, version, project, task, 1, "raw"))
                for parent in parents:
                    self.db.execute("INSERT INTO observation_derivations VALUES(?,?)", (mid, parent))
                if claim_key:
                    self.db.execute("INSERT INTO observation_claims VALUES(?,?,?,?)", (mid, claim_key, claim_value, epistemic))
                    if epistemic == "observed":
                        # Current cross-source observations and adjacent revision
                        # edges only; no quadratic all-history conflict expansion.
                        prior = self.db.execute("SELECT e.*,c.claim_value FROM observation_claims c JOIN observation_events e ON e.id=c.memory_id WHERE c.claim_key=? AND c.claim_value<>? AND c.epistemic='observed' AND e.id<>? ORDER BY e.last_timestamp DESC LIMIT 256", (claim_key, claim_value, mid)).fetchall()
                        own_revision = False
                        for old in prior:
                            oldrow = self._decode(dict(old))
                            same = bool(reference) and reference == old["source_reference"]
                            if (same and not own_revision) or (not same and self._current(oldrow, timestamp)):
                                self.db.execute("INSERT OR IGNORE INTO observation_conflicts VALUES(?,?,?)", (old["id"], mid, claim_key))
                            if same:
                                own_revision = True
                self._reindex(dict(self.db.execute("SELECT * FROM observation_events WHERE id=?", (mid,)).fetchone()))
            if not archived_unknown:
                self.db.execute("INSERT OR IGNORE INTO observation_occurrences VALUES(?,?,?)", (mid, token, timestamp))
                self._archive_occurrences(mid)
            if reference and version:
                if self.db.execute("SELECT 1 FROM source_versions WHERE id=? AND reference=?", (version, reference)).fetchone():
                    self.db.execute("INSERT OR IGNORE INTO observation_document_links VALUES(?,?)", (version, reference))
                known = self.db.execute("SELECT timestamp FROM observation_versions WHERE reference=? AND version_id=?", (reference, version)).fetchone()
                if not known:
                    self.db.execute("INSERT INTO observation_versions VALUES(?,?,?,0)", (reference, version, timestamp))
                newest = self.db.execute("SELECT version_id FROM observation_versions WHERE reference=? ORDER BY timestamp DESC,rowid DESC LIMIT 1", (reference,)).fetchone()[0]
                self.db.execute("UPDATE observation_versions SET current=(version_id=?) WHERE reference=?", (newest, reference))
        result = self.get(mid)
        result.update(merged=merged, replayed=replayed, new_occurrence=not replayed and not archived_unknown, collision=collision, archived_unknown=archived_unknown)
        return result

    def _decode(self, row):
        out = {k: row[k] for k in ("id", "dedupe_key", "first_timestamp", "last_timestamp", "source", "kind", "summary", "confidence", "sensitivity", "epistemic", "expires_at", "source_reference", "version_id", "project", "task_id", "occurrences", "raw_state", "evidence_digest")}
        out.update(timestamp=row["last_timestamp"], important=bool(row["important"]), object=json.loads(row["object_json"]), evidence=json.loads(row["evidence_json"]))
        proof = out["evidence"] if isinstance(out["evidence"], dict) else {}
        out["evidence_epistemic"] = "reported_unverified_text" if proof.get("epistemic") == "reported" or (row["source"] == "localpilot" and row["kind"] == "task_result") else ("source_record" if row["epistemic"] == "observed" else "unverified_inference")
        claim = self.db.execute("SELECT claim_key,claim_value FROM observation_claims WHERE memory_id=?", (row["id"],)).fetchone()
        out["claim"] = dict(claim) if claim else None
        out["derived_from"] = [r[0] for r in self.db.execute("SELECT parent_id FROM observation_derivations WHERE memory_id=?", (row["id"],))]
        archive = self.db.execute("SELECT watermark,folded_tokens FROM observation_occurrence_archive WHERE memory_id=?", (row["id"],)).fetchone()
        out["occurrence_archive"] = dict(archive) | {"late_count_accuracy": "UNKNOWN", "policy": "timestamp<=watermark is conservatively ignored unless an exact retained token matches"} if archive else None
        out["provenance"] = "OBSERVED_SOURCE_RECORD" if row["epistemic"] == "observed" else "UNVERIFIED_INFERENCE"
        from .evidence import describe
        out["evidence_type"] = describe(out)
        return out

    def get(self, memory_id):
        row = self.db.execute("SELECT * FROM observation_events WHERE id=?", (memory_id,)).fetchone()
        return self._decode(dict(row)) if row else None

    def is_current(self, row_or_id, now=None):
        """Revalidation helper; get() itself is an administrative history read."""
        row = self.get(row_or_id) if isinstance(row_or_id, str) else row_or_id
        if not row:
            return False
        now = time.time() if now is None else _number(now, "now")
        # Refresh from DB so callers cannot pass a stale cached event dictionary.
        current = self.get(row["id"])
        return bool(current and self._current(current, now) and self.source_allowed(current))

    def _current(self, row, now, seen=None):
        # Default TTL also applies before the maintenance job has run.
        expiry = row["expires_at"]
        if expiry is None and not row["important"]:
            expiry = row["last_timestamp"] + self._ttl_seconds()
        if expiry is not None and now >= expiry:
            return False
        if row["version_id"]:
            known = self.db.execute("SELECT current FROM source_versions WHERE id=? AND reference=?", (row["version_id"], row["source_reference"])).fetchone()
            if known is not None:
                if not known[0]:
                    return False
            else:
                # A linked document version removed by retention/forget must not
                # be revived through the independent event version registry.
                if self.db.execute("SELECT 1 FROM observation_document_links WHERE version_id=? AND reference=?", (row["version_id"], row["source_reference"])).fetchone() or self.db.execute("SELECT 1 FROM source_versions WHERE reference=?", (row["source_reference"],)).fetchone():
                    return False
                local = self.db.execute("SELECT current FROM observation_versions WHERE reference=? AND version_id=?", (row["source_reference"], row["version_id"])).fetchone()
                if not local or not local[0]:
                    return False
        seen = set() if seen is None else set(seen)
        if row["id"] in seen:
            return False
        seen.add(row["id"])
        for mid in row["derived_from"]:
            parent = self.get(mid)
            if not parent or not self._current(parent, now, seen):
                return False
        return True

    def _ttl_seconds(self):
        return self.db.execute("SELECT ttl_days FROM observation_retention_policy WHERE id=1").fetchone()[0] * 86400

    def records(self, limit=100, current_only=True, include_expired=False, now=None):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Invalid observation record limit")
        now = time.time() if now is None else _number(now, "now")
        out = []
        for raw in self.db.execute("SELECT * FROM observation_events ORDER BY last_timestamp DESC,rowid DESC"):
            row = self._decode(dict(raw))
            current = self._current(row, now)
            expiry = row["expires_at"]
            if expiry is None and not row["important"]:
                expiry = row["last_timestamp"] + self._ttl_seconds()
            if (current_only and not current) or (not include_expired and expiry is not None and now >= expiry):
                continue
            row["current"] = current
            if self.source_allowed(row):
                out.append(row)
                if len(out) >= limit:
                    break
        return out

    def conflicts(self, memory_id, now=None):
        now = time.time() if now is None else _number(now, "now")
        out = []
        for conflict in self.db.execute("SELECT * FROM observation_conflicts WHERE older_id=? OR newer_id=?", (memory_id, memory_id)):
            old, new = self.get(conflict["older_id"]), self.get(conflict["newer_id"])
            if old and new and self._current(old, now) and self._current(new, now) and self.source_allowed(old) and self.source_allowed(new):
                out.append(dict(conflict) | {"older_value": old["claim"]["claim_value"], "newer_value": new["claim"]["claim_value"]})
        return out

    def retrieve(self, query, limit=5, max_chars=4000, context=None, now=None):
        _text(query, "query", 2048)
        if type(limit) is not int or not 1 <= limit <= 50 or type(max_chars) is not int or not 128 <= max_chars <= 32000:
            raise ValueError("Invalid observation retrieval budget")
        now = time.time() if now is None else _number(now, "now")
        context = context or {}
        if not isinstance(context, dict) or set(context) - {"project", "task_id", "source_reference"}:
            raise ValueError("Invalid task context")
        for key, value in context.items():
            _text(value, "context " + key, 2048, False)
        expanded = query
        for alias, target in sorted(self.aliases.items(), key=lambda item: -len(item[0])):
            expanded = re.sub(re.escape(alias), lambda _: target, expanded, flags=re.I)
        tokens = set(_tokens(expanded))
        tokens.update(f"alias{i}" for i, group in enumerate(ALIAS_GROUPS) if any(_contains(expanded, word) for word in group))
        recent = any(word in expanded.casefold() for word in ("最近", "忙什么", "recent", "working on"))
        if not tokens and not context:
            return []
        if self.fts_available and tokens:
            expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in sorted(tokens)[:64])
            raw_rows = self.db.execute("SELECT e.*,bm25(observation_fts) AS rank FROM observation_fts JOIN observation_events e ON e.id=observation_fts.id WHERE observation_fts MATCH ? ORDER BY rank LIMIT 2000", (expression,)).fetchall()
        else:
            raw_rows = self.db.execute("SELECT * FROM observation_events ORDER BY last_timestamp DESC LIMIT 2000").fetchall()
        candidates = {row["id"]: dict(row) for row in raw_rows}
        if context or recent:
            # Context-only lookup and recent activity have their own bounded pool.
            where = " AND ".join(key + "=?" for key in context)
            sql = "SELECT * FROM observation_events" + (" WHERE " + where if where else "") + " ORDER BY last_timestamp DESC LIMIT 2000"
            candidates.update({row["id"]: dict(row) for row in self.db.execute(sql, tuple(context.values()))})
        named_projects = {row[0] for row in self.db.execute("SELECT DISTINCT project FROM observation_events WHERE project<>'' LIMIT 256") if len(row[0]) >= 2 and row[0] in expanded}
        ranked = []
        for raw in candidates.values():
            row = self._decode(raw)
            if not self._current(row, now) or not self.source_allowed(row) or any(row[key] != value for key, value in context.items()):
                continue
            if len(named_projects) == 1 and row["project"] not in named_projects:
                continue
            body = row["summary"] + " " + _flatten(row["object"]) + " " + row["project"] + " " + row["source_reference"]
            if row["raw_state"] == "raw":
                body += " " + _flatten(row["evidence"])
            matches = len(tokens & set(_index(body).split()))
            if not matches and not context and not recent:
                continue
            score = matches + (2 / (1 + max(0, now-row["timestamp"])/86400) if recent else 0)
            ranked.append((row["epistemic"] == "observed", score, -raw.get("rank", 0), row["timestamp"], row))
        ranked.sort(key=lambda item: item[:4], reverse=True)
        out = []
        for *_, row in ranked:
            packed = {key: row[key] for key in ("id", "kind", "timestamp", "first_timestamp", "source", "source_reference", "version_id", "object", "summary", "confidence", "sensitivity", "epistemic", "evidence_epistemic", "evidence_type", "provenance", "important", "expires_at", "project", "task_id", "occurrences", "occurrence_archive", "raw_state", "evidence_digest", "claim", "derived_from")}
            packed["conflicts"] = self.conflicts(row["id"], now)
            packed["retrieval_method"] = "sqlite_fts5_bm25_local_alias" if self.fts_available else "bounded_lexical_local_alias"
            if len(_dump(out + [packed])) <= max_chars:
                out.append(packed)
            else:
                # All provenance/conflict fields count against serialized budget.
                original = packed["summary"]
                packed["summary"] = ""
                remaining = max_chars - len(_dump(out + [packed]))
                if remaining <= 0:
                    continue
                packed["summary"] = original[:remaining]
                while packed["summary"] and len(_dump(out + [packed])) > max_chars:
                    packed["summary"] = packed["summary"][:-1]
                out.append(packed)
            if len(out) >= limit:
                break
        return out

    def _delete(self, ids):
        ids = set(ids)
        # Forgetting a source also removes every derived inference, including
        # multi-hop inference. It never writes or deletes the actual source file.
        pending = list(ids)
        while pending:
            parent = pending.pop()
            for row in self.db.execute("SELECT memory_id FROM observation_derivations WHERE parent_id=?", (parent,)).fetchall():
                if row[0] not in ids:
                    ids.add(row[0]); pending.append(row[0])
        for mid in ids:
            if self.fts_available:
                self.db.execute("DELETE FROM observation_fts WHERE id=?", (mid,))
            self.db.execute("DELETE FROM observation_occurrences WHERE memory_id=?", (mid,))
            self.db.execute("DELETE FROM observation_occurrence_archive WHERE memory_id=?", (mid,))
            self.db.execute("DELETE FROM observation_claims WHERE memory_id=?", (mid,))
            self.db.execute("DELETE FROM observation_conflicts WHERE older_id=? OR newer_id=?", (mid, mid))
            self.db.execute("DELETE FROM observation_derivations WHERE memory_id=? OR parent_id=?", (mid, mid))
            self.db.execute("DELETE FROM observation_events WHERE id=?", (mid,))
        self.db.execute("DELETE FROM observation_versions WHERE NOT EXISTS (SELECT 1 FROM observation_events e WHERE e.source_reference=observation_versions.reference AND e.version_id=observation_versions.version_id)")
        self.db.execute("DELETE FROM observation_document_links WHERE NOT EXISTS (SELECT 1 FROM observation_events e WHERE e.source_reference=observation_document_links.reference AND e.version_id=observation_document_links.version_id)")
        return len(ids)

    def forget_source(self, reference):
        _text(reference, "source reference", 2048, False)
        with self.db:
            return self._delete([row[0] for row in self.db.execute("SELECT id FROM observation_events WHERE source_reference=?", (reference,))])

    def delete(self, memory_id):
        with self.db:
            return self._delete([memory_id]) if self.get(memory_id) else 0

    def forget(self, memory_id):
        return self.delete(memory_id)

    def retain(self, now=None, ttl_days=30, raw_ttl_days=7, record_limit=10000):
        now = time.time() if now is None else _number(now, "now")
        ttl = _number(ttl_days, "ttl_days") * 86400
        raw_ttl = _number(raw_ttl_days, "raw_ttl_days") * 86400
        if not ttl or not raw_ttl or raw_ttl > ttl or type(record_limit) is not int or record_limit < 1:
            raise ValueError("Invalid observation retention policy")
        deleted, compressed = 0, 0
        with self.db:
            self.db.execute("UPDATE observation_retention_policy SET ttl_days=? WHERE id=1", (ttl_days,))
            rows = self.db.execute("SELECT * FROM observation_events ORDER BY last_timestamp DESC,rowid DESC").fetchall()
            ordinary = 0
            remove = []
            for raw in rows:
                if raw["important"] and (raw["expires_at"] is None or now < raw["expires_at"]):
                    continue
                ordinary += 1
                expiry = raw["expires_at"] if raw["expires_at"] is not None else raw["last_timestamp"] + ttl
                if now >= expiry or ordinary > record_limit:
                    remove.append(raw["id"])
                elif now - raw["last_timestamp"] >= raw_ttl and raw["raw_state"] == "raw":
                    obj = json.loads(raw["object_json"])
                    provenance_object = {k: v for k, v in obj.items() if k in {"bundle_id", "app", "pid", "path", "project", "task_id", "content_authorized"}} if isinstance(obj, dict) else {}
                    self.db.execute("UPDATE observation_events SET evidence_json='{}',object_json=?,summary=substr(summary,1,300),raw_state='compressed' WHERE id=?", (_dump(provenance_object), raw["id"]))
                    self._reindex(dict(self.db.execute("SELECT * FROM observation_events WHERE id=?", (raw["id"],)).fetchone()))
                    # Exact recent tokens and the persistent old-token watermark
                    # keep replay quiet; archived late-event accuracy is UNKNOWN.
                    compressed += 1
            deleted = self._delete(remove)
        return {"timestamp": now, "compressed": compressed, "deleted": deleted, **self.status()}

    def clear(self):
        with self.db:
            for table in ("observation_occurrences", "observation_occurrence_archive", "observation_claims", "observation_conflicts", "observation_derivations", "observation_versions", "observation_document_links", "observation_events"):
                self.db.execute("DELETE FROM " + table)
            if self.fts_available:
                self.db.execute("DELETE FROM observation_fts")

    def status(self):
        counts = self.db.execute("SELECT count(*),coalesce(sum(important),0),coalesce(sum(occurrences),0),coalesce(sum(raw_state='compressed'),0) FROM observation_events").fetchone()
        return {"records": counts[0], "important": counts[1], "occurrences": counts[2], "compressed_records": counts[3], "fts_available": self.fts_available, "schema_version": self.schema_version,
                "ttl_days": self._ttl_seconds()/86400,
                "occurrence_tokens": self.db.execute("SELECT count(*) FROM observation_occurrences").fetchone()[0],
                "archived_event_count": self.db.execute("SELECT count(*) FROM observation_occurrence_archive").fetchone()[0],
                "occurrence_policy": "at most256 exact tokens per event; old/late count accuracy UNKNOWN",
                "semantic_retrieval": "explicit local aliases only; general semantic similarity UNKNOWN"}
