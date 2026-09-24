import json
import sqlite3
import uuid
from datetime import datetime, timedelta

from radioflix.adapters.rfriends import weekly_title_key
from radioflix.schemas.reservations import Broadcast, JST, RecordingError


WEEKLY_WINDOW = timedelta(hours=2)


class ReservationService:
    def __init__(self, store, adapter, clock=None, programs=None, writes_enabled=False):
        self.store = store
        self.adapter = adapter
        self.clock = clock or (lambda: datetime.now(JST))
        self.programs = programs
        self.writes_enabled = writes_enabled

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
        if not self.writes_enabled:
            self._save_job(db, job, "waiting_write")
            self._state(db, row["id"], "waiting_write", "録音側への書き込みが無効です。予約情報を保持して待機しています。")
            return
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
        if mode == "weekly":
            return self.create_weekly(program, broadcast)
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
            db.execute("""INSERT INTO reservations
                          (id,program_id,title,mode,state,message,broadcast,created_at,updated_at,subscription_id)
                          VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
                       (reservation_id, program["id"], program["title"], "once", "pending_create", "",
                        broadcast.model_dump_json(), now, now))
            db.commit()
            row = dict(db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone())
            job = self._job(db, reservation_id, broadcast)
            self._register(db, row, job)
            return next(item for item in self.store.listing(db) if item["id"] == reservation_id)

    def list_subscriptions(self):
        return self.store.read_subscriptions()

    def create_weekly(self, program, broadcast):
        if broadcast.starts_at <= self.clock() + timedelta(minutes=3):
            raise RecordingError("too_late", "開始3分前を過ぎたため予約できません。")
        with self.store.locked() as db:
            for reservation in self.store.listing(db):
                if (reservation["program_id"] == program["id"]
                        and reservation["state"] not in ("cancelled", "completed")
                        and reservation["broadcast"]["id"] == broadcast.id
                        and not reservation.get("subscription_id")):
                    raise RecordingError("mode_conflict", "同じ放送回を単発予約済みです。毎週録音へ変更する場合は先に解除してください。")
            existing = db.execute(
                "SELECT id FROM weekly_subscriptions WHERE program_id=? AND station=? AND state='active'",
                (program["id"], broadcast.station),
            ).fetchone()
            if existing:
                return next(item for item in self.store.subscriptions(db) if item["id"] == existing["id"])
            subscription_id = uuid.uuid4().hex
            now = self.clock().isoformat()
            try:
                db.execute(
                    """INSERT INTO weekly_subscriptions
                       (id,program_id,station,title,title_key,region,anchor_weekday,anchor_time,
                        state,schedule_state,current_reservation_id,last_matched_broadcast,
                        next_expected_at,next_check_at,message,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (subscription_id, program["id"], broadcast.station, program["title"],
                     weekly_title_key(broadcast.title), broadcast.region, broadcast.starts_at.weekday(),
                     broadcast.starts_at.strftime("%H:%M:%S"), "active", "pending_create", None,
                     broadcast.model_dump_json(), (broadcast.starts_at + timedelta(days=7)).isoformat(),
                     None, "", now, now),
                )
            except sqlite3.IntegrityError:
                existing = db.execute(
                    "SELECT id FROM weekly_subscriptions WHERE program_id=? AND station=? AND state='active'",
                    (program["id"], broadcast.station),
                ).fetchone()
                return next(item for item in self.store.subscriptions(db) if item["id"] == existing["id"])
            reservation = self._create_occurrence(db, program, broadcast, subscription_id)
            self._sync_subscription(db, subscription_id, reservation)
            return next(item for item in self.store.subscriptions(db) if item["id"] == subscription_id)

    def _create_occurrence(self, db, program, broadcast, subscription_id, expected=None):
        reservation_id = uuid.uuid4().hex
        now = self.clock().isoformat()
        db.execute("""INSERT INTO reservations
                      (id,program_id,title,mode,state,message,broadcast,created_at,updated_at,subscription_id)
                      VALUES (?,?,?,?,?,?,?,?,?,?)""",
                   (reservation_id, program["id"], program["title"], "once", "pending_create", "",
                    broadcast.model_dump_json(), now, now, subscription_id))
        db.execute("""UPDATE weekly_subscriptions SET current_reservation_id=?,last_matched_broadcast=?,
                      next_expected_at=?,next_check_at=NULL,replacement_broadcast=NULL,updated_at=? WHERE id=?""",
                   (reservation_id, broadcast.model_dump_json(),
                    ((expected or broadcast.starts_at) + timedelta(days=7)).isoformat(), now, subscription_id))
        db.commit()
        row = dict(db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone())
        job = self._job(db, reservation_id, broadcast)
        self._register(db, row, job)
        return dict(db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone())

    def _sync_subscription(self, db, subscription_id, reservation):
        states = {
            "active": "scheduled", "waiting_write": "waiting_write",
            "pending_create": "pending_create", "create_unknown": "create_unknown",
            "create_failed": "create_failed", "pending_cancel": "cancelling",
            "cancel_failed": "cancel_failed", "cancel_unknown": "cancel_unknown",
        }
        db.execute("UPDATE weekly_subscriptions SET schedule_state=?,message=?,updated_at=? WHERE id=?",
                   (states.get(reservation["state"], reservation["state"]), reservation["message"],
                    self.clock().isoformat(), subscription_id))
        db.commit()

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

    def _cancel_jobs(self, db, row, audit=None):
        for job in self.store.jobs(db, row["id"]):
            if job["state"] in ("cancelled", "elapsed"):
                continue
            if job["state"] == "waiting_write" and not job["external_ref"]:
                self._save_job(db, job, "cancelled")
                continue
            self._save_job(db, job, "pending_cancel")
            if audit:
                audit("reservation_cancel_start", success=True, reservation_id=row["id"], job_id=job["id"])
            if not self.writes_enabled:
                self._state(db, row["id"], "pending_cancel", "録音側への書き込みが無効です。解除意図を保持しています。")
                return
            operation = "inspect"
            try:
                remote = self.adapter.inspect(json.loads(job["payload"]))
                if audit:
                    audit("gateway_inspect_result", success=remote.get("state") in ("scheduled", "absent", "elapsed", "cancelled"),
                          gateway_state=remote.get("state"))
                if remote.get("state") == "running":
                    raise RecordingError("too_late", "録音中のため解除できません。終了後に再確認してください。")
                operation = "cancel"
                result = self.adapter.cancel(json.loads(job["payload"]))
                if audit:
                    audit("gateway_cancel_result", success=result.get("state") in ("cancelled", "absent", "elapsed"),
                          gateway_state=result.get("state"))
                if result.get("state") not in ("cancelled", "absent", "elapsed"):
                    raise RecordingError("unconfirmed", "解除結果を確認できません。予約が残っている可能性があります。", True)
                self._save_job(db, job, "cancelled", result)
            except RecordingError as error:
                if audit:
                    audit(f"gateway_{operation}_result", success=False, error_code=error.code)
                state = "cancel_unknown" if error.uncertain else "cancel_failed"
                self._save_job(db, job, state)
                self._state(db, row["id"], state, error.message)
                return
            except Exception:
                if audit:
                    audit(f"gateway_{operation}_result", success=False, error_code="unknown")
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
                        if self.writes_enabled and (retry or job["state"] in ("pending_create", "waiting_write")):
                            self._register(db, row, job)
                        elif job["state"] == "waiting_write":
                            self._state(db, row["id"], "waiting_write", "録音側への書き込みが無効です。予約情報を保持して待機しています。")
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
            self._reconcile_subscriptions(db)
            return self.store.listing(db)

    def _next_week(self, db, row, previous):
        # Legacy method retained for callers during migration. New weekly rows
        # are subscription-owned and reconciled through the schedule.
        if row.get("subscription_id"):
            return
        broadcast = Broadcast.model_validate({**previous, "id": "weekly"})
        broadcast = broadcast.model_copy(update={"starts_at": broadcast.starts_at + timedelta(days=7),
                                                  "ends_at": broadcast.ends_at + timedelta(days=7)})
        job = self._job(db, row["id"], broadcast)
        self._register(db, row, job)

    def _reconcile_subscriptions(self, db):
        if self.programs is None:
            return
        for raw in db.execute("SELECT * FROM weekly_subscriptions WHERE state='active'").fetchall():
            subscription = dict(raw)
            if subscription["cancel_requested"]:
                self._finish_subscription_cancel(db, subscription)
                continue
            current_id = subscription["current_reservation_id"]
            if current_id:
                current = db.execute("SELECT * FROM reservations WHERE id=?", (current_id,)).fetchone()
                if current and current["state"] not in ("completed", "cancelled"):
                    if not (current["state"] in ("active", "waiting_write") and subscription["schedule_state"] in
                            ("ambiguous", "waiting_schedule", "waiting_program", "schedule_unavailable")):
                        self._sync_subscription(db, subscription["id"], dict(current))
                    if current["state"] in ("active", "waiting_write"):
                        self._refresh_occurrence(db, subscription, dict(current))
                    continue
                db.execute("UPDATE weekly_subscriptions SET current_reservation_id=NULL WHERE id=?",
                           (subscription["id"],))
                db.commit()
            next_check = subscription["next_check_at"]
            if next_check and datetime.fromisoformat(next_check) > self.clock():
                continue
            self._find_next_occurrence(db, subscription)

    def _find_next_occurrence(self, db, subscription):
        program = self.programs.find_program(subscription["program_id"])
        if not program:
            self._wait_for_schedule(db, subscription, "番組情報が見つかりません。", "waiting_program")
            return
        try:
            candidates = self.adapter.weekly_candidates(program, subscription["station"])
        except RecordingError as error:
            self._wait_for_schedule(db, subscription, error.message, "schedule_unavailable")
            return
        expected = datetime.fromisoformat(subscription["next_expected_at"])
        while expected < self.clock() - WEEKLY_WINDOW:
            expected += timedelta(days=7)
        matching = self._matching(subscription, candidates, expected)
        if len(matching) != 1:
            state = "ambiguous" if len(matching) > 1 else "waiting_schedule"
            message = ("次回放送の候補を一意に特定できません。" if matching
                       else "次回放送の番組表公開を待っています。")
            self._wait_for_schedule(db, subscription, message, state, expected)
            return
        broadcast = matching[0]
        duplicate = db.execute(
            "SELECT id FROM reservations WHERE subscription_id=? AND json_extract(broadcast,'$.id')=? AND state NOT IN ('cancelled','completed')",
            (subscription["id"], broadcast.id),
        ).fetchone()
        if duplicate:
            db.execute("UPDATE weekly_subscriptions SET current_reservation_id=?,schedule_state='scheduled',updated_at=? WHERE id=?",
                       (duplicate["id"], self.clock().isoformat(), subscription["id"]))
            db.commit()
            return
        reservation = self._create_occurrence(db, program, broadcast, subscription["id"], expected)
        self._sync_subscription(db, subscription["id"], reservation)

    def _wait_for_schedule(self, db, subscription, message, state, expected=None):
        db.execute("""UPDATE weekly_subscriptions SET schedule_state=?,message=?,next_expected_at=?,
                      next_check_at=?,updated_at=? WHERE id=?""",
                   (state, message, (expected or datetime.fromisoformat(subscription["next_expected_at"])).isoformat(),
                    (self.clock() + timedelta(minutes=30)).isoformat(), self.clock().isoformat(),
                    subscription["id"]))
        db.commit()

    def _matching(self, subscription, candidates, expected):
        # IDs from this provider identify a time slot, not a stable programme.
        unique = {item.id: item for item in candidates
                  if item.station == subscription["station"]
                  and weekly_title_key(item.title) == subscription["title_key"]
                  and item.starts_at > self.clock() + timedelta(minutes=3)
                  and abs(item.starts_at - expected) <= WEEKLY_WINDOW}
        return list(unique.values())

    def _refresh_occurrence(self, db, subscription, current):
        previous = Broadcast.model_validate_json(current["broadcast"])
        if previous.starts_at <= self.clock() + timedelta(minutes=3):
            return
        if subscription["next_check_at"] and datetime.fromisoformat(subscription["next_check_at"]) > self.clock():
            return
        expected = datetime.fromisoformat(subscription["next_expected_at"]) - timedelta(days=7)
        program = self.programs.find_program(subscription["program_id"])
        if not program:
            self._wait_for_schedule(db, subscription, "番組情報が見つかりません。", "waiting_program")
            return
        try:
            matching = self._matching(subscription, self.adapter.weekly_candidates(program, subscription["station"]), expected)
        except RecordingError as error:
            self._wait_for_schedule(db, subscription, error.message, "schedule_unavailable")
            return
        if len(matching) != 1:
            self._wait_for_schedule(db, subscription, "予約済み放送の変更を確認できません。既存予約を保持しています。",
                                    "ambiguous" if matching else "waiting_schedule")
            return
        candidate = matching[0]
        if candidate.starts_at == previous.starts_at and candidate.ends_at == previous.ends_at:
            self._sync_subscription(db, subscription["id"], current)
            db.execute("UPDATE weekly_subscriptions SET next_check_at=? WHERE id=?",
                       ((self.clock() + timedelta(minutes=30)).isoformat(), subscription["id"]))
            db.commit()
            return
        # Persist replacement intent before cancellation. A restart must never
        # create a second future job while the old cancellation is uncertain.
        db.execute("UPDATE weekly_subscriptions SET replacement_broadcast=?,next_expected_at=?,next_check_at=NULL WHERE id=?",
                   (candidate.model_dump_json(), expected.isoformat(), subscription["id"]))
        self._state(db, current["id"], "pending_cancel")
        self._cancel_jobs(db, current)
        refreshed = dict(db.execute("SELECT * FROM reservations WHERE id=?", (current["id"],)).fetchone())
        self._sync_subscription(db, subscription["id"], refreshed)
        # The next reconcile rechecks the schedule after confirmed cancellation.

    def _finish_subscription_cancel(self, db, subscription):
        current = db.execute("SELECT * FROM reservations WHERE id=?", (subscription["current_reservation_id"],)).fetchone()
        if current and current["state"] not in ("completed", "cancelled"):
            self._sync_subscription(db, subscription["id"], dict(current))
            return
        db.execute("UPDATE weekly_subscriptions SET state='cancelled',schedule_state='cancelled',message='',next_check_at=NULL,updated_at=? WHERE id=?",
                   (self.clock().isoformat(), subscription["id"]))
        db.commit()

    def cancel_subscription(self, subscription_id, audit=None):
        with self.store.locked() as db:
            row = db.execute("SELECT * FROM weekly_subscriptions WHERE id=?", (subscription_id,)).fetchone()
            if row is None:
                raise RecordingError("not_found", "毎週録音が見つかりません。")
            if audit:
                audit("subscription_found", success=True)
            if row["state"] != "cancelled":
                db.execute("UPDATE weekly_subscriptions SET cancel_requested=1,next_check_at=NULL WHERE id=?", (subscription_id,))
                reservation = db.execute("SELECT * FROM reservations WHERE id=?", (row["current_reservation_id"],)).fetchone()
                if reservation and reservation["state"] not in ("completed", "cancelled"):
                    self._state(db, reservation["id"], "pending_cancel")
                    self._cancel_jobs(db, dict(reservation), audit=audit)
                self._finish_subscription_cancel(db, dict(row))
            result = next(item for item in self.store.subscriptions(db) if item["id"] == subscription_id)
            if audit:
                audit("db_update_result", success=result["state"] == "cancelled",
                      subscription_state=result["state"], reservation_state=(
                          db.execute("SELECT state FROM reservations WHERE id=?", (result["current_reservation_id"],)).fetchone()[0]
                          if result["current_reservation_id"] else None))
            return result
