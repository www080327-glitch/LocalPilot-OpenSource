import json
import sqlite3
import time
import uuid
from .reliability import explicit_claims, scalar

TYPES = {"user_fact", "preference", "conversation", "computer_event", "document", "project", "topic", "summary", "reflection"}


class MemoryStore:
    def __init__(self, filename):
        self.db = sqlite3.connect(filename)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA secure_delete=ON;
        CREATE TABLE IF NOT EXISTS memories (
          id TEXT PRIMARY KEY, type TEXT NOT NULL, timestamp REAL NOT NULL,
          source TEXT NOT NULL, source_reference TEXT NOT NULL, summary TEXT NOT NULL,
          confidence REAL NOT NULL, epistemic TEXT NOT NULL, metadata TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS memory_time ON memories(timestamp);
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, digest TEXT NOT NULL, mtime_ns INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY, type TEXT NOT NULL, event_key TEXT NOT NULL UNIQUE,
          timestamp REAL NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL, delivery TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_versions (
          id TEXT PRIMARY KEY, reference TEXT NOT NULL, digest TEXT NOT NULL,
          extracted_at REAL NOT NULL, current INTEGER NOT NULL, memory_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS source_current ON source_versions(reference,current);
        CREATE TABLE IF NOT EXISTS claims (
          id INTEGER PRIMARY KEY, memory_id TEXT NOT NULL, claim_key TEXT NOT NULL,
          value TEXT NOT NULL, timestamp REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS claims_key ON claims(claim_key);
        CREATE TABLE IF NOT EXISTS conflicts (
          id INTEGER PRIMARY KEY, claim_key TEXT NOT NULL, older_id TEXT NOT NULL,
          newer_id TEXT NOT NULL, older_value TEXT NOT NULL, newer_value TEXT NOT NULL,
          detected_at REAL NOT NULL, UNIQUE(older_id,newer_id,claim_key));
        """)
        self.db.create_function("companion_terms", 1, self._search_text)
        self.db.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, tokens);
        CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memories BEGIN
          INSERT INTO memory_fts VALUES(new.id,companion_terms(new.summary || ' ' || new.source_reference || ' ' || new.metadata));
        END;
        CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memories BEGIN
          DELETE FROM memory_fts WHERE id=old.id;
          DELETE FROM source_versions WHERE memory_id=old.id;
          DELETE FROM claims WHERE memory_id=old.id;
          DELETE FROM conflicts WHERE older_id=old.id OR newer_id=old.id;
        END;
        """)
        # Repair V0.2 reopen side effects and never reindex compacted archives.
        self.db.execute("DELETE FROM memory_fts WHERE id IN (SELECT id FROM memories WHERE json_extract(metadata,'$.retained')='summary_metadata')")
        self.db.execute("INSERT INTO memory_fts SELECT id,companion_terms(summary || ' ' || source_reference || ' ' || metadata) FROM memories WHERE id NOT IN (SELECT id FROM memory_fts) AND coalesce(json_extract(metadata,'$.retained'),'')<>'summary_metadata'")
        # V0 records have only a digest. Migrate their current version without changing ids.
        for row in self.db.execute("SELECT * FROM memories WHERE type='document'").fetchall():
            meta = json.loads(row["metadata"])
            if meta.get("sha256") and not self.db.execute("SELECT 1 FROM source_versions WHERE memory_id=?", (row["id"],)).fetchone():
                vid = uuid.uuid4().hex
                self.db.execute("INSERT INTO source_versions VALUES(?,?,?,?,1,?)", (vid,row["source_reference"],meta["sha256"],row["timestamp"],row["id"]))
                meta.update(version_id=vid, extraction_timestamp=row["timestamp"])
                self.db.execute("UPDATE memories SET metadata=? WHERE id=?", (json.dumps(meta,ensure_ascii=False),row["id"]))
        self.db.commit()

    @staticmethod
    def _search_text(text):
        # Preserve multiplicity for BM25 term frequency, including Chinese bigrams.
        import re
        latin = re.findall(r"[a-z0-9_]{2,}", text.lower())
        chinese = re.findall(r"[\u4e00-\u9fff]+", text)
        return " ".join(latin + [w[i:i+2] for w in chinese for i in range(max(1,len(w)-1))])

    def is_current(self, row):
        meta = row.get("metadata", {})
        if meta.get("version_id"):
            return bool(self.db.execute("SELECT 1 FROM source_versions WHERE id=? AND current=1", (meta["version_id"],)).fetchone())
        if row["type"] == "summary" and meta.get("sha256"):
            versions = self.db.execute("SELECT digest,current FROM source_versions WHERE reference=?", (row["source_reference"],)).fetchall()
            if versions:
                return any(v["current"] and v["digest"] == meta["sha256"] for v in versions)
            return self.fingerprint(row["source_reference"]) == meta["sha256"]
        return True

    def invalidate_source(self, reference):
        self.db.execute("UPDATE source_versions SET current=0 WHERE reference=?", (reference,))
        self.db.commit()

    def replace_document(self, reference, digest, mtime, document, summary, timestamp=None):
        now = time.time() if timestamp is None else timestamp
        vid, mid = uuid.uuid4().hex, uuid.uuid4().hex
        metadata = {"sha256":digest, "version_id":vid, "extraction_timestamp":now,
                    "structure":document.structure, "locations":document.locations,
                    "truncated":document.truncated, "index_text":document.text,
                    "summary_method":"bounded extractive summary"}
        # A transaction switches the current version and its fingerprint together.
        with self.db:
            previous = [r[0] for r in self.db.execute("SELECT memory_id FROM source_versions WHERE reference=? AND current=1", (reference,))]
            self.db.execute("UPDATE source_versions SET current=0 WHERE reference=?", (reference,))
            self.db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?)", (mid,"document",now,"document_extractor",reference,summary,1.0,"factual",json.dumps(metadata,ensure_ascii=False)))
            self.db.execute("INSERT INTO source_versions VALUES(?,?,?,?,1,?)", (vid,reference,digest,now,mid))
            self.db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (reference,digest,mtime))
            claim_text = document.text
            if document.locations and document.locations[-1].get("incomplete"):
                claim_text = claim_text[:document.locations[-1]["start"]]
            for key, value in explicit_claims(claim_text, reference):
                # One revision edge plus current conflicting sources, rather than
                # every pair in the entire archive (quadratic growth).
                old_rows = self.db.execute("SELECT c.* FROM claims c JOIN source_versions v ON v.memory_id=c.memory_id WHERE c.claim_key=? AND c.value<>? AND (v.current=1 OR c.memory_id IN (" + ",".join("?" for _ in previous) + "))", (key,value,*previous)).fetchall()
                for old in old_rows:
                    self.db.execute("INSERT OR IGNORE INTO conflicts(claim_key,older_id,newer_id,older_value,newer_value,detected_at) VALUES(?,?,?,?,?,?)", (key,old["memory_id"],mid,old["value"],value,now))
                self.db.execute("INSERT INTO claims(memory_id,claim_key,value,timestamp) VALUES(?,?,?,?)", (mid,key,value,now))
        return metadata

    def active_conflicts(self, memory_id):
        rows = self.db.execute("SELECT * FROM conflicts WHERE older_id=? OR newer_id=?", (memory_id,memory_id)).fetchall()
        def current(mid):
            return bool(self.db.execute("SELECT 1 FROM source_versions WHERE memory_id=? AND current=1", (mid,)).fetchone())
        return [dict(r) for r in rows if current(r["older_id"]) and current(r["newer_id"]) and scalar(r["older_value"]) != scalar(r["newer_value"])]

    def add(self, kind, summary, source, reference="", confidence=1.0, epistemic="factual", metadata=None, timestamp=None):
        if kind not in TYPES or epistemic not in {"factual", "inferred", "reflection"} or not 0 <= confidence <= 1:
            raise ValueError("Invalid memory provenance")
        if kind == "reflection" and epistemic != "reflection":
            raise ValueError("Reflections cannot be facts")
        if epistemic == "factual" and (source.startswith("model") or source.startswith("companion_model") or source.startswith("companion_reflection")):
            raise ValueError("Model narratives cannot be observations")
        if kind == "conversation" and getattr(self, "conversation_disabled", False):
            return None
        from .evidence import evidence_type, is_question
        if kind == "user_fact" and source == "explicit_user_statement" and is_question(summary):
            raise ValueError("A question cannot be saved as a confirmed user fact")
        metadata = dict(metadata or {})
        metadata["evidence_type"] = evidence_type(source, kind, epistemic, summary)
        if epistemic == "factual":
            for parent in (metadata or {}).get("derived_from", []):
                row = self.db.execute("SELECT epistemic FROM memories WHERE id=?", (parent,)).fetchone()
                if not row or row[0] != "factual":
                    raise ValueError("Inferred or reflected knowledge cannot become observations")
        mid = uuid.uuid4().hex
        self.db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?)", (mid, kind, timestamp or time.time(), source, reference, summary, confidence, epistemic, json.dumps(metadata or {}, ensure_ascii=False)))
        self.db.commit()
        return mid

    def records(self, limit=1000, kinds=None):
        if kinds:
            q = "SELECT * FROM memories WHERE type IN (" + ",".join("?" for _ in kinds) + ") ORDER BY timestamp DESC LIMIT ?"
            rows = self.db.execute(q, (*kinds, limit))
        else:
            rows = self.db.execute("SELECT * FROM memories ORDER BY timestamp DESC LIMIT ?", (limit,))
        from .evidence import describe
        records = [dict(row) | {"metadata": json.loads(row["metadata"])} for row in rows]
        return [row | {"evidence_type": describe(row)} for row in records]

    def candidates(self, tokens, limit=2000):
        """Search across history on demand, rather than dropping older facts by age."""
        tokens = sorted(tokens)[:64]
        if not tokens:
            return []
        clauses, values = [], []
        for token in tokens:
            value = "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append("(summary LIKE ? ESCAPE '\\' OR source_reference LIKE ? ESCAPE '\\' OR metadata LIKE ? ESCAPE '\\')")
            values.extend((value,value,value))
        rows = self.db.execute("SELECT * FROM memories WHERE " + " OR ".join(clauses) + " ORDER BY timestamp DESC LIMIT ?", (*values,limit))
        return [dict(row) | {"metadata":json.loads(row["metadata"])} for row in rows]

    def forget_source(self, reference):
        self.db.execute("DELETE FROM memories WHERE source_reference=? AND type IN ('document','summary','computer_event')", (reference,))
        self.db.execute("DELETE FROM files WHERE path=?", (reference,))
        self.db.commit()

    def fingerprint(self, reference):
        row = self.db.execute("SELECT digest FROM files WHERE path=?", (reference,)).fetchone()
        return row[0] if row else None

    def set_file(self, reference, digest, mtime):
        self.db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (reference, digest, mtime))
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def clear(self, extra_tables=(), state=None):
        allowed = {"observation_occurrences", "observation_claims", "observation_conflicts", "observation_derivations",
                   "observation_versions", "observation_document_links", "observation_events", "observation_fts", "observation_occurrence_archive"}
        if set(extra_tables) - allowed:
            raise ValueError("Unknown memory tables")
        with self.db:
            for table in (*extra_tables, "memories", "files", "notices", "state", "source_versions", "claims", "conflicts", "memory_fts"):
                self.db.execute(f"DELETE FROM {table}")
            for key, value in (state or {}).items():
                self.db.execute("INSERT INTO state VALUES(?,?)", (key, json.dumps(value)))
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")

    def close(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
