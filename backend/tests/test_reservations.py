"""Offline API/state-machine tests. No real gateway, network or recorder calls."""
import io
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

    def broadcasts(self, program):
        return [self.broadcast]

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


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2030, 1, 1, 12, tzinfo=JST)
        self.broadcast = Broadcast(id="broadcast-1", station="TBS", title="テスト番組",
                                   starts_at=self.now + timedelta(hours=12), ends_at=self.now + timedelta(hours=14))
        self.adapter = FakeAdapter(self.broadcast)
        self.store = ReservationStore(Path(self.temp.name) / "db.sqlite3")
        self.service = ReservationService(self.store, self.adapter, lambda: self.now)
        self.program = {"id": "program-1", "title": "テスト番組"}

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
        self.assertEqual(self.service.cancel(row["id"])["state"], "cancel_unknown")
        self.now += timedelta(days=8)
        self.service.reconcile()
        self.assertEqual(len(self.adapter.creates), 1)
        self.adapter.cancel_error = None
        self.service.reconcile()
        self.assertEqual(self.service.list()[0]["state"], "cancelled")

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
        self.adapter.remote[row["jobs"][0]["id"]] = "elapsed"
        self.now += timedelta(days=15)
        restarted = ReservationService(self.store, self.adapter, lambda: self.now)
        restarted.reconcile()
        result = restarted.list()[0]
        latest = result["jobs"][-1]
        expected = self.broadcast.starts_at + timedelta(days=21)
        self.assertEqual(datetime.fromisoformat(latest["payload"]["starts_at"]), expected)
        self.assertEqual(len(self.adapter.creates), 2)
        restarted.reconcile()
        self.assertEqual(len(self.adapter.creates), 2)
        restarted.cancel(row["id"])
        self.assertEqual([job["id"] for job in self.adapter.cancels], [latest["id"]])

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
