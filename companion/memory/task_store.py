"""Indexed Companion task receipts in the existing memory database."""
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile


TERMINAL = {"completed", "incomplete", "failed", "cancelled", "timed_out"}
INSERT = """INSERT INTO localpilot_tasks
    (task_id,timestamp,endpoint,session_id,scope,active,payload,context_request) VALUES(?,?,?,?,?,?,?,?)"""
UPDATE = """ ON CONFLICT(task_id) DO UPDATE SET timestamp=excluded.timestamp,
    endpoint=excluded.endpoint,session_id=excluded.session_id,scope=excluded.scope,
    active=excluded.active,payload=excluded.payload,context_request=excluded.context_request"""


class TaskStore:
    def __init__(self, db):
        self.db = db
        self.backup_path = None
        filename = self.db.execute("PRAGMA database_list").fetchone()[2]
        self.path = Path(filename) if filename else None
        legacy = self.db.execute("SELECT value FROM state WHERE key='localpilot_tasks'").fetchone()
        records = self._legacy_records(legacy[0]) if legacy else {}
        if records:
            self.backup_path = self._backup()
        with self.db:
            # SQLite DDL does not implicitly start Python's transaction.
            self.db.execute("BEGIN")
            self.db.execute("""CREATE TABLE IF NOT EXISTS localpilot_tasks (
                task_id TEXT PRIMARY KEY,timestamp REAL NOT NULL,endpoint TEXT,
                session_id TEXT,scope TEXT,active INTEGER NOT NULL,payload TEXT NOT NULL,
                context_request TEXT)""")
            if 'context_request' not in {row[1] for row in self.db.execute('PRAGMA table_info(localpilot_tasks)')}:
                self.db.execute('ALTER TABLE localpilot_tasks ADD COLUMN context_request TEXT')
            # Older row-store versions omit this column when inserting tasks.
            self.db.execute('CREATE INDEX IF NOT EXISTS task_context_pending ON localpilot_tasks(task_id) WHERE context_request IS NULL')
            self.db.execute('''CREATE TRIGGER IF NOT EXISTS task_context_invalidate
                AFTER UPDATE OF payload ON localpilot_tasks
                WHEN NEW.payload IS NOT OLD.payload AND NEW.context_request IS OLD.context_request
                BEGIN UPDATE localpilot_tasks SET context_request=NULL WHERE task_id=NEW.task_id; END''')
            self._refresh_contexts()
            self.db.execute("CREATE INDEX IF NOT EXISTS task_history_time ON localpilot_tasks(timestamp DESC,task_id DESC)")
            self.db.execute("CREATE INDEX IF NOT EXISTS task_history_session ON localpilot_tasks(session_id,endpoint,timestamp,task_id)")
            self.db.execute("CREATE INDEX IF NOT EXISTS task_history_active ON localpilot_tasks(endpoint,scope,active,timestamp DESC,task_id DESC)")
            self.db.execute("CREATE INDEX IF NOT EXISTS task_context_session ON localpilot_tasks(session_id,endpoint,timestamp,context_request)")
            self.db.executemany(INSERT, (self._row(task_id, record) for task_id, record in records.items()))
            self.db.execute("DELETE FROM state WHERE key='localpilot_tasks'")

    def get(self, task_id, default=None):
        row = self.db.execute("SELECT payload FROM localpilot_tasks WHERE task_id=?", (task_id,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, task_id, record):
        row = self._row(task_id, record)
        with self.db:
            self.db.execute(INSERT + UPDATE, row)
            self.db.execute('UPDATE localpilot_tasks SET context_request=? WHERE task_id=? AND context_request IS NULL',
                            (row[-1], task_id))

    def put_if_absent(self, task_id, record):
        with self.db:
            self.db.execute(INSERT + " ON CONFLICT(task_id) DO NOTHING", self._row(task_id, record))

    def count(self):
        return self.db.execute("SELECT count(*) FROM localpilot_tasks").fetchone()[0]

    def page(self, limit=30, before=None):
        where, values = "", ()
        if before is not None:
            where, values = "WHERE (timestamp,task_id)<(?,?)", (before['timestamp'], before['id'])
        rows = self.db.execute(f"SELECT task_id,timestamp,payload FROM localpilot_tasks {where} ORDER BY timestamp DESC,task_id DESC LIMIT ?",
                               (*values, limit + 1)).fetchall()
        page = rows[:limit]
        cursor = {"timestamp":page[-1]['timestamp'], "id":page[-1]['task_id']} if len(rows) > limit else None
        return {"tasks":{row['task_id']:json.loads(row['payload']) for row in page},
                "total":self.count(), "next_before":cursor}

    def session_records(self, endpoint, session_id, before=None):
        where, values = "", ()
        if before is not None:
            where, values = " AND timestamp<=?", (before,)
        rows = self.db.execute("SELECT payload FROM localpilot_tasks WHERE session_id=? AND endpoint=?" + where,
                               (session_id, endpoint, *values))
        return (json.loads(row[0]) for row in rows)

    def session_contexts(self, endpoint, session_id, before=None):
        with self.db:
            self._refresh_contexts()
        where, values = "", ()
        if before is not None:
            where, values = " AND timestamp<=?", (before,)
        rows = self.db.execute("SELECT DISTINCT context_request FROM localpilot_tasks WHERE session_id=? AND endpoint=?" + where,
                               (session_id, endpoint, *values))
        return (json.loads(row[0]) if row[0] is not None else None for row in rows)

    def _refresh_contexts(self):
        for row in self.db.execute('SELECT task_id,payload FROM localpilot_tasks WHERE context_request IS NULL'):
            self.db.execute('UPDATE localpilot_tasks SET context_request=? WHERE task_id=?',
                            (self._context_request(json.loads(row['payload'])), row['task_id']))

    def has_session(self, session_id):
        return self.db.execute("SELECT 1 FROM localpilot_tasks WHERE session_id=? LIMIT 1", (session_id,)).fetchone() is not None

    def resumable(self, endpoint, scope, limit=2):
        rows = self.db.execute("""SELECT task_id,payload FROM localpilot_tasks
            WHERE endpoint=? AND scope=? AND active=1 ORDER BY timestamp DESC,task_id DESC LIMIT ?""",
            (endpoint, scope, limit))
        return [(row['task_id'], json.loads(row['payload'])) for row in rows]

    def forget_backups(self):
        if self.path:
            for path in self.path.parent.glob(self.path.name + '.task-rows-backup-*.sqlite3'):
                path.unlink()

    @staticmethod
    def _row(task_id, record):
        transport = record.get('transport', {})
        session = (record.get('result') or record.get('last_status') or {}).get('session_id')
        active = int(record.get('last_status', {}).get('status') not in TERMINAL)
        return (task_id, record.get('timestamp', 0), record.get('endpoint'), session,
                transport.get('scope'), active, json.dumps(record, ensure_ascii=False),
                TaskStore._context_request(record))

    @staticmethod
    def _context_request(record):
        if 'request' not in record:
            return 'null'
        request = record['request']
        # Only dependency identity is stable; access and source freshness must
        # still be checked on every read, including after revocation.
        context = {
            'relevant_memories': [{'id': row.get('id')} for row in request.get('relevant_memories', [])],
            'relevant_files': request.get('relevant_files', []),
            'recent_events': [({'observation_id': row['observation_id']} if row.get('observation_id')
                               else {'source_reference': row.get('source_reference', '')})
                              for row in request.get('recent_events', [])],
        }
        for key, values in context.items():
            encoded = {json.dumps(value, ensure_ascii=False, sort_keys=True): value for value in values}
            context[key] = [encoded[item] for item in sorted(encoded)]
        return json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    @staticmethod
    def _legacy_records(value):
        records = json.loads(value)
        if not isinstance(records, dict):
            raise ValueError('Legacy Companion task history must be a JSON mapping')
        for task_id, record in records.items():
            if not isinstance(task_id, str) or not task_id or not isinstance(record, dict):
                raise ValueError('Legacy Companion task history contains an invalid record')
            timestamp = record.get('timestamp', 0)
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                raise ValueError('Legacy Companion task timestamp must be finite')
        return records

    def _backup(self):
        if self.path is None:
            return None
        fd, filename = tempfile.mkstemp(prefix=self.path.name + '.task-rows-backup-', suffix='.sqlite3', dir=self.path.parent)
        os.close(fd)
        path = Path(filename)
        try:
            with closing(sqlite3.connect(path)) as backup:
                self.db.backup(backup)
                if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise sqlite3.DatabaseError('Companion task migration backup is invalid')
        except BaseException:
            path.unlink()
            raise
        return path
