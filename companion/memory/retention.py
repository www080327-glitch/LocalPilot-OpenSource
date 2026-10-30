"""Bound owned DB history; never writes, unlinks or touches source files."""
import json
import time
from companion.triggers.policy import expire_notices


def retain(store, recent=3, full_ttl_days=30, metadata_limit=100, record_limit=10000, now=None):
    if type(recent) is not int or type(metadata_limit) is not int or recent < 1 or metadata_limit < recent or record_limit < 1 or full_ttl_days <= 0:
        raise ValueError("Invalid retention policy")
    now = time.time() if now is None else now
    expire_notices(store, now)
    compacted = deleted = 0
    pending = store.get("pending_escalation") or {}
    pinned = {r["id"] for r in pending.get("relevant_memories", [])}
    with store.db:
        references = store.db.execute("SELECT DISTINCT reference FROM source_versions").fetchall()
        for (reference,) in references:
            rows = store.db.execute("SELECT v.*,m.metadata FROM source_versions v JOIN memories m ON m.id=v.memory_id WHERE v.reference=? ORDER BY v.current DESC,v.extracted_at DESC,v.rowid DESC", (reference,)).fetchall()
            historical = [r for r in rows if not r["current"]]
            for index, row in enumerate(historical):
                if row["memory_id"] in pinned:
                    continue
                if index >= metadata_limit:
                    store.db.execute("DELETE FROM memories WHERE id=?", (row["memory_id"],))
                    deleted += 1
                elif index >= recent or now - row["extracted_at"] > full_ttl_days * 86400:
                    meta = json.loads(row["metadata"])
                    if meta.get("retained") == "summary_metadata":
                        continue
                    # Keep source id, digest, extraction time and bounded summary.
                    meta.pop("index_text", None)
                    meta.pop("locations", None)
                    meta["retained"] = "summary_metadata"
                    store.db.execute("UPDATE memories SET summary=substr(summary,1,600),metadata=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), row["memory_id"]))
                    store.db.execute("DELETE FROM memory_fts WHERE id=?", (row["memory_id"],))
                    compacted += 1
        # Activity, answer history and notices also grow during multi-day residence.
        for kind in ("computer_event", "conversation", "summary"):
            rows = store.db.execute("SELECT id,metadata FROM memories WHERE type=? ORDER BY timestamp DESC,rowid DESC LIMIT -1 OFFSET ?", (kind, record_limit)).fetchall()
            for row in rows:
                meta = json.loads(row["metadata"])
                # Summaries bound to current versions are protected too.
                current = meta.get("version_id") and store.db.execute("SELECT 1 FROM source_versions WHERE id=? AND current=1", (meta["version_id"],)).fetchone()
                if row["id"] not in pinned and not current:
                    store.db.execute("DELETE FROM memories WHERE id=?", (row["id"],))
                    deleted += 1
        # Preserve feedback state. Notice ids are deduped only over the retained window.
        store.db.execute("DELETE FROM notices WHERE id IN (SELECT id FROM notices WHERE status <> 'pending' ORDER BY timestamp DESC LIMIT -1 OFFSET ?)", (record_limit,))
    stats = {"timestamp": now, "compacted": compacted, "deleted": deleted,
             "current_versions": store.db.execute("SELECT count(*) FROM source_versions WHERE current=1").fetchone()[0],
             "old_versions": store.db.execute("SELECT count(*) FROM source_versions WHERE current=0").fetchone()[0]}
    store.set("last_retention", stats)
    return stats
