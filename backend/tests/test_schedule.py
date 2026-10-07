"""Phase 1–3 isolated fixtures. Network and gateway are always fake."""
import gzip
import hashlib
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import FastAPI
from fastapi.testclient import TestClient
from radioflix.adapters.schedule import ScheduleAdapter
from radioflix.api.schedule import schedule_router
from radioflix.database.reservations import ReservationStore
from radioflix.schemas.reservations import Broadcast, JST, RecordingError
from radioflix.services.program_service import ProgramService
from radioflix.services.reservation_service import ReservationService
from radioflix.services.schedule_service import NativeReservations, ProgramCatalog, ScheduleService
from test_reservations import FakeAdapter

NOW = datetime(2030, 1, 8, 12, tzinfo=JST)
STATIONS = b'<stations><station><id>JORF</id><name>Radio Japan</name></station><station><id>TBS</id><name>TBS Radio</name></station></stations>'
def xml(day='20300109', title='New show'):
    return f'<radiko><stations><station id="JORF"><name>Radio Japan</name><progs><prog id="provider" ft="{day}120000" to="{day}130000"><title>{title}</title><pfm>Guest</pfm><desc>description</desc><ts_in_ng>0</ts_in_ng></prog></progs></station></stations></radiko>'.encode()


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.schedule = ScheduleAdapter(area='JP13')
        self.requests = []
        self.failed = set()
        self.compressed = False
        def open_url(url, timeout):
            self.requests.append(url)
            if 'station/list' in url:
                return io.BytesIO(STATIONS)
            day = url.split('/')[-2]
            if day in self.failed:
                raise HTTPError(url, 404, '', {}, None)
            body = xml(day)
            return io.BytesIO(gzip.compress(body) if self.compressed else body)
        self.opener = patch('radioflix.adapters.schedule.urlopen', side_effect=open_url).start()
        self.addCleanup(patch.stopall)
        self.broadcast = Broadcast(id='fake', station='JORF', title='New show', starts_at=NOW+timedelta(days=1), ends_at=NOW+timedelta(days=1,hours=1))
        self.gateway = FakeAdapter(self.broadcast)
        self.store = ReservationStore(self.path/'db.sqlite')
        self.catalog = ProgramCatalog(self.store, ProgramService(self.path/'recordings'))
        self.res = ReservationService(self.store, self.gateway, lambda: NOW, self.catalog, writes_enabled=False)
        self.native_dir = self.path/'native'
        self.native_dir.mkdir()
        self.service = ScheduleService(self.schedule, self.res, self.catalog, NativeReservations(self.native_dir))
        app = FastAPI(); app.include_router(schedule_router(self.service))
        self.client = TestClient(app)
        token = self.path/'test-token'
        token.write_text('fixture-credential-' * 3)
        patch.dict(os.environ, {'RADIOFLIX_WRITE_TOKEN_FILE':str(token), 'RADIOFLIX_WRITE_ORIGIN':'http://testserver'}).start()
        self.client.headers['Authorization'] = 'Bearer ' + 'fixture-credential-' * 3

    def get(self, day='2030-01-09', station='JORF'):
        return self.client.get('/api/schedule', params={'date': day, 'station': station})

    def item(self):
        return self.get().json()['days'][0]['broadcasts'][0]

    def post(self, mode='once', item=None):
        item = item or self.item()
        return self.client.post('/api/broadcasts/'+item['id']+'/reservations', json={
            'date': '2030-01-09', 'mode': mode, 'schedule_revision': item['schedule_revision']})

    def test_authentication_required(self):
        self.client.headers.pop('Authorization')
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(self.store.path.exists())

    def test_cross_origin_rejected(self):
        self.client.headers['Origin'] = 'http://untrusted.invalid'
        self.assertEqual(self.post().status_code, 403)
        self.assertFalse(self.store.path.exists())

    def test_station_list(self):
        r = self.client.get('/api/stations'); self.assertEqual(r.status_code, 200)
        self.assertEqual([s['id'] for s in r.json()['stations']], ['JORF', 'TBS'])
        self.assertEqual(r.headers['cache-control'], 'no-store')

    def test_specified_day_and_metadata(self):
        b = self.item(); self.assertEqual(b['performer'], 'Guest')
        self.assertEqual(b['provider_program_id'], 'provider'); self.assertEqual(b['station_name'], 'Radio Japan')
        self.assertEqual(b['starts_at'], '2030-01-09T12:00:00+09:00')

    def test_past_seven(self): self.assertEqual(self.get('2030-01-01').status_code, 200)
    def test_future_seven(self): self.assertEqual(self.get('2030-01-15').status_code, 200)
    def test_outside_range(self):
        for date in ['2029-12-31', '2030-01-16']:
            self.assertEqual(self.get(date).status_code, 422)
    def test_invalid_date(self): self.assertEqual(self.get('bad').status_code, 422)
    def test_invalid_station(self): self.assertEqual(self.get(station='../bad').status_code, 422)
    def test_plain_xml(self): self.assertEqual(self.get().json()['availability'], 'ok')
    def test_gzip_xml(self):
        self.compressed = True; self.assertEqual(self.item()['title'], 'New show')
    def test_partial_success(self):
        self.failed.add('20300109')
        data = self.client.get('/api/schedule?date=2030-01-09&date=2030-01-10').json()
        self.assertEqual(data['availability'], 'partial'); self.assertEqual(data['days'][0]['availability'], 'not_available')
        self.assertTrue(data['days'][1]['broadcasts'])
    def test_all_failed(self):
        self.failed.update(['20300109', '20300110'])
        data = self.client.get('/api/schedule?date=2030-01-09&date=2030-01-10').json()
        self.assertEqual(data['availability'], 'unavailable')
    def test_missing_station(self): self.assertEqual(self.get(station='TBS').json()['days'][0]['availability'], 'station_missing')
    def test_stable_id_revision_changes(self):
        a = self.item()
        with patch.object(self.schedule, '_xml', return_value=self.schedule._parse_xml(xml(title='Changed title'))):
            b = self.schedule.day(datetime(2030,1,9).date(), fresh=True)['broadcasts'][0]
        self.assertEqual(a['id'], b['id']); self.assertNotEqual(a['schedule_revision'], b['schedule_revision'])
    def test_retry(self):
        with patch('radioflix.adapters.schedule.urlopen', side_effect=[OSError(), io.BytesIO(STATIONS)]) as fetch:
            self.assertEqual(len(self.schedule.stations()), 2); self.assertEqual(fetch.call_count, 2)
    def test_all_retries_fail(self):
        self.schedule.stations()
        with patch('radioflix.adapters.schedule.urlopen', side_effect=OSError()) as fetch:
            self.assertEqual(self.get().json()['availability'], 'unavailable'); self.assertEqual(fetch.call_count, 2)
    def test_hostile_xml(self):
        self.schedule.stations()
        with patch('radioflix.adapters.schedule.urlopen', side_effect=lambda *a, **k: io.BytesIO(b'<!DOCTYPE x><x/>')):
            self.assertEqual(self.get().json()['availability'], 'unavailable')
    def test_radio_day_before_five(self):
        self.res.clock = lambda: datetime(2030,1,9,4,59,tzinfo=JST)
        self.service.clock = self.res.clock
        self.assertEqual(self.get().json()['today'], '2030-01-08')
    def test_cache_and_post_refetch(self):
        self.item(); before = len(self.requests); self.item(); self.assertEqual(len(self.requests), before)
        self.post(); self.assertGreater(len(self.requests), before)
    def test_get_has_no_writes(self):
        self.item(); self.assertFalse(self.store.path.exists()); self.assertEqual(self.gateway.creates, [])
    def test_once_new_show_without_recordings(self):
        row = self.post().json(); self.assertEqual(row['state'], 'waiting_write')
        self.assertTrue(row['program_id'].startswith('series-')); self.assertFalse((self.path/'recordings').exists())
        self.assertIsNotNone(self.catalog.find_program(row['program_id'])); self.assertEqual(self.gateway.creates, [])
    def test_weekly_new_show(self):
        row = self.post('weekly').json(); self.assertEqual(row['schedule_state'], 'waiting_write')
        self.assertIsNotNone(self.catalog.find_program(row['program_id']))
    def test_once_duplicate(self):
        a=self.post().json(); b=self.post().json(); self.assertEqual(a['id'], b['id']); self.assertEqual(len(self.res.list()), 1)
    def test_weekly_duplicate(self):
        a=self.post('weekly').json(); b=self.post('weekly').json(); self.assertEqual(a['id'], b['id']); self.assertEqual(len(self.res.list_subscriptions()), 1)
    def test_cross_entry_duplicate(self):
        item=self.item(); b=Broadcast.model_validate(item)
        old=self.res.create({'id':'legacy', 'title':b.title}, b, 'once')
        self.assertEqual(self.post().json()['id'], old['id'])
    def test_cross_entry_weekly_duplicate(self):
        b=Broadcast.model_validate(self.item()); old=self.res.create({'id':'legacy','title':b.title}, b, 'weekly')
        self.assertEqual(self.post('weekly').json()['id'], old['id'])
    def test_mode_conflict(self):
        self.post(); self.assertEqual(self.post('weekly').status_code, 409)
    def test_weekly_then_once_conflict(self):
        self.post('weekly'); self.assertEqual(self.post().status_code, 409)
    def test_native_conflict_untouched(self):
        path=self.native_dir/'foreign.dat'; content='20300109120000 20300109130000 3600 0 0 0 JORF native'
        path.write_text(content)
        self.assertEqual(self.item()['reservation_state'], 'native_conflict')
        self.assertEqual(self.post().status_code, 409); self.assertEqual(path.read_text(), content)
        self.assertEqual(self.gateway.creates, []); self.assertEqual(self.gateway.cancels, [])

    def native_dat(self, name, station, start='20300109120000', end='20300109130000'):
        path = self.native_dir / (name + '.dat')
        path.write_text(f'{start} {end} 3600 0 0 0 {station} native')
        return path

    def test_native_r1_is_tokyo_joak_and_files_untouched(self):
        self.native_dat('nhk', 'r1')
        (self.native_dir / 'nhk.sh').write_text('# fixture script; never execute\n')
        def fingerprints():
            return {p.name: (p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_mode,
                            hashlib.sha256(p.read_bytes()).hexdigest()) for p in self.native_dir.iterdir()}
        before = fingerprints()
        rows = self.service.native.snapshot({'JOAK'})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].raw_station, rows[0].station, rows[0].station_state), ('r1', 'JOAK', 'known'))
        self.item()
        self.assertEqual(fingerprints(), before)

    def test_native_documented_radiru_aliases(self):
        aliases = {'r1': 'JOAK', 'r1_sendai': 'JOHK', 'r1_nagoya': 'JOCK',
                   'r1_osaka': 'JOBK', 'r1_sapporo': 'JOIK', 'r1_hiroshima': 'JOFK',
                   'r1_matsuyama': 'JOZK', 'r1_fukuoka': 'JOLK',
                   'r2': 'JOAB', 'r3': 'JOAK-FM', 'r3_osaka': 'JOBK-FM'}
        for alias in aliases:
            self.native_dat(alias, alias)
        self.assertEqual({r.raw_station: r.station for r in self.service.native.snapshot(set())}, aliases)

    def test_native_uppercase_stations_preserved(self):
        for station in ['JORF', 'TBS', 'JOAK-FM']:
            self.native_dat(station, station)
        self.assertEqual({r.station for r in self.service.native.snapshot({'JORF', 'TBS', 'JOAK-FM'})},
                         {'JORF', 'TBS', 'JOAK-FM'})

    def test_native_unknown_station_retained_with_times_and_warning(self):
        self.native_dat('known', 'r1')
        self.native_dat('unknown', 'future-id')
        with self.assertLogs('radioflix.services.schedule_service', level='WARNING') as logs:
            rows = self.service.native.snapshot({'JOAK'})
        self.assertEqual(len(rows), 2)
        row = next(r for r in rows if r.id == 'unknown')
        self.assertIsNone(row.station)
        self.assertEqual(row.station_state, 'unknown')
        self.assertEqual(row.starts_at, datetime(2030, 1, 9, 12, tzinfo=JST))
        self.assertEqual(row.ends_at, datetime(2030, 1, 9, 13, tzinfo=JST))
        self.assertIn('count=1', logs.output[0])
        self.assertNotIn('future-id', logs.output[0])

    def test_native_unknown_overlap_blocks_before_any_write(self):
        for station in ['future-id', 'UNKNOWN_ID', 'r1_unknown', 'r1_']:
            with self.subTest(station=station):
                self.native_dat('unknown', station)
                item = self.item()
                self.assertEqual(item['native_state'], 'unknown')
                self.assertEqual(item['reservation_state'], 'native_unknown')
                self.assertEqual(item['allowed_actions'], [])
                for enabled in [False, True]:  # Fake service only; never sets the process environment.
                    self.res.writes_enabled = enabled
                    response = self.post(item=item)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json()['detail']['code'], 'native_unknown')
                self.assertFalse(self.store.path.exists())
                self.assertFalse(self.gateway.creates)
                self.assertFalse(self.gateway.cancels)

    def test_native_unknown_nonoverlap_does_not_hide_known_reservations(self):
        self.native_dat('unknown', 'future-id', '20300109140000', '20300109150000')
        self.native_dat('known', 'JORF')
        item = self.item()
        self.assertEqual(item['native_state'], 'partial')
        self.assertEqual(item['reservation_state'], 'native_conflict')
        self.assertEqual(item['allowed_actions'], [])
        self.assertEqual(self.post().json()['detail']['code'], 'conflict')

    def test_native_unknown_nonoverlap_allows_safe_time_only(self):
        self.native_dat('unknown', 'future-id', '20300109140000', '20300109150000')
        item = self.item()
        self.assertEqual(item['native_state'], 'partial')
        self.assertEqual(item['reservation_state'], 'unreserved')
        self.assertEqual(self.post().json()['state'], 'waiting_write')
        self.assertFalse(self.gateway.creates)

    def test_native_unknown_boundary_is_half_open(self):
        self.native_dat('unknown', 'future-id', '20300109130000', '20300109140000')
        self.assertEqual(self.item()['native_state'], 'partial')
        self.assertEqual(self.post().json()['state'], 'waiting_write')

    def test_native_r1_blocks_canonical_joak_reservation(self):
        self.native_dat('nhk', 'r1')
        item = {**self.item(), 'station': 'JOAK'}
        with patch.object(self.schedule, 'stations', return_value=[{'id': 'JOAK', 'name': 'NHK'}]), \
             patch.object(self.schedule, 'day', return_value={'availability': 'ok', 'broadcasts': [item]}):
            status = self.service.status(item, [], [], self.service.native.snapshot({'JOAK'}))
            self.assertEqual(status['native_state'], 'checked')
            self.assertEqual(status['reservation_state'], 'native_conflict')
            self.assertEqual(self.post(item=item).json()['detail']['code'], 'conflict')
        self.assertFalse(self.store.path.exists())
        self.assertFalse(self.gateway.creates)

    def test_native_unknown_owned_name_is_not_discarded(self):
        self.native_dat('owned', 'future-id')
        rows = [{'jobs': [{'external_ref': {'name': 'owned'}, 'state': 'scheduled'}]}]
        self.assertEqual(len(self.service.native_snapshot(rows, {'JORF'})), 1)

    def test_native_invalid_time_still_fails_closed(self):
        self.native_dat('unknown', 'future-id', 'invalid')
        self.assertIsNone(self.service.native.snapshot({'JORF'}))
        self.res.writes_enabled = True
        self.assertEqual(self.post().json()['detail']['code'], 'native_unknown')
        self.assertFalse(self.gateway.creates)
    def test_waiting_state_not_reserved(self):
        self.post(); b=self.item(); self.assertEqual(b['reservation_state'], 'waiting_write'); self.assertNotIn('予約済み', b['reservation_label'])
    def test_once_state_fake_gateway(self):
        self.res.writes_enabled=True; self.post(); self.assertEqual(self.item()['reservation_label'], '今回のみ予約済み')
    def test_weekly_state_fake_gateway(self):
        self.res.writes_enabled=True; self.post('weekly'); self.assertEqual(self.item()['reservation_label'], '毎週録音中')
    def test_gateway_conflict_preserved(self):
        self.res.writes_enabled=True; self.gateway.create_error=RecordingError('conflict','既存予約は変更していません')
        self.assertEqual(self.post().json()['state'], 'create_failed'); self.assertEqual(self.gateway.cancels, [])
        self.assertIn('既存予約', self.item()['reservation_label'])
    def test_unknown_native_stops_enabled_create(self):
        self.res.writes_enabled=True; self.service.native=NativeReservations()
        self.assertEqual(self.post().status_code,409); self.assertFalse(self.gateway.creates)
    def test_revision_rejected(self):
        b=self.item(); b['schedule_revision']='0'*64
        self.assertEqual(self.post(item=b).status_code,409); self.assertFalse(self.store.path.exists())
    def test_past_cannot_reserve(self):
        b=self.get('2030-01-07').json()['days'][0]['broadcasts'][0]
        r=self.client.post('/api/broadcasts/'+b['id']+'/reservations',json={'date':'2030-01-07','schedule_revision':b['schedule_revision'],'mode':'once'})
        self.assertEqual(r.status_code,409); self.assertFalse(self.gateway.creates)
        self.assertEqual(b['timefree_message'],'タイムフリー録音は準備中'); self.assertEqual(b['allowed_actions'],[])
    def test_concurrent_once(self):
        b=Broadcast.model_validate(self.item()); p=self.catalog.resolve(b)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(lambda _: self.res.create(p,b,'once'), range(4)))
        self.assertEqual(len({r['id'] for r in rows}),1)
    def test_weekly_resolver_after_restart(self):
        row=self.post('weekly').json()
        restored=ProgramCatalog(self.store, ProgramService(self.path/'recordings'))
        self.assertEqual(restored.find_program(row['program_id'])['title'], 'New show')
    def test_legacy_alias_survives_folder_removal(self):
        folder = self.path/'recordings'/'JORF_New show'
        folder.mkdir(parents=True)
        legacy = self.catalog.programs.get_all_programs()[0]
        row = self.post('weekly').json()
        self.assertEqual(row['program_id'], legacy['id'])
        folder.rmdir()
        self.assertEqual(self.catalog.find_program(legacy['id'])['title'], 'New show')

    def test_new_show_weekly_advances_without_folder(self):
        row = self.post('weekly').json()
        current = self.res.list()[0]
        job = current['jobs'][0]
        self.gateway.remote[job['id']] = 'elapsed'
        b = Broadcast.model_validate(current['broadcast'])
        self.gateway.candidates = [b.model_copy(update={
            'id': 'next-week', 'starts_at': b.starts_at + timedelta(days=7),
            'ends_at': b.ends_at + timedelta(days=7)})]
        self.res.clock = lambda: NOW + timedelta(days=7)
        self.res.reconcile()
        sub = self.res.list_subscriptions()[0]
        self.assertEqual(sub['id'], row['id'])
        self.assertEqual(sub['last_matched_broadcast']['id'], 'next-week')
        self.assertEqual(sub['schedule_state'], 'waiting_write')
        self.assertFalse(self.gateway.creates)

    def test_revision_snapshot_is_persistent(self):
        b = self.item(); self.post(item=b)
        with self.store.locked() as db:
            row = db.execute('SELECT snapshot FROM broadcast_revisions WHERE id=?', (b['id'],)).fetchone()
        self.assertEqual(json.loads(row['snapshot'])['schedule_revision'], b['schedule_revision'])

    def test_schedule_changed_overlap(self):
        self.post(); b=Broadcast.model_validate(self.item()).model_copy(update={'id':'different','ends_at':NOW+timedelta(days=1,hours=2)})
        with self.assertRaises(RecordingError): self.res.create({'id':'other','title':b.title},b,'once')

if __name__ == '__main__': unittest.main()
