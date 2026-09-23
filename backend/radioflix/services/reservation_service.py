import json
import uuid
from datetime import datetime, timedelta

from radioflix.schemas.reservations import Broadcast, JST, RecordingError


class ReservationService:
    def __init__(self, store, adapter, clock=None):
        self.store = store
        self.adapter = adapter
        self.clock = clock or (lambda: datetime.now(JST))

    def _state(self, db, reservation_id, state, message=""):
        db.execute("UPDATE reservations SET state=?,message=?,updated_at=? WHERE id=?",
                   (state, message, self.clock().isoformat(), reservation_id))
        db.commit()

    def _job(self, db, reservation_id, broadcast):
        job_id = uuid.uuid4().hex
        payload = {**broadcast.model_dump(mode="json"), "id": job_id}
        db.execute("INSERT INTO recording_jobs VALUES (?,?,?,?,NULL)",
                   (job_id, reservation_id, json.dumps(payload), "pending_create"))
        db.commit()
        return dict(db.execute("SELECT * FROM recording_jobs WHERE id=?", (job_id,)).fetchone())

    def _save_job(self, db, job, state, external=None):
        db.execute("UPDATE recording_jobs SET state=?, external_ref=COALESCE(?, external_ref) WHERE id=?",
                   (state, json.dumps(external) if external else None, job["id"]))
        db.commit()

    def _register(self, db, row, job):
        self._state(db, row["id"], "pending_create")
        self._save_job(db, job, "pending_create")
        try:
            result = self.adapter.create(json.loads(job["payload"]))
            if result.get("state") != "scheduled":
                raise RecordingError("unconfirmed", "録音側の登録結果を確認できません。状態を再確認してください。", True)
            self._save_job(db, job, "scheduled", result)
            self._state(db, row["id"], "active")
        except RecordingError as error:
            state = "create_unknown" if error.uncertain else "create_failed"
            self._save_job(db, job, state)
            self._state(db, row["id"], state, error.message)
        except Exception:
            self._save_job(db, job, "create_unknown")
            self._state(db, row["id"], "create_unknown", "登録結果を確認できません。状態を再確認してください。")

    def list(self):
        items = self.store.read()
        for item in items:
            if item["state"] == "active" and datetime.fromisoformat(item["updated_at"]) < self.clock() - timedelta(minutes=3):
                item["state"] = "stale"
                item["message"] = "録音側の確認が遅れています。状態を再確認してください。"
        return items

    def create(self, program, broadcast, mode):
        if broadcast.starts_at <= self.clock() + timedelta(minutes=3):
            raise RecordingError("too_late", "開始3分前を過ぎたため予約できません。")
        with self.store.locked() as db:
            for existing in self.store.listing(db):
                if existing["state"] in ("cancelled", "completed"):
                    continue
                old = Broadcast.model_validate(existing["broadcast"])
                same_slot = (old.station == broadcast.station
                             and old.starts_at.weekday() == broadcast.starts_at.weekday()
                             and old.starts_at.time() == broadcast.starts_at.time())
                if existing["program_id"] == program["id"] and (old.id == broadcast.id or
                        (same_slot and (mode == "weekly" or existing["mode"] == "weekly"))):
                    if existing["mode"] != mode:
                        raise RecordingError("mode_conflict", "別の方式で予約済みです。変更する場合は既存予約を解除してください。")
                    return existing
            reservation_id = uuid.uuid4().hex
            now = self.clock().isoformat()
            db.execute("INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?,?)",
                       (reservation_id, program["id"], program["title"], mode, "pending_create", "",
                        broadcast.model_dump_json(), now, now))
            db.commit()
            row = dict(db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone())
            job = self._job(db, reservation_id, broadcast)
            self._register(db, row, job)
            return next(item for item in self.store.listing(db) if item["id"] == reservation_id)

    def cancel(self, reservation_id):
        with self.store.locked() as db:
            row = db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            if row is None:
                raise RecordingError("not_found", "予約が見つかりません。")
            if row["state"] in ("cancelled", "completed"):
                return next(item for item in self.store.listing(db) if item["id"] == reservation_id)
            # Intent survives a crash, and prevents the periodic task creating the next week.
            self._state(db, reservation_id, "pending_cancel")
            self._cancel_jobs(db, dict(row))
            return next(item for item in self.store.listing(db) if item["id"] == reservation_id)

    def _cancel_jobs(self, db, row):
        for job in self.store.jobs(db, row["id"]):
            if job["state"] in ("cancelled", "elapsed"):
                continue
            self._save_job(db, job, "pending_cancel")
            try:
                result = self.adapter.cancel(json.loads(job["payload"]))
                if result.get("state") not in ("cancelled", "absent", "elapsed"):
                    raise RecordingError("unconfirmed", "解除結果を確認できません。予約が残っている可能性があります。", True)
                self._save_job(db, job, "cancelled", result)
            except RecordingError as error:
                state = "cancel_unknown" if error.uncertain else "cancel_failed"
                self._save_job(db, job, state)
                self._state(db, row["id"], state, error.message)
                return
            except Exception:
                self._save_job(db, job, "cancel_unknown")
                self._state(db, row["id"], "cancel_unknown", "解除結果を確認できません。予約が残っている可能性があります。")
                return
        self._state(db, row["id"], "cancelled")

    def reconcile(self, reservation_id=None, retry=False):
        with self.store.locked() as db:
            rows = list(db.execute("SELECT * FROM reservations WHERE state NOT IN ('cancelled','completed')"))
            for raw in rows:
                row = dict(raw)
                if reservation_id and row["id"] != reservation_id:
                    continue
                if row["state"] in ("pending_cancel", "cancel_failed", "cancel_unknown"):
                    self._cancel_jobs(db, row)
                    continue
                jobs = self.store.jobs(db, row["id"])
                if not jobs:
                    # A crash between saving intent and saving its first job.
                    jobs = [self._job(db, row["id"], Broadcast.model_validate_json(row["broadcast"]))]
                job = jobs[-1]
                payload = json.loads(job["payload"])
                try:
                    remote = self.adapter.inspect(payload)
                    state = remote.get("state")
                    if state in ("scheduled", "running"):
                        self._save_job(db, job, state, remote)
                        self._state(db, row["id"], "active")
                    elif state == "elapsed":
                        self._save_job(db, job, "elapsed", remote)
                        if row["mode"] == "once":
                            self._state(db, row["id"], "completed")
                        else:
                            self._next_week(db, row, payload)
                    elif state == "cancelled":
                        self._save_job(db, job, "cancelled", remote)
                        self._state(db, row["id"], "create_failed", "録音側で解除されています。毎週予約も停止しています。")
                    elif state == "absent":
                        if retry or job["state"] == "pending_create":
                            self._register(db, row, job)
                        else:
                            self._save_job(db, job, "create_failed")
                            message = row["message"] if row["state"] == "create_failed" else ""
                            self._state(db, row["id"], "create_failed", message or "録音側に予約が見つかりません。再登録または解除してください。")
                    else:
                        raise RecordingError("unconfirmed", "録音側の状態を確認できません。", True)
                except RecordingError as error:
                    self._state(db, row["id"], "create_unknown", error.message)
                except Exception:
                    self._state(db, row["id"], "create_unknown", "録音側の状態を確認できません。状態を再確認してください。")
            return self.store.listing(db)

    def _next_week(self, db, row, previous):
        broadcast = Broadcast.model_validate({**previous, "id": "weekly"})
        start = broadcast.starts_at + timedelta(days=7)
        end = broadcast.ends_at + timedelta(days=7)
        while start <= self.clock() + timedelta(minutes=3):
            start += timedelta(days=7)
            end += timedelta(days=7)
        broadcast = broadcast.model_copy(update={"starts_at": start, "ends_at": end})
        job = self._job(db, row["id"], broadcast)
        self._register(db, row, job)
