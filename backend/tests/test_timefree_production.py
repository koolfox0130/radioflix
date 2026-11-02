"""Production composition with scripted HTTP and locally synthesized ADTS only."""
import hashlib
import os
import sqlite3
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from radioflix.timefree.runtime_policy import require_runtime_capture
from radioflix.timefree.capture.errors import CaptureNotReady
from radioflix.timefree.capture.production import ProductionCaptureAdapter
from radioflix.timefree.capture.source.models import HttpResponse
from radioflix.timefree.capture.source.transport import FakeHttpTransport
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.worker import TimefreeWorker
import test_timefree


class ProductionStackTests(unittest.TestCase):
    def setUp(self):
        self.f = test_timefree.TimefreeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.output.mkdir()
        self.recordings = self.f.root / 'normal'
        self.recordings.mkdir()
        self.guard = Preflight(self.f.store, self.f.guide.native_dir, [self.recordings], self.f.output)
        self.env = patch.dict(os.environ, {'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '1',
            'RADIOFLIX_TIMEFREE_BOOT_MODE': 'enabled', 'RFRIENDS_ENABLE_WRITES': '0'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.row = self.queue()
        with self.f.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET execution_kind='live'")
        self.http = FakeHttpTransport([])
        self.adapter = self.make_adapter(self.http)
        self.worker = TimefreeWorker(self.f.store, self.f.output, self.adapter,
            preflight=self.guard, clock=lambda: self.f.now)

    def queue(self, *, offset=0):
        start = datetime.fromisoformat(self.f.item['starts_at']) + timedelta(minutes=offset)
        end = start + timedelta(seconds=1)
        self.f.item['starts_at'], self.f.item['ends_at'] = start.isoformat(), end.isoformat()
        self.f.item['id'] = hashlib.sha256(
            f"{self.f.item['station']}:{start.isoformat()}:{end.isoformat()}".encode()).hexdigest()
        return self.f.post().json()

    def make_adapter(self, http, **kwargs):
        adapter = ProductionCaptureAdapter(store=self.f.store, managed_root=self.f.output,
            preflight=self.guard, transport=http, bridge_approved=True,
            clock=lambda: self.f.now, executable=Path('/usr/bin/ffmpeg').resolve(strict=True),
            preflight_allowlisted_path=Path('/usr/bin/ffmpeg').resolve(strict=True), **kwargs)
        adapter.refresh_readiness()
        return adapter

    def script(self):
        path = self.f.root / 'synthetic.aac'
        if not path.exists():
            subprocess.run(['/usr/bin/ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1',
                '-c:a', 'aac', '-f', 'adts', '-n', str(path)], check=True,
                timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return [HttpResponse(200, body=b'RadikoJSPlayer(x,"pc_html5","0123456789abcdef0123456789abcdef01234567",{})'),
            HttpResponse(200, headers={'X-Radiko-AuthToken': 'TEST_ONLY', 'X-Radiko-KeyOffset': '0', 'X-Radiko-KeyLength': '16'}),
            HttpResponse(200, body=b'JP13,fixture'),
            HttpResponse(200, body=b'<urls><url areafree="0" timefree="1"><playlist_create_url>https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/fixture/index.m3u8</playlist_create_url></url></urls>'),
            HttpResponse(200, body=b'#EXTM3U\n#EXTINF:1,\nsegment.aac\n#EXT-X-ENDLIST\n'),
            HttpResponse(200, body=path.read_bytes())]

    def successful_stack(self):
        self.http = FakeHttpTransport(self.script())
        self.adapter = self.make_adapter(self.http)
        self.worker.transport = self.adapter

    def test_production_stack_capture_validate_publish(self):
        self.successful_stack()
        with patch('socket.create_connection', side_effect=AssertionError('no network')), patch(
                'socket.getaddrinfo', side_effect=AssertionError('no DNS')):
            self.assertTrue(self.adapter.ready)
            self.assertEqual(self.worker.run_once(self.row['job_id']), self.row['job_id'])
        self.assertEqual(self.f.store.get(self.row['job_id'])['state'], 'completed')
        self.assertEqual(len(self.http.requests), 6)
        self.assertEqual(len(list(self.f.output.glob('*/audio.wav'))), 1)
        self.assertIsNotNone(self.f.store.publication(self.row['job_id']))

    def test_ready_is_local_and_not_approval(self):
        self.adapter.bridge_approved = False
        self.assertTrue(self.adapter.ready)
        self.assertEqual(self.http.requests, [])
        with self.assertRaises(CaptureNotReady):
            with self.adapter.capture_job(self.row['job_id']):
                self.fail('must reject')
        self.assertEqual(self.http.requests, [])

    def test_start_matrix(self):
        for mode, gate, ready, approved in [('disabled','1',True,True),
                ('enabled','0',True,True), ('enabled','1',False,True), ('enabled','1',True,False)]:
            with self.subTest(mode=mode,gate=gate,ready=ready,approved=approved), patch.dict(
                    os.environ, {'RADIOFLIX_TIMEFREE_BOOT_MODE':mode, 'RADIOFLIX_TIMEFREE_ENABLE_WRITES':gate}):
                from types import SimpleNamespace
                with self.assertRaises(CaptureNotReady):
                    require_runtime_capture(SimpleNamespace(ready=ready, bridge_approved=approved))
        require_runtime_capture(self.adapter)

    def test_revocation_is_checked_at_http_boundary(self):
        with patch.dict(os.environ, {'RADIOFLIX_TIMEFREE_ENABLE_WRITES':'0'}):
            # Authentication deliberately sanitizes exceptions at its source boundary.
            from radioflix.timefree.capture.source.errors import SourceFailure, SourceCode
            with self.assertRaises(SourceFailure) as error:
                self.adapter.authenticator.authenticate(None, timeout_seconds=1)
            self.assertEqual(error.exception.code, SourceCode.AUTH_FAILED)
        self.assertEqual(self.http.requests, [])

    def test_missing_source_not_ready(self):
        self.adapter.source_transport = None
        self.assertFalse(self.adapter.refresh_readiness().ready)

    def test_missing_stage_not_ready(self):
        for name in ('authenticator','playlist_provider','media_fetcher'):
            with self.subTest(stage=name), patch.object(self.adapter,name,None):
                self.assertFalse(self.adapter.refresh_readiness().ready)

    def test_missing_executable_not_ready(self):
        self.adapter.transcoder.executable = Path('/missing/ffmpeg')
        self.assertFalse(self.adapter.refresh_readiness().ready)
        self.assertEqual(self.http.requests, [])

    def test_store_read_only_not_ready(self):
        self.f.store.read_only = True
        self.assertFalse(self.adapter.refresh_readiness().ready)

    def test_store_missing_schema_not_ready(self):
        self.f.store.path = self.f.root / 'empty.sqlite'
        sqlite3.connect(self.f.store.path).close()
        self.assertFalse(self.adapter.refresh_readiness().ready)

    def test_staging_symlink_not_ready(self):
        (self.f.output / '.staging').symlink_to(self.recordings, target_is_directory=True)
        self.assertFalse(self.adapter.refresh_readiness().ready)

    def test_no_preflight_not_ready(self):
        self.adapter.preflight = None
        self.assertFalse(self.adapter.refresh_readiness().ready)

    def test_long_program_rejected_before_auth(self):
        row=self.row
        with self.f.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET state='running' WHERE job_id=?", (row['job_id'],))
        from radioflix.timefree.capture.adapter import CaptureAdapter
        with patch.object(CaptureAdapter, '_metadata', return_value=({},None,61)):
            with self.assertRaisesRegex(ValueError,'media_duration_invalid'):
                with self.adapter.capture_job(row['job_id']): pass
        self.assertEqual(self.http.requests, [])

    def test_unknown_host_stays_rejected(self):
        replies=self.script()
        replies[3]=HttpResponse(200,body=b'<urls><url areafree="0" timefree="1"><playlist_create_url>https://unapproved.invalid/tf/x</playlist_create_url></url></urls>')
        self.http=FakeHttpTransport(replies)
        self.worker.transport=self.make_adapter(self.http)
        self.worker.run_once(self.row['job_id'])
        self.assertEqual(self.f.store.get(self.row['job_id'])['state'],'failed')
        self.assertEqual(len(self.http.requests),4)
        self.assertFalse(list(self.f.output.glob('*/audio.wav')))

    def test_guard_and_ready_property_do_not_run_preflight(self):
        self.assertTrue(self.adapter.ready)
        with patch.object(self.adapter, 'local_preflight', side_effect=AssertionError('not pure')):
            require_runtime_capture(self.adapter)
            self.assertTrue(self.adapter.ready)

    def test_default_symlink_executable_fails_closed(self):
        link = self.f.root / 'ffmpeg'
        link.symlink_to(Path('/usr/bin/ffmpeg').resolve(strict=True))
        adapter = ProductionCaptureAdapter(store=self.f.store, managed_root=self.f.output,
            preflight=self.guard, transport=self.http, executable=link)
        self.assertFalse(adapter.refresh_readiness().ready)

    def test_local_change_is_rechecked_before_auth(self):
        self.successful_stack()
        self.adapter.transcoder.executable = Path('/missing/ffmpeg')
        self.worker.run_once(self.row['job_id'])
        self.assertEqual(self.f.store.get(self.row['job_id'])['state'], 'failed')
        self.assertEqual(self.http.requests, [])

    def test_factory_keeps_local_readiness_independent_of_approval(self):
        from radioflix.timefree.control import production_worker
        from radioflix.timefree.capture.production import WorkspaceTranscoder
        with patch.dict(os.environ, {'RADIOFLIX_DB_PATH': str(self.f.store.path),
                'RADIOFLIX_TIMEFREE_ROOT': str(self.f.output)}), patch(
                'radioflix.timefree.capture.production.WorkspaceTranscoder',
                side_effect=lambda executable, **kw: WorkspaceTranscoder(
                    Path('/usr/bin/ffmpeg').resolve(strict=True),
                    preflight_allowlisted_path=Path('/usr/bin/ffmpeg').resolve(strict=True))):
            worker = production_worker(transport=self.http)
        self.assertTrue(worker.transport.ready)
        self.assertFalse(worker.transport.bridge_approved)
        self.assertTrue(worker.read_only)
        self.assertTrue(worker.store.read_only)
        self.assertIsNone(worker.run_once(self.row['job_id']))
        self.assertEqual(self.http.requests, [])

    def test_disabled_factory_never_runs_local_probe_or_network(self):
        from radioflix.timefree.control import production_app
        with patch.dict(os.environ, {'RADIOFLIX_DB_PATH': str(self.f.store.path),
                'RADIOFLIX_TIMEFREE_ROOT': str(self.f.output),
                'RADIOFLIX_TIMEFREE_BOOT_MODE': 'disabled'}), patch.object(
                ProductionCaptureAdapter, 'local_preflight', side_effect=AssertionError('disabled probe')):
            app = production_app()
            endpoints = {r.path: r.endpoint for r in app.routes}
            self.assertFalse(endpoints['/health']()['capture_ready'])
            self.assertFalse(endpoints['/health']()['writes_enabled'])
            self.assertEqual(endpoints['/status']()['job_count'], 1)
