"""Acceptance-only limits using real local ffmpeg and socket-forbidden HTTP fixtures."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from radioflix.timefree.acceptance import main
from radioflix.timefree.acceptance_profile import (budget, AcceptanceTransport, AcceptanceCapture,
    MAX_WIRE_REQUESTS, MAX_SEGMENTS, AcceptanceMedia)
from radioflix.timefree.capture.argv import _adts_duration, _validate_wav
from radioflix.timefree.capture.limits import NORMAL, ACCEPTANCE, checked
from radioflix.timefree.capture.source.models import HttpRequest, HttpResponse
from radioflix.timefree.capture.source.errors import SourceNotReady
from radioflix.timefree.capture.source.transport import ProductionHttpTransport
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.worker import TimefreeWorker
from radioflix.api.timefree import TimefreeRequest
import test_timefree


class ProfileTests(unittest.TestCase):
    def test_duration_boundaries(self):
        for duration in (60, 300):
            self.assertEqual(budget(duration)['duration'], duration)
        for duration in (0, 301, 302, 600, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError): budget(duration)
        self.assertEqual(ACCEPTANCE.audio_seconds, 302)
        self.assertEqual((NORMAL.metadata_seconds, NORMAL.audio_seconds), (60, 60))
        with self.assertRaises(ValueError): checked(type(NORMAL)(300, 999999, 999999999))

    def test_wire_exact_hard_boundary_and_no_runtime_override(self):
        for transport, limit in ((ProductionHttpTransport(observation_mode=True,max_wire_requests=8),8),
                                 (AcceptanceTransport(300),MAX_WIRE_REQUESTS)):
            with patch.object(transport,'_public_addresses',return_value=('8.8.8.8',)), patch.object(
                    transport,'_open_once',return_value=HttpResponse(200,body=b'ok')) as opened:
                for _ in range(limit): transport.request(HttpRequest('GET','https://radiko.jp/fixture'))
                with self.assertRaises(SourceNotReady): transport.request(HttpRequest('GET','https://radiko.jp/fixture'))
                self.assertEqual(opened.call_count,limit)
        with self.assertRaises(ValueError): ProductionHttpTransport(observation_mode=True,max_wire_requests=9)

    def test_retry_and_redirect_share_remaining_budget(self):
        for response in (HttpResponse(503),HttpResponse(302,headers={'Location':'https://radiko.jp/fixture'})):
            t=AcceptanceTransport(300); t.wire_requests=MAX_WIRE_REQUESTS-1
            with patch.object(t,'_public_addresses',return_value=('8.8.8.8',)), patch.object(t,'_open_once',return_value=response) as opened:
                with self.assertRaises(SourceNotReady): t.request(HttpRequest('GET','https://radiko.jp/fixture'))
                self.assertEqual(opened.call_count,1);self.assertEqual(t.wire_requests,MAX_WIRE_REQUESTS)

    def test_manifest_tightens_budget_and_segment_bound(self):
        t=AcceptanceTransport(300)
        t.manifest_budget(61);self.assertEqual(t._wire_limit(),72)
        t.manifest_budget(62);self.assertEqual(t._wire_limit(),72) # cannot enlarge again
        for count in (0,63,10000,True):
            with self.assertRaises(ValueError): t.manifest_budget(count)
        self.assertEqual(budget(60)['max_wire_requests'],25)

    def test_audio_duration_boundary_is_independent_of_metadata(self):
        # Structurally complete ADTS frames: no codec/network calls needed to test duration parser.
        # 8192 Hz is not supported; use 8000 Hz: 2359 frames=301.952s, 2360=302.08s.
        frame=bytes([0xff,0xf1,0x6c,0x80,0,0xff,0xfc]) # 7-byte frame, 8000 Hz
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'segment-001.bin'
            p.write_bytes(frame*2359)
            self.assertLessEqual(_adts_duration(p,_profile=ACCEPTANCE)[1],302)
            with self.assertRaises(ValueError): _adts_duration(p)
            p.write_bytes(frame*2360)
            with self.assertRaises(ValueError): _adts_duration(p,_profile=ACCEPTANCE)


class FiveMinuteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='rf-accept-aac-')
        cls.addClassCleanup(cls.temp.cleanup)
        path=Path(cls.temp.name)/'source.aac'
        subprocess.run(['/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','error','-f','lavfi',
            '-i','anullsrc=r=48000:cl=stereo','-t','300','-c:a','aac','-b:a','48k','-f','adts','-n',str(path)],
            check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        data=path.read_bytes();frames=[];i=0
        while i<len(data):
            n=((data[i+3]&3)<<11)|(data[i+4]<<3)|(data[i+5]>>5)
            frames.append(data[i:i+n]);i+=n
        cls.segments=[b''.join(frames[len(frames)*j//61:len(frames)*(j+1)//61]) for j in range(61)]

    def setUp(self):
        self.f=test_timefree.TimefreeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.output.mkdir(); normal=self.f.root/'normal';normal.mkdir()
        self.guard=Preflight(self.f.store,self.f.guide.native_dir,[normal],self.f.output)
        self.rows=[]
        start=datetime.fromisoformat(self.f.item['starts_at'])
        for offset in (0,10):
            a=start+timedelta(minutes=offset); b=a+timedelta(seconds=300)
            self.f.item.update(starts_at=a.isoformat(),ends_at=b.isoformat(),id=hashlib.sha256(
                f"{self.f.item['station']}:{a.isoformat()}:{b.isoformat()}".encode()).hexdigest())
            self.rows.append(self.f.service.create(TimefreeRequest(**self.f.request())))
        with self.f.store.transaction() as db: db.execute("UPDATE timefree_jobs SET execution_kind='live'")
        self.approval=self.f.root/'approval.json'
        self.approval.write_text(json.dumps({'job_id':self.rows[0]['job_id'],'approved':True,
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}));self.approval.chmod(0o600)
        env=patch.dict(os.environ,{'RADIOFLIX_DB_PATH':str(self.f.store.path),
            'RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE':str(self.approval),'RFRIENDS_ENABLE_WRITES':'0',
            'RADIOFLIX_TIMEFREE_ENABLE_WRITES':'1','RADIOFLIX_TIMEFREE_BOOT_MODE':'enabled'})
        env.start();self.addCleanup(env.stop)

    def stack(self,count=61):
        self.http=AcceptanceTransport(300)
        self.adapter=AcceptanceCapture(duration=300,store=self.f.store,managed_root=self.f.output,
            preflight=self.guard,transport=self.http,bridge_approved=True,clock=lambda:self.f.now,
            executable=Path('/usr/bin/ffmpeg').resolve(),preflight_allowlisted_path=Path('/usr/bin/ffmpeg').resolve())
        self.adapter.refresh_readiness()
        self.assertTrue(self.adapter.ready)
        self.worker=TimefreeWorker(self.f.store,self.f.output,self.adapter,preflight=self.guard,clock=lambda:self.f.now)
        station=self.rows[0]['station']
        manifest=('#EXTM3U\n'+''.join(f'#EXTINF:{300/count},\ns{j}.aac\n' for j in range(count))+'#EXT-X-ENDLIST\n').encode()
        self.responses=[HttpResponse(200,body=b'RadikoJSPlayer(x,"pc_html5","0123456789abcdef0123456789abcdef01234567",{})'),
            HttpResponse(200,headers={'X-Radiko-AuthToken':'FIXTURE','X-Radiko-KeyOffset':'0','X-Radiko-KeyLength':'16'}),
            HttpResponse(200,body=b'JP13,fixture'),
            HttpResponse(200,body=f'<region><station><id>{station}</id><area_id>JP13</area_id></station></region>'.encode()),
            HttpResponse(200,body=b'<urls><url areafree="0" timefree="1"><playlist_create_url>https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/fixture/index.m3u8</playlist_create_url></url></urls>'),
            HttpResponse(200,body=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=48000\nmedia.m3u8\n'),
            HttpResponse(200,body=manifest)]+[HttpResponse(200,body=x) for x in self.segments]

    def execute(self):
        with patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')), patch(
                'socket.create_connection',side_effect=AssertionError('network forbidden')), patch.object(
                self.http,'_public_addresses',return_value=('8.8.8.8',)), patch.object(self.http,'_open_once',side_effect=self.responses):
            return main(['--accept-job',self.rows[0]['job_id']],worker_factory=lambda **kw:self.worker)

    def test_five_minute_real_transcode_and_target_only_process(self):
        self.stack(); before=self.f.store.get(self.rows[1]['job_id'])
        proc=multiprocessing.get_context('fork').Process(target=_run_child,args=(self,))
        proc.start();proc.join(40)
        if proc.is_alive():proc.terminate();proc.join(3)
        self.assertEqual(proc.exitcode,0)
        row=self.f.store.get(self.rows[0]['job_id']);self.assertEqual(row['state'],'completed')
        self.assertLessEqual(abs(row['duration']-300),2)
        self.assertGreater(row['output_size'],32*1024*1024)
        self.assertEqual(self.f.store.get(self.rows[1]['job_id']),before)
        self.assertEqual(len(list(self.f.output.glob('*/audio.wav'))),1)
        self.assertIsNotNone(self.f.store.publication(row['job_id']))
        self.assertFalse(self.approval.exists())
        self.worker.reconcile();self.assertEqual(self.f.store.get(row['job_id'])['state'],'completed')

    def test_abnormal_playlist_rejected_before_first_segment(self):
        self.stack(63)
        self.assertEqual(self.execute(),1)
        self.assertEqual(self.http.wire_requests,7)
        self.assertEqual(self.f.store.get(self.rows[0]['job_id'])['state'],'failed')
        self.assertEqual(self.f.store.get(self.rows[1]['job_id'])['state'],'queued')
        self.assertFalse(list(self.f.output.glob('*/audio.wav')))

    def test_exact_segment_max_accepted_by_gate(self):
        self.stack(62)
        self.adapter.media_fetcher.check_segments(tuple(range(62)))
        with self.assertRaises(ValueError):self.adapter.media_fetcher.check_segments(tuple(range(63)))

    def test_capture_failure_cleanup(self):
        self.stack();self.responses[7]=HttpResponse(403)
        self.assertEqual(self.execute(),1)
        self.assertEqual(self.f.store.get(self.rows[0]['job_id'])['state'],'failed')
        self.assertFalse(list(self.f.output.glob('*/audio.wav')))
        self.assertFalse(list((self.f.output/'.staging'/'capture-work').iterdir()))


def _run_child(case):
    try: code=case.execute()
    finally:case.approval.unlink(missing_ok=True)
    raise SystemExit(code)
