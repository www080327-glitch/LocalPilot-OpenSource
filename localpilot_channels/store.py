"""Private channel metadata, not an Agent task engine. SQLite locks also work on Windows."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from .security import canonical_path, private_directory, private_file


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def regular_path(path):
    return private_file(path)


class Store:
    def __init__(self, directory, configuration):
        root = canonical_path(directory)
        repo = Path(__file__).resolve().parents[1]
        if root == repo or repo in root.parents:
            raise ValueError('state_must_be_outside_repository')
        root = private_directory(root, create=True)
        self.owner = self.db = None
        try:
            for name in ('owner.sqlite3', 'owner.sqlite3-journal', 'channels.sqlite3', 'channels.sqlite3-wal', 'channels.sqlite3-shm'):
                regular_path(root / name)
            private_file(root / 'owner.sqlite3', create=True)
            private_file(root / 'channels.sqlite3', create=True)
            self.owner = sqlite3.connect(root / 'owner.sqlite3', timeout=0, check_same_thread=False)
            self.owner.execute('CREATE TABLE IF NOT EXISTS owner (id INTEGER)')
            self.owner.commit()
            self.owner.execute('BEGIN EXCLUSIVE')
            self.db = sqlite3.connect(root / 'channels.sqlite3', timeout=0, check_same_thread=False)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            old = self.get('configuration')
            if old is not None and old != configuration:
                raise ValueError('channel_configuration_changed_explicit_migration_required')
            self.put('configuration', configuration)
            for name in ('owner.sqlite3', 'channels.sqlite3', 'channels.sqlite3-wal', 'channels.sqlite3-shm'):
                regular_path(root / name)
        except Exception:
            self.close()
            raise

    def get(self, key):
        row = self.db.execute('SELECT data FROM items WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        self.put_many({key: value})

    def put_many(self, values):
        with self.db:
            for key, value in values.items():
                self.db.execute('INSERT OR REPLACE INTO items VALUES (?,?)', (key, json.dumps(value, ensure_ascii=True)))

    def event(self, event):
        key = digest([event['official_task_id'], event['type'], event.get('receipt_fingerprint'), event.get('task_status'), event.get('quiescent')])
        with self.db:
            old = self.db.execute('SELECT data FROM audit WHERE id=?', (key,)).fetchone()
            if old:
                previous = json.loads(old[0])
                if {k:v for k,v in previous.items() if k not in {'event_id','timestamp'}} != event:
                    raise ValueError('audit_receipt_changed')
                return
            record = dict(event, event_id=key, timestamp=datetime.now(timezone.utc).isoformat())
            self.db.execute('INSERT INTO audit VALUES (?,?)', (key, json.dumps(record)))

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.owner is not None:
            self.owner.close()
            self.owner = None
