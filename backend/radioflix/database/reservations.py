"""SQLite journal. Commit intent before remote I/O; serialize across workers."""
import fcntl
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from radioflix.adapters.rfriends import weekly_title_key


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

    def read_subscriptions(self):
        if not self.path.exists():
            return []
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            if not db.execute("SELECT name FROM sqlite_master WHERE name='weekly_subscriptions'").fetchone():
                return []
            return self.subscriptions(db)
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
                    CREATE TABLE IF NOT EXISTS weekly_subscriptions (
                        id TEXT PRIMARY KEY,
                        program_id TEXT NOT NULL,
                        station TEXT NOT NULL,
                        title TEXT NOT NULL,
                        title_key TEXT NOT NULL,
                        region TEXT NOT NULL,
                        anchor_weekday INTEGER NOT NULL,
                        anchor_time TEXT NOT NULL,
                        state TEXT NOT NULL,
                        schedule_state TEXT NOT NULL,
                        current_reservation_id TEXT,
                        last_matched_broadcast TEXT,
                        next_expected_at TEXT NOT NULL,
                        next_check_at TEXT,
                        message TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS one_active_weekly_per_program_station
                        ON weekly_subscriptions(program_id, station) WHERE state='active';
                """)
                columns = {row[1] for row in db.execute("PRAGMA table_info(reservations)")}
                if "subscription_id" not in columns:
                    db.execute("ALTER TABLE reservations ADD COLUMN subscription_id TEXT")
                subscription_columns = {row[1] for row in db.execute("PRAGMA table_info(weekly_subscriptions)")}
                for name, definition in (("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
                                         ("replacement_broadcast", "TEXT")):
                    if name not in subscription_columns:
                        db.execute(f"ALTER TABLE weekly_subscriptions ADD COLUMN {name} {definition}")
                self._migrate_legacy_weekly(db)
                db.commit()
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

    @staticmethod
    def subscriptions(db):
        result = []
        for row in db.execute("SELECT * FROM weekly_subscriptions ORDER BY created_at DESC"):
            item = dict(row)
            item["last_matched_broadcast"] = (json.loads(item["last_matched_broadcast"])
                                                if item["last_matched_broadcast"] else None)
            result.append(item)
        return result

    @staticmethod
    def _migrate_legacy_weekly(db):
        """Preserve pre-subscription weekly rows as their current occurrence."""
        rows = db.execute(
            "SELECT * FROM reservations WHERE mode='weekly' AND subscription_id IS NULL"
        ).fetchall()
        for row in rows:
            broadcast = json.loads(row["broadcast"])
            start = datetime.fromisoformat(broadcast["starts_at"])
            end = datetime.fromisoformat(broadcast["ends_at"])
            subscription_id = "legacy-" + row["id"]
            state = "cancelled" if row["state"] == "cancelled" else "active"
            schedule_state = "cancelled" if state == "cancelled" else "scheduled"
            db.execute(
                """INSERT OR IGNORE INTO weekly_subscriptions
                   (id,program_id,station,title,title_key,region,anchor_weekday,anchor_time,
                    state,schedule_state,current_reservation_id,last_matched_broadcast,
                    next_expected_at,next_check_at,message,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (subscription_id, row["program_id"], broadcast["station"], row["title"],
                 weekly_title_key(broadcast["title"]), broadcast.get("region", "JP13"), start.weekday(),
                 start.strftime("%H:%M:%S"), state, schedule_state, row["id"],
                 json.dumps(broadcast), (start + timedelta(days=7)).isoformat(), None,
                 row["message"], row["created_at"], row["updated_at"]),
            )
            db.execute(
                "UPDATE reservations SET subscription_id=?, mode='once' WHERE id=?",
                (subscription_id, row["id"]),
            )
