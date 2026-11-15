"""User-selected read-only exports, with durable grants and source-version evidence."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from companion.config import SENSITIVE
from .events import ObservationEvent, PRIVATE_FILE, redact_text
from .files import read_regular_file
from .source_formats import EXTENSIONS, parse_source


class SourceRegistry:
    def __init__(self, config, store, memory, paused):
        self.config, self.store, self.db, self.memory, self.paused = config, store, store.db, memory, paused
        self.next_poll = 0
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS connected_sources (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, path TEXT NOT NULL,
                path_kind TEXT NOT NULL, label TEXT NOT NULL, enabled INTEGER NOT NULL,
                follow INTEGER NOT NULL, created_at REAL NOT NULL, last_sync REAL,
                last_result TEXT, UNIQUE(kind,path));
            CREATE TABLE IF NOT EXISTS source_import_files (
                source_id TEXT NOT NULL, path TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
                version TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
                status TEXT NOT NULL, records INTEGER NOT NULL,
                PRIMARY KEY(source_id,path));
        """)

    def list(self):
        sources = []
        for raw in self.db.execute("SELECT * FROM connected_sources ORDER BY created_at,id"):
            row = dict(raw)
            row.update(enabled=bool(row["enabled"]), follow=bool(row["follow"]),
                       last_result=json.loads(row["last_result"]) if row["last_result"] else None,
                       coverage=self.coverage(row["kind"]))
            sources.append(row)
        return {"status": "ok", "sources": sources}

    @staticmethod
    def coverage(kind):
        return ("仅导出的用户/助手可见文字；隐藏推理、工具参数和执行收据不导入。" if kind == "codex"
                else "仅所选会议文字/字幕，不采集音频；文件时间、说话者和完成情况不作独立验证。")

    def connect(self, kind, filename, label=None, follow=True):
        path, label = self._connection_input(kind, filename, label, follow)
        prior = self.db.execute("SELECT id FROM connected_sources WHERE kind=? AND path=?", (kind, str(path))).fetchone()
        source_id = prior[0] if prior else "source_" + uuid.uuid4().hex
        with self.db:
            self.db.execute("""INSERT INTO connected_sources VALUES(?,?,?,?,?,1,?,?,NULL,NULL)
                ON CONFLICT(id) DO UPDATE SET label=excluded.label,follow=excluded.follow,enabled=1""",
                (source_id, kind, str(path), "directory" if path.is_dir() else "file", label, int(follow), time.time()))
        result = self.sync(source_id)
        return {"status": "ok", "source": self.get(source_id), "sync": result}

    def get(self, source_id):
        if not isinstance(source_id, str):
            raise ValueError("A registered source ID is required")
        for row in self.list()["sources"]:
            if row["id"] == source_id:
                return row
        raise ValueError("Source is not registered")

    def set_enabled(self, source_id, enabled):
        if type(enabled) is not bool:
            raise ValueError("Source enabled must be boolean")
        self.get(source_id)
        with self.db:
            self.db.execute("UPDATE connected_sources SET enabled=? WHERE id=?", (int(enabled), source_id))
        self.store.set("pending_escalation", None)
        return {"status": "ok", "source": self.get(source_id)}

    def revoke(self, source_id):
        self.get(source_id)
        removed = 0
        for row in self.db.execute("SELECT reference FROM source_import_files WHERE source_id=?", (source_id,)).fetchall():
            removed += self.memory.forget_source(row[0])
        with self.db:
            self.db.execute("DELETE FROM source_import_files WHERE source_id=?", (source_id,))
            self.db.execute("DELETE FROM connected_sources WHERE id=?", (source_id,))
        self.store.set("pending_escalation", None)
        return {"status": "ok", "removed_records": removed}

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        if now < self.next_poll or self.paused():
            return []
        self.next_poll = now + 60
        return [self.sync(row["id"]) for row in self.list()["sources"] if row["enabled"] and row["follow"]]

    def sync(self, source_id):
        source = self.get(source_id)
        if not source["enabled"] or self.paused():
            return {"status": "disabled" if not source["enabled"] else "paused", "source_id": source_id,
                    "files": 0, "records": 0, "coverage": self.coverage(source["kind"])}
        result = {"status": "ok", "source_id": source_id, "files": 0, "records": 0,
                  "cached_files": 0, "skipped_records": 0, "errors": [], "truncated": False,
                  "coverage": self.coverage(source["kind"])}
        now, total_bytes = time.time(), 0
        try:
            for filename in self._paths(source):
                if result["files"] >= min(self.config.max_scan_files, 500):
                    result["truncated"] = True
                    break
                result["files"] += 1
                try:
                    content, st = read_regular_file(filename, self.config.max_file_bytes)
                    total_bytes += len(content)
                    if total_bytes > 32 * 1024 * 1024:
                        result["truncated"] = True
                        break
                    imported = self._import_file(source, filename, content, st, now)
                    result["records"] += imported["records"]
                    result["cached_files"] += int(imported.get("cached", False))
                    result["skipped_records"] += imported.get("skipped_records", 0)
                    result["truncated"] |= imported.get("truncated", False)
                except (OSError, ValueError, TypeError) as error:
                    with self.db:
                        self.db.execute("UPDATE source_import_files SET status='unavailable' WHERE source_id=? AND path=?", (source_id, str(filename)))
                    result["errors"].append({"file": filename.name, "reason": type(error).__name__})
        except (OSError, ValueError) as error:
            result["errors"].append({"file": Path(source["path"]).name, "reason": type(error).__name__})
        if result["errors"] or result["truncated"]:
            result["status"] = "partial" if result["records"] else "unavailable"
        elif not result["records"]:
            result["status"] = "empty"
        with self.db:
            self.db.execute("UPDATE connected_sources SET last_sync=?,last_result=? WHERE id=?", (now, json.dumps(result, ensure_ascii=False), source_id))
        return result

    def accessible(self, row):
        if self.paused():
            return False
        found = self.db.execute("""SELECT f.*,s.path AS root,s.path_kind,s.enabled FROM source_import_files f
            JOIN connected_sources s ON s.id=f.source_id WHERE f.reference=?""", (row.get("source_reference", ""),)).fetchone()
        if not found or not found["enabled"] or found["status"] != "ready" or found["version"] != row.get("version_id"):
            return False
        filename = Path(found["path"])
        if not self._within(filename, Path(found["root"]), found["path_kind"]):
            return False
        try:
            st = filename.stat()
            return (st.st_mtime_ns, st.st_size) == (found["mtime_ns"], found["size"])
        except OSError:
            return False

    def _import_file(self, source, filename, content, st, now):
        version = hashlib.sha256(content).hexdigest()
        reference = "source:" + source["id"] + ":" + hashlib.sha256(str(filename).encode()).hexdigest()[:24]
        old = self.db.execute("SELECT * FROM source_import_files WHERE source_id=? AND path=?", (source["id"], str(filename))).fetchone()
        if old and old["version"] == version and old["status"] == "ready":
            with self.db:
                self.db.execute("UPDATE source_import_files SET mtime_ns=?,size=? WHERE reference=?", (st.st_mtime_ns, st.st_size, reference))
            count = self.db.execute("SELECT count(*) FROM observation_events WHERE source_reference=? AND version_id=? AND (expires_at IS NULL OR expires_at>?)", (reference, version, now)).fetchone()[0]
            return {"records": count, "cached": True}
        records, metadata = parse_source(source["kind"], content, filename.suffix.lower(), st.st_mtime)
        truncated = len(records) > 2000
        records = records[:2000]
        with self.db:
            self.db.execute("""INSERT OR REPLACE INTO source_import_files VALUES(?,?,?,?,?,?,?,?)""",
                (source["id"], str(filename), reference, version, st.st_mtime_ns, st.st_size, "publishing", 0))
        for record in records:
            event = ObservationEvent.create("external_source", "imported." + source["kind"],
                {"source_id": source["id"], "source_kind": source["kind"], "source_path": str(filename),
                 "label": source["label"], "role": record["role"]},
                {**record, "file_sha256": version, "imported_at": now, "read_status": "READ_SUCCESS_NONEMPTY",
                 "completion_verified": False, "coverage": metadata["coverage"]},
                timestamp=min(record["timestamp"], now), source_reference=reference, version_id=version).to_dict()
            event.update(summary=f"{source['label']} · {record['role']} · {record['locator']}\n{record['text']}",
                         occurrence_id=version + ":" + record["locator"], expires_at=now+self.config.observation_ttl_days*86400)
            self.memory.add(event)
        with self.db:
            # Import order governs source versions; message times can be historical.
            self.db.execute("UPDATE observation_versions SET current=(version_id=?),timestamp=CASE WHEN version_id=? THEN ? ELSE timestamp END WHERE reference=?", (version, version, now, reference))
            self.db.execute("UPDATE source_import_files SET status='ready',records=? WHERE reference=?", (len(records), reference))
        return {"records": len(records), "truncated": truncated, **metadata}

    def _paths(self, source):
        root = Path(source["path"])
        if source["path_kind"] == "file":
            if not self._within(root, root, "file"):
                raise ValueError("Selected file is unavailable")
            yield root
            return
        if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError("Selected directory is unavailable")
        for parent, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in SENSITIVE and not name.startswith(".")
                                    and not (Path(parent)/name).is_symlink())
            for name in sorted(files):
                filename = Path(parent)/name
                if filename.suffix.lower() in EXTENSIONS[source["kind"]] and self._within(filename, root, "directory"):
                    yield filename

    @staticmethod
    def _within(filename, root, path_kind):
        return ((filename == root if path_kind == "file" else filename.is_relative_to(root))
                and not PRIVATE_FILE.search(str(filename))
                and not any(p.is_symlink() for p in (filename, *filename.parents)))

    def _connection_input(self, kind, filename, label, follow):
        if kind not in EXTENSIONS or not isinstance(filename, str) or not filename.strip() or len(filename) > 1500 or type(follow) is not bool:
            raise ValueError("Select a bounded Codex or meeting source path")
        path = Path(os.path.abspath(os.path.expanduser(filename)))
        label = path.name if label is None else label
        if not isinstance(label, str) or not label.strip() or len(label) > 120 or redact_text(label) != label:
            raise ValueError("A bounded nonsensitive source label is required")
        if not self._within(path, path, "file") or not (path.is_file() or path.is_dir()):
            raise ValueError("Choose an existing regular file or directory without symbolic links")
        if path.is_file() and path.suffix.lower() not in EXTENSIONS[kind]:
            raise ValueError("Unsupported source export format")
        if self.db.execute("SELECT count(*) FROM connected_sources").fetchone()[0] >= 32 and not self.db.execute("SELECT 1 FROM connected_sources WHERE kind=? AND path=?", (kind, str(path))).fetchone():
            raise ValueError("At most 32 explicit sources may be connected")
        return path, label
