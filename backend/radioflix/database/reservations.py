"""SQLite journal. Commit intent before remote I/O; serialize across workers."""
import fcntl
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ReservationStore:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        # Listing must not wait for an in-flight network operation. A read-only
        # SQLite snapshot can show the committed pending/unknown state instead.
        if not self.path.exists():
            return []
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            if not db.execute("SELECT name FROM sqlite_master WHERE name='reservations'").fetchone():
                return []
            return self.listing(db)
        finally:
            db.close()

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA foreign_keys=ON")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS reservations (
                        id TEXT PRIMARY KEY, program_id TEXT NOT NULL, title TEXT NOT NULL,
                        mode TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
                        broadcast TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS recording_jobs (
                        id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL REFERENCES reservations(id),
                        payload TEXT NOT NULL, state TEXT NOT NULL, external_ref TEXT,
                        UNIQUE(reservation_id, payload)
                    );
                """)
                yield db
            finally:
                db.close()
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def jobs(db, reservation_id):
        return [dict(row) for row in db.execute("SELECT * FROM recording_jobs WHERE reservation_id=? ORDER BY rowid", (reservation_id,))]

    def listing(self, db):
        result = []
        for row in db.execute("SELECT * FROM reservations ORDER BY created_at DESC"):
            item = dict(row)
            item["broadcast"] = json.loads(item["broadcast"])
            item["jobs"] = [{**job, "payload": json.loads(job["payload"]),
                              "external_ref": json.loads(job["external_ref"]) if job["external_ref"] else None}
                             for job in self.jobs(db, item["id"])]
            result.append(item)
        return result
