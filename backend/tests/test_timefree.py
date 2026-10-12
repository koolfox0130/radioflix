"""Only temporary databases, fake schedule and injected offline worker."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from radioflix.api.timefree import timefree_router, TimefreeRequest
from radioflix.schemas.reservations import JST
from radioflix.timefree.service import TimefreeService, eligibility, deadline
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker, FixturePHP, completed_assets, safe_file
import test_schedule


class FakeAudio:
    kind = 'fixture'
    def __init__(self, callback=None): self.callback = callback
    def run(self, row, work):
        if self.callback: self.callback(row)
        p = work / 'output'; p.mkdir(); f = p / 'audio.wav'
        duration = int((datetime.fromisoformat(row['end_at'])-datetime.fromisoformat(row['start_at'])).total_seconds())
        with wave.open(str(f), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(1); w.setframerate(8000); w.writeframes(b'\x80' * duration * 8000)
        return f


class TimefreeTests(unittest.TestCase):
    def setUp(self):
        self.guide = test_schedule.GuideTests(); self.guide.setUp(); self.addCleanup(self.guide.doCleanups)
        self.root = self.guide.path
        self.now = self.guide.res.clock()
        b = self.guide.service.adapter.day((self.now-timedelta(days=1)).date())['broadcasts'][0]
        b['metadata'].update(failed_record='0', ts_in_ng='0', ts_out_ng='0')
        self.item = b
        self.guide.service.adapter.day = lambda *a, **k: {'availability': 'ok', 'broadcasts': [self.item]}
        self.store = TimefreeStore(self.root/'jobs.sqlite3')
        self.service = TimefreeService(self.store, self.guide.service, clock=lambda:self.now, fixture=True)
        self.app = FastAPI(); self.app.include_router(timefree_router(self.service)); self.client = TestClient(self.app)
        self.client.headers.update(self.guide.client.headers)
        self.output = self.root/'published'

    def request(self):
        return {'broadcast_episode_id': self.item['id'], 'schedule_revision': self.item['schedule_revision'],
                'date': self.item['starts_at'][:10]}

    def post(self):return self.client.post('/api/timefree/jobs',json=self.request())

    def worker(self, transport=None):
        return TimefreeWorker(self.store,self.output,transport or FakeAudio(),clock=lambda:self.now)

    def test_register_queued_get_and_metadata(self):
        r=self.post();self.assertEqual(r.status_code,202);row=r.json();self.assertEqual(row['state'],'queued')
        self.assertEqual(row['broadcast'],self.item)
        self.assertEqual(self.client.get('/api/timefree/jobs/'+row['job_id']).json(),row)
        self.assertEqual(self.client.get('/api/timefree/jobs').headers['cache-control'],'no-store')

    def test_future_rejected(self):
        self.item['starts_at']=(self.now+timedelta(hours=1)).isoformat();self.item['ends_at']=(self.now+timedelta(hours=2)).isoformat()
        self.assertEqual(self.post().status_code,409);self.assertEqual(self.store.list(),[])

    def test_expired_rejected(self):
        self.now=deadline(__import__('radioflix.schemas.reservations',fromlist=['Broadcast']).Broadcast.model_validate(self.item))
        self.guide.service.validate_dates=lambda d:None
        self.assertEqual(self.post().status_code,410);self.assertFalse(self.store.path.exists())

    def test_exact_deadline_and_ready_boundaries(self):
        from radioflix.schemas.reservations import Broadcast
        b=Broadcast.model_validate(self.item)
        self.assertEqual(eligibility(self.item,b.ends_at+timedelta(seconds=119)),'not_ready')
        self.assertIsNone(eligibility(self.item,b.ends_at+timedelta(seconds=120)))
        self.assertIsNone(eligibility(self.item,deadline(b)-timedelta(seconds=1)))
        self.assertEqual(eligibility(self.item,deadline(b)),'expired')
        self.assertEqual(deadline(b).hour,5)

    def test_duplicate_concurrent_and_completed(self):
        req=TimefreeRequest(**self.request())
        with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda _:self.service.create(req),range(4)))
        self.assertEqual(len({r['job_id'] for r in rows}),1)
        self.worker().run_once();self.assertEqual(self.post().json()['job_id'],rows[0]['job_id'])
        self.assertEqual(len(self.store.list()),1)

    def test_running_completed_and_asset_contract(self):
        row=self.post().json()
        def observed(r):self.assertEqual(TimefreeStore(self.store.path).get(r['job_id'])['state'],'running')
        self.worker(FakeAudio(observed)).run_once();done=self.store.get(row['job_id'])
        self.assertEqual(done['state'],'completed');self.assertIsNotNone(done['started_at']);self.assertIsNotNone(done['completed_at'])
        self.assertEqual(completed_assets(self.store,self.output),[]) # fixtures never enter production catalogue
        assets=completed_assets(self.store,self.output,include_fixture=True)
        self.assertEqual(assets[0]['broadcast']['title'],self.item['title']);self.assertEqual(assets[0]['asset_id'],row['job_id'])
        safe_file(self.output,done['output_path']).write_bytes(b'broken')
        self.assertEqual(completed_assets(self.store,self.output,include_fixture=True),[])

    def test_failed_sanitized(self):
        def fail(row):raise RuntimeError('private-credential-must-not-leak')
        row=self.post().json();self.worker(FakeAudio(fail)).run_once()
        failed=self.store.get(row['job_id']);self.assertEqual(failed['state'],'failed')
        self.assertNotIn('private-credential',json.dumps(failed));self.assertIsNone(failed['output_path'])

    def test_restart_and_interrupted_no_redownload(self):
        row=self.post().json();self.assertEqual(TimefreeStore(self.store.path).get(row['job_id'])['state'],'queued')
        with self.store.transaction() as db:db.execute("UPDATE timefree_jobs SET state='running'")
        self.worker(FakeAudio(lambda _:self.fail('must not run'))).run_once()
        self.assertEqual(self.store.get(row['job_id'])['state'],'unknown');self.assertEqual(self.post().json()['job_id'],row['job_id'])

    def test_truncated_audio_is_not_published(self):
        class Truncated(FakeAudio):
            def run(self, row, work):
                output = super().run(row, work)
                with output.open('r+b') as audio:
                    audio.truncate(44)
                return output
        row = self.post().json()
        self.worker(Truncated()).run_once()
        self.assertEqual(self.store.get(row['job_id'])['state'], 'failed')
        self.assertFalse((self.output / row['job_id']).exists())

    def test_work_directory_failure_is_recorded(self):
        row = self.post().json()
        with patch('radioflix.timefree.worker.tempfile.mkdtemp', side_effect=OSError('disk full')):
            self.worker().run_once()
        self.assertEqual(self.store.get(row['job_id'])['state'], 'failed')

    def test_timeout_is_unknown_and_never_retried(self):
        def timeout(row):
            raise subprocess.TimeoutExpired('private-command', 60)
        row = self.post().json()
        self.worker(FakeAudio(timeout)).run_once()
        saved = self.store.get(row['job_id'])
        self.assertEqual(saved['state'], 'unknown')
        self.assertNotIn('private-command', json.dumps(saved))
        self.assertIsNone(self.worker(FakeAudio(lambda _: self.fail('retry'))).run_once())

    def test_existing_output_is_unchanged(self):
        row = self.post().json()
        dest = self.output / row['job_id']
        dest.mkdir(parents=True)
        existing = dest / 'audio.wav'
        existing.write_bytes(b'existing recording')
        self.worker().run_once()
        self.assertEqual(existing.read_bytes(), b'existing recording')
        self.assertEqual(self.store.get(row['job_id'])['state'], 'unknown')

    def test_copy_failure_is_unknown_and_not_exposed(self):
        row = self.post().json()
        with patch('radioflix.timefree.worker.shutil.copyfileobj', side_effect=OSError('disk full')):
            self.worker().run_once()
        self.assertEqual(self.store.get(row['job_id'])['state'], 'unknown')
        self.assertEqual(completed_assets(self.store, self.output, include_fixture=True), [])
        self.assertEqual(self.post().json()['job_id'], row['job_id'])

    def test_db_failure_after_publish_never_redownloads(self):
        row = self.post().json()
        original = self.store.event
        def event(db, job_id, state, now):
            if state == 'completed':
                raise OSError('audit unavailable')
            return original(db, job_id, state, now)
        with patch.object(self.store, 'event', side_effect=event):
            self.worker().run_once()
        self.assertTrue((self.output / row['job_id'] / 'audio.wav').is_file())
        self.assertEqual(self.store.get(row['job_id'])['state'], 'unknown')
        self.assertEqual(completed_assets(self.store, self.output, include_fixture=True), [])
        self.assertIsNone(self.worker(FakeAudio(lambda _: self.fail('retry'))).run_once())

    def test_only_one_worker_owns_running_job(self):
        row = self.post().json()
        def concurrent(_):
            self.assertIsNone(self.worker(FakeAudio(lambda _: self.fail('duplicate'))).run_once())
            self.assertEqual(self.store.get(row['job_id'])['state'], 'running')
        self.worker(FakeAudio(concurrent)).run_once()
        self.assertEqual(self.store.get(row['job_id'])['state'], 'completed')

    def test_fixture_never_consumes_live_rows(self):
        row = self.post().json()
        with self.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET execution_kind='live'")
        self.assertIsNone(self.worker(FakeAudio(lambda _: self.fail('live row'))).run_once())
        self.assertEqual(self.store.get(row['job_id'])['state'], 'queued')

    def test_changed_revision_and_overlapping_episode_rejected(self):
        request = self.request()
        request['schedule_revision'] = 'f' * 64
        self.assertEqual(self.client.post('/api/timefree/jobs', json=request).json()['detail']['code'], 'schedule_changed')
        self.assertFalse(self.store.path.exists())
        self.post()
        self.item['id'] = 'e' * 64
        self.assertEqual(self.post().json()['detail']['code'], 'conflict')
        self.assertEqual(len(self.store.list()), 1)

    def test_reading_jobs_never_creates_database(self):
        self.assertEqual(self.client.get('/api/timefree/jobs').json(), [])
        self.assertEqual(self.client.get('/api/timefree/jobs/missing').status_code, 404)
        self.assertFalse(self.store.path.exists())

    def test_gate_enable_still_cannot_create_production_job(self):
        self.service.fixture = False
        with patch('radioflix.timefree.service.live_gate', return_value=True):
            self.assertEqual(self.post().json()['detail']['code'], 'worker_unavailable')
        self.assertFalse(self.store.path.exists())

    def test_cancel_queued(self):
        row=self.post().json();self.assertEqual(self.client.delete('/api/timefree/jobs/'+row['job_id']).json()['state'],'cancelled')
        self.assertIsNone(self.worker().run_once())

    def test_worker_rechecks_expiry(self):
        row=self.post().json();self.now+=timedelta(days=8);self.worker(FakeAudio(lambda _:self.fail('expired'))).run_once()
        self.assertEqual(self.store.get(row['job_id'])['state'],'expired')

    def test_no_token_rejected_even_gates_off(self):
        self.client.headers.pop('Authorization');self.service.fixture=False
        with patch.dict(os.environ,{'RADIOFLIX_WRITE_TOKEN_FILE':''}):self.assertEqual(self.post().status_code,403)
        self.assertFalse(self.store.path.exists())

    def test_disabled_gate_never_queues_or_starts_live(self):
        self.service.fixture=False
        with patch.dict(os.environ,{'RFRIENDS_ENABLE_WRITES':'0','RADIOFLIX_TIMEFREE_ENABLE_WRITES':'0'}):
            self.assertEqual(self.post().json()['detail']['code'],'writes_disabled')
            class Live(FakeAudio):kind='live'
            self.assertIsNone(self.worker(Live(lambda _:self.fail('live'))).run_once())
        self.assertFalse(self.store.path.exists())

    def test_request_injection_rejected(self):
        for extra in [{'command':'sh evil'},{'output_path':'../../native'},{'station':'TBS;touch bad'},{'execution_kind':'live'}]:
            self.assertEqual(self.client.post('/api/timefree/jobs',json={**self.request(),**extra}).status_code,422)
        self.assertFalse(self.store.path.exists())

    def test_title_not_used_as_path(self):
        self.item['title']='../../native; $(touch bad) `x`'
        row=self.post().json();self.worker().run_once()
        self.assertEqual(self.store.get(row['job_id'])['output_path'],row['job_id']+'/audio.wav')
        self.assertEqual(list((self.root/'native').iterdir()),[])

    def test_path_traversal_and_symlink_refused(self):
        self.output.mkdir();outside=self.root/'outside';outside.mkdir()
        (self.output/('a'*32)).symlink_to(outside,target_is_directory=True)
        for path in ['../outside','/tmp/evil','a'*32+'/audio.wav']:
            with self.assertRaises((ValueError,OSError)):safe_file(self.output,path)

    def test_native_unchanged_conflict_and_unknown(self):
        p=self.guide.native_dir/'native.dat'
        p.write_text('20300107120000 20300107130000 3600 0 0 0 JORF native')
        before=hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(self.post().json()['detail']['code'],'native_conflict')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),before)
        self.assertFalse(self.store.path.exists())
        p.write_text('malformed');self.assertEqual(self.post().json()['detail']['code'],'native_unknown')

    def test_restrictions_fail_closed(self):
        for value in [None,'1','2']:
            self.item['metadata']['ts_in_ng']=value
            self.assertEqual(self.post().json()['detail']['code'],'restricted')

    def test_projection_states(self):
        for state,label in [('queued','録音待ち'),('running','録音中…'),('completed','録音済み'),('failed','録音失敗'),('expired','期限切れ')]:
            result=self.service.project(self.item,[{'job_id':'x','broadcast_episode_id':self.item['id'],'state':state}])
            self.assertEqual(result['timefree_label'],label);self.assertFalse(result['timefree_enabled'])


PHP_COMMAND=json.loads(os.getenv('RADIOFLIX_TIMEFREE_TEST_PHP','null'))
SOURCE=os.getenv('RADIOFLIX_TIMEFREE_TEST_SOURCE','')
@unittest.skipUnless(PHP_COMMAND and SOURCE,'isolated PHP/source not configured')
class PHPTimefreeTests(unittest.TestCase):
    def test_real_downloader_with_offline_boundaries(self):
        for scenario in ['success','auth_failed','hls_failed','download_failed','short','publish_failed']:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(prefix='rf-timefree-',dir='/tmp/radioflix-timefree-tests') as tmp:
                now=datetime.now(JST);start=now-timedelta(hours=2);end=start+timedelta(minutes=1)
                b={'id':'a'*64,'station':'TBS','region':'JP13','title':'../../unsafe; $(x)',
                   'starts_at':start.isoformat(),'ends_at':end.isoformat(),
                   'metadata':{'failed_record':'0','ts_in_ng':'0','ts_out_ng':'0'}}
                runner=FixturePHP(PHP_COMMAND,SOURCE,scenario)
                row={'job_id':'b'*32,'broadcast':b}
                if scenario=='success':
                    path=runner.run(row,Path(tmp));self.assertTrue(path.is_file())
                    with wave.open(str(path),'rb') as f:self.assertEqual(f.getnframes()/f.getframerate(),60)
                else:
                    with self.assertRaises(ValueError):runner.run(row,Path(tmp))
