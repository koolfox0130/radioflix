"""Offline API/state-machine tests. No real gateway, network or recorder calls."""
import io
import gzip
import json
import os
import secrets
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from pydantic import ValidationError

from radioflix.adapters.rfriends import RfriendsAdapter, normalized_title
from radioflix.adapters import rfriends_gateway as gateway
from radioflix.database.reservations import ReservationStore
from radioflix.schemas.reservations import Broadcast, JST, RecordingError
from radioflix.services.reservation_service import ReservationService


class FakeAdapter:
    def __init__(self, broadcast):
        self.broadcast = broadcast
        self.remote = {}
        self.creates = []
        self.cancels = []
        self.create_error = None
        self.cancel_error = None
        self.inspect_error = None
        self.create_hook = None
        self.cancel_hook = None
        self.candidates = [broadcast]

    def broadcasts(self, program):
        return [self.broadcast]

    def weekly_candidates(self, program, station):
        return list(self.candidates)

    def create(self, job):
        self.creates.append(job)
        if self.create_error:
            raise self.create_error
        self.remote[job["id"]] = "scheduled"
        if self.create_hook:
            self.create_hook(job)
        return {"state": "scheduled", "job_id": "123", "name": "owned-job"}

    def inspect(self, job):
        if self.inspect_error:
            raise self.inspect_error
        return {"state": self.remote.get(job["id"], "absent"), "job_id": "123"}

    def cancel(self, job):
        self.cancels.append(job)
        if self.cancel_error:
            raise self.cancel_error
        self.remote[job["id"]] = "cancelled"
        if self.cancel_hook:
            self.cancel_hook(job)
        return {"state": "cancelled"}


class FakePrograms:
    def __init__(self, program):
        self.program = program

    def find_program(self, program_id):
        return self.program if self.program["id"] == program_id else None


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2030, 1, 1, 12, tzinfo=JST)
        self.broadcast = Broadcast(id="broadcast-1", station="TBS", title="テスト番組",
                                   starts_at=self.now + timedelta(hours=12), ends_at=self.now + timedelta(hours=14))
        self.adapter = FakeAdapter(self.broadcast)
        self.store = ReservationStore(Path(self.temp.name) / "db.sqlite3")
        self.program = {"id": "program-1", "title": "テスト番組"}
        self.programs = FakePrograms(self.program)
        self.service = ReservationService(self.store, self.adapter, lambda: self.now,
                                          self.programs, writes_enabled=True)

    def create(self, mode="once"):
        return self.service.create(self.program, self.broadcast, mode)

    def test_once_persists_mapping_and_cancels_idempotently(self):
        row = self.create()
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["jobs"][0]["external_ref"]["job_id"], "123")
        cancelled = self.service.cancel(row["id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(self.service.cancel(row["id"])["broadcast"], cancelled["broadcast"])
        self.assertEqual(len(self.adapter.cancels), 1)

    def test_duplicate_concurrent_requests_share_one_job(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.create(), range(2)))
        self.assertEqual(rows[0]["id"], rows[1]["id"])
        self.assertEqual(len(self.adapter.creates), 1)

    def test_mode_change_does_not_silently_return_wrong_mode(self):
        self.create()
        with self.assertRaises(RecordingError):
            self.create("weekly")
        self.assertEqual(len(self.adapter.creates), 1)

    def test_failed_create_is_not_reserved(self):
        self.adapter.create_error = RecordingError("conflict", "既存予約があります。")
        row = self.create()
        self.assertEqual(row["state"], "create_failed")
        self.assertFalse(self.adapter.remote)

    def test_lost_create_response_reconciles_without_duplicate(self):
        def lose_response(job):
            raise RecordingError("timeout", "結果不明", True)
        self.adapter.create_hook = lose_response
        row = self.create()
        self.assertEqual(row["state"], "create_unknown")
        self.service.reconcile()
        self.assertEqual(self.service.list()[0]["state"], "active")
        self.assertEqual(len(self.adapter.creates), 1)

    def test_crash_after_registration_recovers_from_journal(self):
        def crash(job):
            raise KeyboardInterrupt()
        self.adapter.create_hook = crash
        with self.assertRaises(KeyboardInterrupt):
            self.create()
        self.assertEqual(self.service.list()[0]["state"], "pending_create")
        self.service.reconcile()
        self.assertEqual(self.service.list()[0]["state"], "active")
        self.assertEqual(len(self.adapter.creates), 1)

    def test_retry_reuses_job_id(self):
        self.adapter.create_error = RecordingError("timeout", "結果不明", True)
        row = self.create()
        self.adapter.create_error = None
        self.service.reconcile(row["id"])
        self.assertEqual(self.service.list()[0]["state"], "create_failed")
        self.assertEqual(len(self.adapter.creates), 1)
        self.service.reconcile(row["id"], retry=True)
        self.assertEqual(self.adapter.creates[0]["id"], self.adapter.creates[1]["id"])
        self.assertEqual(self.service.list()[0]["state"], "active")

    def test_cancel_failure_keeps_intent_and_stops_weekly_generation(self):
        row = self.create("weekly")
        self.adapter.cancel_error = RecordingError("timeout", "解除結果不明", True)
        self.assertEqual(self.service.cancel_subscription(row["id"])["state"], "active")
        self.now += timedelta(days=8)
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 1)
        self.adapter.cancel_error = None
        self.service.reconcile()
        self.assertEqual(self.service.list_subscriptions()[0]["state"], "cancelled")

    def test_weekly_cancel_audit_reports_gateway_and_database_outcomes(self):
        subscription = self.create("weekly")
        events = []
        result = self.service.cancel_subscription(subscription["id"],
                                                  audit=lambda stage, **details: events.append((stage, details)))
        stages = [stage for stage, _ in events]
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(stages, ["subscription_found", "reservation_cancel_start",
                                  "gateway_inspect_result", "gateway_cancel_result", "db_update_result"])
        self.assertTrue(events[2][1]["success"])
        self.assertEqual(events[3][1]["gateway_state"], "cancelled")
        self.assertTrue(events[4][1]["success"])

    def test_weekly_cancel_audit_reports_gateway_failure(self):
        subscription = self.create("weekly")
        self.adapter.cancel_error = RecordingError("timeout", "結果不明", True)
        events = []
        result = self.service.cancel_subscription(subscription["id"],
                                                  audit=lambda stage, **details: events.append((stage, details)))
        self.assertEqual(result["state"], "active")
        gateway_event = next(details for stage, details in events if stage == "gateway_cancel_result")
        self.assertFalse(gateway_event["success"])
        database_event = next(details for stage, details in events if stage == "db_update_result")
        self.assertFalse(database_event["success"])

    def test_cancel_deterministic_failure_is_not_cancelled(self):
        row = self.create()
        self.adapter.cancel_error = RecordingError("too_late", "録音中です。")
        self.assertEqual(self.service.cancel(row["id"])["state"], "cancel_failed")
        self.assertEqual(self.adapter.remote[row["jobs"][0]["id"]], "scheduled")

    def test_crash_during_cancel_recovers(self):
        row = self.create()
        def crash(job):
            raise KeyboardInterrupt()
        self.adapter.cancel_hook = crash
        with self.assertRaises(KeyboardInterrupt):
            self.service.cancel(row["id"])
        self.adapter.cancel_hook = None
        self.service.reconcile()
        self.assertEqual(self.service.list()[0]["state"], "cancelled")

    def test_weekly_advances_and_persists_across_restart(self):
        row = self.create("weekly")
        occurrence = self.service.list()[0]
        self.adapter.remote[occurrence["jobs"][0]["id"]] = "elapsed"
        expected = self.broadcast.starts_at + timedelta(days=7)
        self.adapter.candidates = [self.broadcast.model_copy(update={
            "id": "broadcast-2", "starts_at": expected, "ends_at": expected + timedelta(hours=2)
        })]
        self.now += timedelta(days=1)
        restarted = ReservationService(self.store, self.adapter, lambda: self.now,
                                       self.programs, writes_enabled=True)
        restarted.reconcile()
        subscription = restarted.list_subscriptions()[0]
        latest = next(item for item in restarted.list() if item["id"] == subscription["current_reservation_id"])
        self.assertEqual(datetime.fromisoformat(latest["broadcast"]["starts_at"]), expected)
        self.assertEqual(len(self.adapter.creates), 2)
        restarted.reconcile()
        self.assertEqual(len(self.adapter.creates), 2)
        restarted.cancel_subscription(row["id"])
        self.assertEqual([job["id"] for job in self.adapter.cancels], [latest["jobs"][0]["id"]])

    def test_once_completion_never_creates_next_week(self):
        row = self.create()
        self.adapter.remote[row["jobs"][0]["id"]] = "elapsed"
        self.now += timedelta(days=1)
        self.service.reconcile()
        self.assertEqual(self.service.list()[0]["state"], "completed")
        self.assertEqual(len(self.adapter.creates), 1)

    def test_missing_job_and_disconnected_adapter_are_not_active(self):
        row = self.create()
        self.adapter.remote.clear()
        self.service.reconcile()
        self.assertEqual(self.service.list()[0]["state"], "create_failed")
        self.adapter.inspect_error = RecordingError("unreachable", "接続できません。", True)
        self.service.reconcile(row["id"])
        self.assertEqual(self.service.list()[0]["state"], "create_unknown")

    def test_pending_operation_does_not_block_listing(self):
        observed = []
        self.adapter.create_hook = lambda job: observed.append(self.service.list()[0]["state"])
        self.create()
        self.assertEqual(observed, ["pending_create"])

    def test_stale_status_does_not_claim_current_confirmation(self):
        self.create()
        self.now += timedelta(minutes=4)
        self.assertEqual(self.service.list()[0]["state"], "stale")

    def test_start_guard_and_timezone(self):
        self.broadcast.starts_at = self.now + timedelta(minutes=2)
        with self.assertRaises(RecordingError):
            self.create()
        with self.assertRaises(ValidationError):
            Broadcast(id="bad", station="TBS", title="bad", starts_at="2030-01-01T12:00:00", ends_at="2030-01-01T13:00:00")


class WeeklySubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2030, 1, 1, 12, tzinfo=JST)
        self.first = Broadcast(id="week-1", station="TBS", title="テスト番組",
                               starts_at=self.now + timedelta(hours=12),
                               ends_at=self.now + timedelta(hours=13))
        self.program = {"id": "program-1", "title": "テスト番組"}
        self.programs = FakePrograms(self.program)
        self.adapter = FakeAdapter(self.first)
        self.store = ReservationStore(Path(self.temp.name) / "db.sqlite3")
        self.service = ReservationService(self.store, self.adapter, lambda: self.now,
                                          self.programs, writes_enabled=True)

    def subscribe(self):
        return self.service.create(self.program, self.first, "weekly")

    def finish_current(self, subscription):
        occurrence = next(item for item in self.service.list()
                          if item["id"] == subscription["current_reservation_id"])
        self.adapter.remote[occurrence["jobs"][0]["id"]] = "elapsed"
        self.now += timedelta(days=1)
        return occurrence

    def next_broadcast(self, *, minutes=0, duration=60, title="テスト番組", station="TBS", weeks=1, identifier="week-2"):
        start = self.first.starts_at + timedelta(days=7 * weeks, minutes=minutes)
        return Broadcast(id=identifier, station=station, title=title, starts_at=start,
                         ends_at=start + timedelta(minutes=duration))

    def test_weekly_registration_deduplicates_and_survives_restart(self):
        first = self.subscribe()
        second = self.subscribe()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.adapter.creates), 1)
        restarted = ReservationService(self.store, self.adapter, lambda: self.now,
                                       self.programs, writes_enabled=True)
        self.assertEqual(restarted.list_subscriptions()[0]["id"], first["id"])

    def test_schedule_unpublished_keeps_subscription_waiting(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        self.adapter.candidates = []
        self.service.reconcile()
        result = self.service.list_subscriptions()[0]
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["schedule_state"], "waiting_schedule")
        self.assertIsNone(result["current_reservation_id"])

    def test_one_week_break_advances_expected_week_without_fake_job(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        self.adapter.candidates = []
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 1)
        self.now = self.first.starts_at + timedelta(days=7, hours=7)
        following = self.next_broadcast(weeks=2, identifier="week-3")
        self.adapter.candidates = [following]
        self.service.reconcile()
        result = self.service.list_subscriptions()[0]
        self.assertEqual(result["last_matched_broadcast"]["id"], "week-3")
        self.assertEqual(len(self.adapter.creates), 2)

    def test_time_duration_and_light_title_changes_are_followed(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        changed = self.next_broadcast(minutes=10, duration=90, title="【新】テスト番組")
        self.adapter.candidates = [changed]
        self.service.reconcile()
        result = self.service.list_subscriptions()[0]
        self.assertEqual(result["last_matched_broadcast"]["starts_at"], changed.model_dump(mode="json")["starts_at"])
        self.assertEqual(result["last_matched_broadcast"]["ends_at"], changed.model_dump(mode="json")["ends_at"])

    def test_station_mismatch_and_ambiguous_candidates_never_register(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        self.adapter.candidates = [self.next_broadcast(station="LFR")]
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 1)
        self.now += timedelta(minutes=31)
        self.adapter.candidates = [self.next_broadcast(minutes=-10, identifier="a"),
                                   self.next_broadcast(minutes=10, identifier="b")]
        self.service.reconcile()
        self.assertEqual(self.service.list_subscriptions()[0]["schedule_state"], "ambiguous")
        self.assertEqual(len(self.adapter.creates), 1)

    def test_repeated_reconcile_creates_only_one_next_occurrence(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        self.adapter.candidates = [self.next_broadcast()]
        self.service.reconcile()
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 2)
        linked = [item for item in self.service.list() if item.get("subscription_id") == subscription["id"]]
        self.assertEqual(len(linked), 2)

    def test_conflict_keeps_subscription_and_occurrence_for_safe_retry(self):
        self.adapter.create_error = RecordingError("conflict", "既存予約があります。")
        subscription = self.subscribe()
        self.assertEqual(subscription["state"], "active")
        self.assertEqual(subscription["schedule_state"], "create_failed")
        self.assertEqual(len(self.service.list()), 1)

    def test_cancel_is_idempotent_and_only_cancels_current_owned_job(self):
        subscription = self.subscribe()
        occurrence = self.service.list()[0]
        first = self.service.cancel_subscription(subscription["id"])
        second = self.service.cancel_subscription(subscription["id"])
        self.assertEqual(first["state"], "cancelled")
        self.assertEqual(second["state"], "cancelled")
        self.assertEqual([job["id"] for job in self.adapter.cancels], [occurrence["jobs"][0]["id"]])

    def test_running_occurrence_is_not_claimed_cancelled(self):
        subscription = self.subscribe()
        occurrence = self.service.list()[0]
        self.adapter.cancel_error = RecordingError("too_late", "録音中です。")
        self.service.cancel_subscription(subscription["id"])
        current = next(item for item in self.service.list() if item["id"] == occurrence["id"])
        self.assertEqual(current["state"], "cancel_failed")
        self.assertEqual(self.adapter.remote[occurrence["jobs"][0]["id"]], "scheduled")

    def test_writes_disabled_persists_and_never_calls_create_or_cancel(self):
        service = ReservationService(self.store, self.adapter, lambda: self.now,
                                     self.programs, writes_enabled=False)
        subscription = service.create(self.program, self.first, "weekly")
        self.assertEqual(service.list_subscriptions()[0]["schedule_state"], "waiting_write")
        self.assertFalse(self.adapter.creates)
        service.reconcile()
        self.assertFalse(self.adapter.creates)
        service.cancel_subscription(subscription["id"])
        self.assertFalse(self.adapter.cancels)
        self.assertEqual(service.list_subscriptions()[0]["state"], "cancelled")

    def test_weekly_registration_success(self):
        subscription = self.subscribe()
        self.assertEqual(subscription["state"], "active")
        self.assertEqual(subscription["schedule_state"], "scheduled")
        self.assertEqual(self.service.list()[0]["subscription_id"], subscription["id"])

    def test_weekly_concurrent_registration_deduplicates(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.subscribe(), range(2)))
        self.assertEqual(rows[0]["id"], rows[1]["id"])
        self.assertEqual(len(self.adapter.creates), 1)

    def test_restart_opens_existing_database(self):
        subscription = self.subscribe()
        restarted = ReservationService(ReservationStore(self.store.path), self.adapter,
                                       lambda: self.now, self.programs, writes_enabled=True)
        self.assertEqual(restarted.list_subscriptions()[0]["id"], subscription["id"])
        self.assertEqual(restarted.list()[0]["id"], subscription["current_reservation_id"])

    def test_start_time_changes_ten_and_thirty_minutes(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        for weeks, minutes in ((1, 10), (2, 30)):
            candidate = self.next_broadcast(weeks=weeks, minutes=minutes, identifier=f"week-{weeks + 1}")
            self.adapter.candidates = [candidate]
            self.service.reconcile()
            subscription = self.service.list_subscriptions()[0]
            self.assertEqual(subscription["last_matched_broadcast"]["starts_at"], candidate.starts_at.isoformat())
            # The normal weekly anchor must not drift with each temporary delay.
            self.assertEqual(datetime.fromisoformat(subscription["next_expected_at"]),
                             self.first.starts_at + timedelta(weeks=weeks + 1))
            self.finish_current(subscription)
            self.now = candidate.ends_at + timedelta(hours=1)

    def test_duration_extension_and_shortening(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        for weeks, duration in ((1, 90), (2, 30)):
            candidate = self.next_broadcast(weeks=weeks, duration=duration, identifier=f"duration-{weeks}")
            self.adapter.candidates = [candidate]
            self.service.reconcile()
            subscription = self.service.list_subscriptions()[0]
            self.assertEqual(subscription["last_matched_broadcast"]["ends_at"], candidate.ends_at.isoformat())
            self.finish_current(subscription)
            self.now = candidate.ends_at + timedelta(hours=1)

    def test_wrong_title_outside_window_and_past_never_match(self):
        subscription = self.subscribe()
        self.finish_current(subscription)
        self.adapter.candidates = [self.next_broadcast(title="別番組"),
                                   self.next_broadcast(minutes=121, identifier="late"),
                                   self.first]
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 1)
        self.assertEqual(self.service.list_subscriptions()[0]["schedule_state"], "waiting_schedule")

    def test_scheduled_time_change_cancels_before_replacement_and_keeps_history(self):
        subscription = self.subscribe()
        original = self.service.list()[0]
        candidate = self.next_broadcast(weeks=0, minutes=30, duration=90, identifier="changed")
        self.adapter.candidates = [candidate]
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 1)
        self.assertEqual(self.adapter.remote[original["jobs"][0]["id"]], "cancelled")
        restarted = ReservationService(ReservationStore(self.store.path), self.adapter,
                                       lambda: self.now, self.programs, writes_enabled=True)
        restarted.reconcile()
        restarted.reconcile()
        rows = restarted.list()
        self.assertEqual(len(self.adapter.creates), 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["state"] == "active" for row in rows), 1)
        old = next(row for row in rows if row["id"] == original["id"])
        self.assertEqual(old["state"], "cancelled")
        self.assertEqual(old["broadcast"], original["broadcast"])
        self.assertTrue(all(row["created_at"] and row["updated_at"] and row["subscription_id"] == subscription["id"] for row in rows))

    def test_schedule_replacement_cancel_failure_never_creates_second_job(self):
        self.subscribe()
        self.adapter.candidates = [self.next_broadcast(weeks=0, minutes=10, identifier="changed")]
        self.adapter.cancel_error = RecordingError("ownership", "所有情報を確認できません。", True)
        self.service.reconcile()
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 1)
        self.assertEqual(self.service.list_subscriptions()[0]["schedule_state"], "cancel_unknown")
        self.adapter.cancel_error = None
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 2)

    def test_cancel_failure_remains_active_and_retry_succeeds(self):
        subscription = self.subscribe()
        self.adapter.cancel_error = RecordingError("unreachable", "解除できません。", True)
        failed = self.service.cancel_subscription(subscription["id"])
        self.assertEqual(failed["state"], "active")
        self.assertEqual(failed["schedule_state"], "cancel_unknown")
        self.assertTrue(failed["cancel_requested"])
        self.assertEqual(failed["message"], "解除できません。")
        self.adapter.cancel_error = None
        result = self.service.cancel_subscription(subscription["id"])
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(len(self.service.list()), 1)

    def test_running_job_is_never_sent_to_cancel(self):
        subscription = self.subscribe()
        job = self.service.list()[0]["jobs"][0]
        self.adapter.remote[job["id"]] = "running"
        result = self.service.cancel_subscription(subscription["id"])
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["schedule_state"], "cancel_failed")
        self.assertFalse(self.adapter.cancels)
        self.adapter.remote[job["id"]] = "elapsed"
        self.service.reconcile()
        self.assertEqual(self.service.list_subscriptions()[0]["state"], "cancelled")

    def test_cancel_weekly_leaves_unrelated_reservations_untouched(self):
        subscription = self.subscribe()
        once = self.service.create({"id": "other", "title": "別番組"}, self.next_broadcast(station="LFR"), "once")
        self.service.cancel_subscription(subscription["id"])
        self.assertEqual(self.adapter.remote[once["jobs"][0]["id"]], "scheduled")
        self.assertNotIn(once["jobs"][0]["id"], [job["id"] for job in self.adapter.cancels])

    def test_disabled_writes_never_reach_gateway_transport(self):
        adapter = RfriendsAdapter(url="http://fake.invalid", token_file=str(Path(self.temp.name) / "token"))
        service = ReservationService(self.store, adapter, lambda: self.now, self.programs, writes_enabled=False)
        with patch.object(adapter, "_call", side_effect=AssertionError("No gateway call allowed")):
            subscription = service.create(self.program, self.first, "weekly")
            service.cancel_subscription(subscription["id"])
        self.assertEqual(service.list_subscriptions()[0]["state"], "cancelled")

    def test_scheduled_ambiguous_change_keeps_original(self):
        self.subscribe()
        self.adapter.candidates = [self.next_broadcast(weeks=0, minutes=10, identifier="a"),
                                   self.next_broadcast(weeks=0, minutes=30, identifier="b")]
        self.service.reconcile()
        self.assertEqual(self.service.list_subscriptions()[0]["schedule_state"], "ambiguous")
        self.assertFalse(self.adapter.cancels)
        self.assertEqual(len(self.adapter.creates), 1)


    def test_replacement_crash_keeps_new_broadcast_and_anchor_atomic(self):
        self.subscribe()
        changed = self.next_broadcast(weeks=0, minutes=30, identifier="changed")
        self.adapter.candidates = [changed]
        self.service.reconcile()
        def crash(job):
            raise KeyboardInterrupt()
        self.adapter.create_hook = crash
        with self.assertRaises(KeyboardInterrupt):
            self.service.reconcile()
        self.adapter.create_hook = None
        restarted = ReservationService(ReservationStore(self.store.path), self.adapter,
                                       lambda: self.now, self.programs, writes_enabled=True)
        restarted.reconcile()
        result = restarted.list_subscriptions()[0]
        self.assertEqual(result["last_matched_broadcast"]["id"], "changed")
        self.assertEqual(datetime.fromisoformat(result["next_expected_at"]), self.first.starts_at + timedelta(days=7))
        self.assertEqual(len(self.adapter.creates), 2)
        self.assertEqual(len(self.adapter.cancels), 1)

    def test_ambiguous_warning_survives_reconcile_until_schedule_recheck(self):
        self.subscribe()
        self.adapter.candidates = []
        self.service.reconcile()
        self.service.reconcile()
        self.assertEqual(self.service.list_subscriptions()[0]["schedule_state"], "waiting_schedule")
        self.now += timedelta(minutes=31)
        self.adapter.candidates = [self.first]
        self.service.reconcile()
        self.assertEqual(self.service.list_subscriptions()[0]["schedule_state"], "scheduled")



class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token = secrets.token_urlsafe(32)
        self.token_file = Path(self.temp.name) / 'token'
        self.token_file.write_text(self.token)
        self.adapter = RfriendsAdapter('http://gateway.invalid', str(self.token_file))

    def test_unconfigured_makes_no_request(self):
        with patch('radioflix.adapters.rfriends.gateway_open') as transport:
            with self.assertRaises(RecordingError):
                RfriendsAdapter(url='').create({})
            transport.assert_not_called()

    def test_timeout_is_uncertain_and_does_not_expose_details(self):
        with patch('radioflix.adapters.rfriends.gateway_open', side_effect=URLError(self.token)):
            with self.assertRaises(RecordingError) as error:
                self.adapter.create({})
        self.assertTrue(error.exception.uncertain)
        self.assertNotIn(self.token, str(error.exception))

    def test_authorization_and_normalized_conflict(self):
        error = HTTPError('http://gateway.invalid', 409, self.token, {}, io.BytesIO(b'{"detail":{"code":"conflict"}}'))
        with patch('radioflix.adapters.rfriends.gateway_open', side_effect=error) as transport:
            with self.assertRaises(RecordingError) as caught:
                self.adapter.create({})
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(caught.exception.code, 'conflict')
        self.assertEqual(transport.call_args.args[0].get_header('Authorization'), 'Bearer ' + self.token)
        self.assertNotIn(self.token, str(caught.exception))

    def test_schedule_parser_cache_and_region(self):
        xml = b'<radiko><stations><station id="TBS"><progs><prog ft="20300102010000" to="20300102030000"><title>Test</title></prog></progs></station></stations></radiko>'
        self.adapter.area = 'JP27'
        with patch('radioflix.adapters.rfriends.urlopen', return_value=io.BytesIO(xml)) as transport:
            first = self.adapter._day('20300101')
            second = self.adapter._day('20300101')
        self.assertEqual(first, second)
        self.assertEqual(first[0].region, 'JP27')
        self.assertEqual(first[0].starts_at.hour, 1)
        transport.assert_called_once()

    @staticmethod
    def schedule_xml(date='20300102'):
        return (f'<radiko><stations><station id="TBS"><progs><prog ft="{date}010000" '
                f'to="{date}030000"><title>Test</title></prog></progs></station></stations></radiko>'
                .encode())

    @staticmethod
    def schedule_response(body, content_encoding=None):
        response = io.BytesIO(body)
        response.headers = {'Content-Encoding': content_encoding} if content_encoding else {}
        return response

    def test_schedule_plain_xml_parses(self):
        with patch('radioflix.adapters.rfriends.urlopen',
                   return_value=self.schedule_response(self.schedule_xml())):
            self.assertEqual(len(self.adapter._fetch_day('20300101')), 1)

    def test_schedule_gzip_xml_parses_by_body_magic(self):
        body = gzip.compress(self.schedule_xml())
        self.assertEqual(body[:2], b'\x1f\x8b')
        with patch('radioflix.adapters.rfriends.urlopen',
                   return_value=self.schedule_response(body)):
            self.assertEqual(len(self.adapter._fetch_day('20300101')), 1)

    def test_schedule_gzip_header_with_already_decoded_xml_is_not_decompressed(self):
        with patch('radioflix.adapters.rfriends.urlopen',
                   return_value=self.schedule_response(self.schedule_xml(), 'gzip')):
            self.assertEqual(len(self.adapter._fetch_day('20300101')), 1)

    def test_schedule_corrupt_gzip_retries_once_then_fails(self):
        bad = self.schedule_response(b'\x1f\x8bnot-a-valid-gzip-stream', 'gzip')
        with patch('radioflix.adapters.rfriends.urlopen', side_effect=[bad, bad]) as transport, \
                patch('radioflix.adapters.rfriends.time.sleep') as sleep:
            with self.assertRaises(RecordingError) as caught:
                self.adapter._day('20300101')
        self.assertEqual(caught.exception.code, 'schedule_unavailable')
        self.assertEqual(transport.call_count, 2)
        sleep.assert_called_once_with(0.2)

    def test_schedule_gzip_failure_retries_and_then_succeeds(self):
        bad = self.schedule_response(b'\x1f\x8btruncated', 'gzip')
        good = self.schedule_response(gzip.compress(self.schedule_xml()), 'gzip')
        with patch('radioflix.adapters.rfriends.urlopen', side_effect=[bad, good]) as transport, \
                patch('radioflix.adapters.rfriends.time.sleep') as sleep:
            result = self.adapter._day('20300101')
        self.assertEqual(len(result), 1)
        self.assertEqual(transport.call_count, 2)
        sleep.assert_called_once_with(0.2)

    def test_broadcasts_skips_one_gzip_failure_when_other_days_succeed(self):
        calls = []
        now = datetime.now(JST)
        radio_day = (now - timedelta(hours=5)).date()

        def response(url, timeout):
            date = url.rsplit('/', 2)[-2]
            calls.append(date)
            if date == radio_day.strftime('%Y%m%d'):
                return self.schedule_response(b'\x1f\x8bbroken-gzip', 'gzip')
            day = datetime.strptime(date, '%Y%m%d')
            start = (day + timedelta(days=1)).strftime('%Y%m%d')
            xml = self.schedule_xml(start)
            return self.schedule_response(gzip.compress(xml), 'gzip')

        with patch('radioflix.adapters.rfriends.urlopen', side_effect=response), \
                patch('radioflix.adapters.rfriends.time.sleep'):
            result = self.adapter.broadcasts({'raw_name': 'TBS_Test', 'title': 'Test'})
        self.assertEqual(len(calls), 9)
        self.assertTrue(result)

    def test_broadcasts_raises_when_all_gzip_days_fail(self):
        bad = self.schedule_response(b'\x1f\x8bbroken-gzip', 'gzip')
        with patch('radioflix.adapters.rfriends.urlopen', return_value=bad), \
                patch('radioflix.adapters.rfriends.time.sleep'):
            with self.assertRaises(RecordingError) as caught:
                self.adapter.broadcasts({'raw_name': 'TBS_Test', 'title': 'Test'})
        self.assertEqual(caught.exception.code, 'schedule_unavailable')

    def test_entity_xml_and_unpublished_day(self):
        with patch('radioflix.adapters.rfriends.urlopen', return_value=io.BytesIO(b'<!DOCTYPE a><a/>')):
            with self.assertRaises(RecordingError):
                self.adapter._day('20300101')
        with patch('radioflix.adapters.rfriends.urlopen', side_effect=HTTPError('x', 404, '', {}, None)):
            self.assertEqual(self.adapter._day('20300108'), [])

    def test_schedule_http_failure_retries_once(self):
        xml = b'<radiko><stations><station id="TBS"><progs><prog ft="20300102010000" to="20300102030000"><title>Test</title></prog></progs></station></stations></radiko>'
        first_error = HTTPError('x', 503, '', {}, None)
        with patch('radioflix.adapters.rfriends.urlopen', side_effect=[first_error, io.BytesIO(xml)]) as transport, \
                patch('radioflix.adapters.rfriends.time.sleep') as sleep:
            result = self.adapter._day('20300101')
        self.assertEqual(len(result), 1)
        self.assertEqual(transport.call_count, 2)
        sleep.assert_called_once_with(0.2)

    def test_broadcasts_skips_one_failed_day(self):
        start = datetime.now(JST) + timedelta(days=1)
        broadcast = Broadcast(id='ok', station='TBS', title='Test',
                              starts_at=start, ends_at=start + timedelta(hours=1))
        calls = []

        def day(date):
            calls.append(date)
            if len(calls) == 1:
                raise RecordingError('schedule_unavailable', 'failed')
            return [broadcast]

        self.adapter._day = day
        result = self.adapter.broadcasts({'raw_name': 'TBS_Test', 'title': 'Test'})
        self.assertEqual(result, [broadcast])
        self.assertEqual(len(calls), 8)

    def test_broadcasts_fails_only_when_all_days_fail(self):
        self.adapter._day = lambda date: (_ for _ in ()).throw(RecordingError('schedule_unavailable', 'failed'))
        with self.assertRaises(RecordingError) as error:
            self.adapter.broadcasts({'raw_name': 'TBS_Test', 'title': 'Test'})
        self.assertEqual(error.exception.code, 'schedule_unavailable')

    def test_program_title_matching(self):
        self.assertEqual(normalized_title('JUNK-テスト 番組'), normalized_title('テスト番組'))
        self.assertEqual(normalized_title('三四郎のオールナイトニッポン0(ZERO)'), normalized_title('三四郎のANN0'))
        self.assertEqual(normalized_title('オールナイトニッポンZERO'), normalized_title('ANN0'))

    def test_gateway_redirect_does_not_forward_credentials(self):
        from radioflix.adapters.rfriends import NoGatewayRedirect
        self.assertIsNone(NoGatewayRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid'))

    def test_gateway_auth_and_default_write_lock(self):
        start = datetime.now(JST) + timedelta(days=1)
        body = {'operation': 'create', 'job': {'id': 'a' * 32, 'station': 'TBS', 'title': 'Test', 'starts_at': start.isoformat(), 'ends_at': (start + timedelta(hours=1)).isoformat()}}
        with patch.dict(os.environ, {'RFRIENDS_TOKEN_FILE': str(self.token_file), 'RFRIENDS_ENABLE_WRITES': '0'}), patch.object(gateway, 'run_driver') as driver:
            from fastapi import HTTPException
            request = gateway.Operation.model_validate(body)
            with self.assertRaises(HTTPException) as denied:
                gateway.execute(request, '')
            self.assertEqual(denied.exception.status_code, 403)
            with self.assertRaises(HTTPException) as locked:
                gateway.execute(request, 'Bearer ' + self.token)
            self.assertEqual(locked.exception.detail['code'], 'writes_disabled')
            driver.assert_not_called()

    def test_gateway_invalid_command_rejected_and_errors_redacted(self):
        start = datetime.now(JST) + timedelta(days=1)
        body = {'operation': 'inspect', 'job': {'id': 'b' * 32, 'station': 'TBS', 'title': 'Test', 'starts_at': start.isoformat(), 'ends_at': (start + timedelta(hours=1)).isoformat()}}
        with patch.dict(os.environ, {'RFRIENDS_TOKEN_FILE': str(self.token_file)}), patch.object(gateway, 'run_driver', side_effect=ValueError(self.token)):
            from fastapi import HTTPException
            request = gateway.Operation.model_validate(body)
            with self.assertRaises(HTTPException) as failure:
                gateway.execute(request, 'Bearer ' + self.token)
            self.assertEqual(failure.exception.status_code, 502)
            self.assertNotIn(self.token, str(failure.exception.detail))
            body['operation'] = 'shell'
            with self.assertRaises(ValidationError):
                gateway.Operation.model_validate(body)

    def test_docker_response_demultiplex_and_exit_status(self):
        import struct
        output = b'{"state":"scheduled","job_id":"12"}'
        frame = b'\x01\x00\x00\x00' + struct.pack('>I', len(output)) + output
        responses = [b'{"Id":"exec-test"}', frame, b'{"Running":false,"ExitCode":0}']
        with patch.object(gateway, 'docker_request', side_effect=responses) as transport:
            self.assertEqual(gateway.run_driver({'operation': 'inspect', 'job': {}})['job_id'], '12')
            command = transport.call_args_list[0].args[1]['Cmd']
            self.assertEqual(command[0], 'php')
            self.assertNotIn('require_once(', command[-2])
        with patch.object(gateway, 'docker_request', side_effect=[b'{"Id":"e"}', b'bad']):
            with self.assertRaises(ValueError):
                gateway.run_driver({'operation': 'inspect', 'job': {}})

    def test_app_registers_reservation_api_paths(self):
        import app as application
        paths = {route.path for route in application.app.routes if hasattr(route, "path")}
        for router in application.app.routes:
            original = getattr(router, "original_router", None)
            if original:
                paths.update(route.path for route in original.routes if hasattr(route, "path"))
        self.assertTrue({
            '/api/reservations', '/api/reservations/{reservation_id}',
            '/api/reservations/{reservation_id}/refresh',
            '/api/reservations/{reservation_id}/retry',
            '/api/programs/{program_id}/broadcasts',
        }.issubset(paths))


if __name__ == '__main__':
    unittest.main()
