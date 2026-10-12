"""Short SQLite transactions; no network/worker I/O inside a transaction."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class TimefreeStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=15) as db:
            db.row_factory = sqlite3.Row
            db.executescript('''
                CREATE TABLE IF NOT EXISTS timefree_jobs (
                    job_id TEXT PRIMARY KEY, broadcast_episode_id TEXT NOT NULL,
                    station TEXT NOT NULL, title TEXT NOT NULL,
                    start_at TEXT NOT NULL, end_at TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','expired','cancelled','unknown')),
                    created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, failed_at TEXT,
                    output_path TEXT, error_code TEXT, error_message TEXT,
                    snapshot TEXT NOT NULL, deadline TEXT NOT NULL, execution_kind TEXT NOT NULL,
                    output_sha256 TEXT, output_size INTEGER, duration REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS timefree_live_episode
                  ON timefree_jobs(broadcast_episode_id) WHERE state IN ('queued','running','completed','unknown');
                CREATE TABLE IF NOT EXISTS timefree_events (
                    seq INTEGER PRIMARY KEY, job_id TEXT NOT NULL, state TEXT NOT NULL, at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS timefree_publications (
                    job_id TEXT PRIMARY KEY, manifest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS timefree_dispatches (
                    job_id TEXT PRIMARY KEY
                );
            ''')
            db.execute('BEGIN IMMEDIATE')
            columns = {r[1] for r in db.execute('PRAGMA table_info(timefree_jobs)')}
            if 'station_ids' not in columns:
                db.execute("ALTER TABLE timefree_jobs ADD COLUMN station_ids TEXT NOT NULL DEFAULT '[]'")
            yield db

    @staticmethod
    def decode(row):
        item = dict(row)
        item['broadcast'] = json.loads(item.pop('snapshot'))
        return item

    def list(self):
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            if not db.execute("SELECT name FROM sqlite_master WHERE name='timefree_jobs'").fetchone():
                return []
            return [self.decode(r) for r in db.execute('SELECT * FROM timefree_jobs ORDER BY created_at DESC,job_id')]

    def get(self, job_id):
        return next((r for r in self.list() if r['job_id'] == job_id), None)

    @staticmethod
    def event(db, job_id, state, now):
        db.execute('INSERT INTO timefree_events(job_id,state,at) VALUES (?,?,?)', (job_id, state, now))

    def save_publication(self, job_id, manifest):
        with self.transaction() as db:
            db.execute('INSERT INTO timefree_publications VALUES (?,?)',
                       (job_id, json.dumps(manifest, sort_keys=True, ensure_ascii=False)))

    def publication(self, job_id):
        with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if not db.execute("SELECT name FROM sqlite_master WHERE name='timefree_publications'").fetchone():
                return None
            row = db.execute('SELECT manifest FROM timefree_publications WHERE job_id=?', (job_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def pending_dispatches(self):
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if not db.execute("SELECT name FROM sqlite_master WHERE name='timefree_dispatches'").fetchone():
                return []
            return [r[0] for r in db.execute('SELECT job_id FROM timefree_dispatches ORDER BY rowid')]
