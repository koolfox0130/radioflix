"""One-job CLI/worker tests with Fake ports and network-none fixtures only."""
import json
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from radioflix.timefree.acceptance import approved_job, main
from radioflix.timefree.contracts import CaptureNotReady
from radioflix.timefree.capture.errors import CaptureFailure
from radioflix.timefree.capture.fixture import (FixtureAuthenticator, FixtureMediaFetcher,
    FixturePlaylistProvider, SyntheticAudioTranscoder)
from radioflix.timefree.capture.adapter import CaptureAdapter
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.service import eligibility
from radioflix.api.timefree import TimefreeRequest
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker, completed_assets
from radioflix.timefree.publisher import rename_noreplace
import test_timefree


class CountAuthenticator(FixtureAuthenticator):
    def __init__(self, **kwargs):
        super().__init__(**kwargs); self.capture_count = 0
    def authenticate(self, *args, **kwargs):
        self.capture_count += 1
        return super().authenticate(*args, **kwargs)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.f = test_timefree.TimefreeTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.output.mkdir(); self.recordings=self.f.root/'normal'; self.recordings.mkdir()
        self.guard=Preflight(self.f.store,self.f.guide.native_dir,[self.recordings],self.f.output)
        self.env=patch.dict(os.environ, {'RADIOFLIX_TIMEFREE_BOOT_MODE':'enabled',
            'RADIOFLIX_TIMEFREE_ENABLE_WRITES':'1','RFRIENDS_ENABLE_WRITES':'0'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.rows=[self.queue(0),self.queue(1)]
        with self.f.store.transaction() as db: db.execute("UPDATE timefree_jobs SET execution_kind='fixture'")
        self.auth=CountAuthenticator(); self.media=FixtureMediaFetcher()
        self.transcoder=SyntheticAudioTranscoder(1)
        self.adapter=CaptureAdapter(store=self.f.store,managed_root=self.f.output,
            authenticator=self.auth,playlist_provider=FixturePlaylistProvider(),media_fetcher=self.media,
            transcoder=self.transcoder,preflight=self.guard,clock=lambda:self.f.now,timeout_seconds=10)
        # Acceptance checks runtime gates while all capture ports remain fixture-only.
        self.adapter.ready=True; self.adapter.bridge_approved=True
        self.worker=TimefreeWorker(self.f.store,self.f.output,self.adapter,preflight=self.guard,
                                   clock=lambda:self.f.now)
        self.approval=self.f.root/'approval.json'
        self.write_approval(self.rows[0]['job_id'])
        self.approval_env=patch.dict(os.environ, {'RADIOFLIX_DB_PATH':str(self.f.store.path),
            'RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE':str(self.approval)})
        self.approval_env.start(); self.addCleanup(self.approval_env.stop)

    def queue(self, offset):
        start=datetime.fromisoformat(self.f.item['starts_at'])+timedelta(minutes=offset)
        end=start+timedelta(seconds=1)
        self.f.item.update(starts_at=start.isoformat(),ends_at=end.isoformat())
        import hashlib
        self.f.item['id']=hashlib.sha256(f"{self.f.item['station']}:{start.isoformat()}:{end.isoformat()}".encode()).hexdigest()
        # Call the in-process fixture service directly. TestClient starts an
        # ASGI portal, which is unnecessary for this worker/process contract.
        return self.f.service.create(TimefreeRequest(**self.f.request()))

    def write_approval(self, ident, *, approval=True, expires=None, mode=0o600):
        expires=expires or (datetime.now(timezone.utc)+timedelta(minutes=5))
        self.approval.write_text(json.dumps({'job_id':ident,'approved':approval,'expires_at':expires.isoformat()}))
        self.approval.chmod(mode)

    def factory(self, **kwargs):
        return self.worker

    def run_cli(self, ident=None):
        argv=[] if ident is None else ['--accept-job',ident]
        return main(argv,worker_factory=self.factory)

    def states(self): return [self.f.store.get(row['job_id'])['state'] for row in self.rows]

    def test_two_queued_process_exactly_target_and_exit(self):
        with patch('radioflix.timefree.control.create_app',side_effect=AssertionError('server/loop started')):
            code=self.run_cli(self.rows[0]['job_id'])
        self.assertEqual(code,0)
        self.assertEqual(self.states(),['completed','queued'])
        self.assertEqual(self.auth.capture_count,1)
        self.assertEqual(self.media.calls and len(self.media.calls),1)
        self.assertEqual(len(self.transcoder.calls),1)
        self.assertEqual(len(list(self.f.output.glob('*/audio.wav'))),1)
        self.assertEqual(len(self.f.store.list()),2)
        self.assertEqual(len(completed_assets(self.f.store,self.f.output,include_fixture=True)),1)
        with sqlite3.connect(self.f.store.path) as db:
            self.assertEqual([row[0] for row in db.execute(
                'SELECT state FROM timefree_events WHERE job_id=? ORDER BY seq',
                (self.rows[0]['job_id'],))], ['queued','running','completed'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM timefree_publications').fetchone()[0],1)
        self.assertEqual(self.worker.accept_one(self.rows[0]['job_id']),'completed')
        self.assertEqual(self.auth.capture_count,1)

    def test_cli_requires_explicit_job_id(self):
        with self.assertRaises(SystemExit): main([],worker_factory=self.factory)
        self.assertEqual(self.states(),['queued','queued']); self.assertEqual(self.auth.capture_count,0)

    def test_unknown_id_fails_without_touching_queued_jobs(self):
        result=self.run_cli('f'*32)
        self.assertEqual(result,2); self.assertEqual(self.states(),['queued','queued'])
        self.assertEqual(self.auth.capture_count,0)

    def test_completed_is_noop_without_approval_or_factory(self):
        self.complete_existing(self.rows[0])
        self.approval.unlink()
        factory=Mock(side_effect=AssertionError('capture stack constructed'))
        with patch.dict(os.environ,{'RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE':str(self.approval)}):
            self.assertEqual(main(['--accept-job',self.rows[0]['job_id']],worker_factory=factory),0)
        factory.assert_not_called();self.assertEqual(self.auth.capture_count,0)
        self.assertEqual(self.states(),['completed','queued'])

    def complete_existing(self,row):
        # Produce a legitimate fixture publication using existing safety path.
        fixture_adapter=CaptureAdapter(store=self.f.store,managed_root=self.f.output,
            authenticator=FixtureAuthenticator(),playlist_provider=FixturePlaylistProvider(),
            media_fetcher=FixtureMediaFetcher(),transcoder=SyntheticAudioTranscoder(1),
            preflight=self.guard,clock=lambda:self.f.now,timeout_seconds=10)
        fixture_worker=TimefreeWorker(self.f.store,self.f.output,fixture_adapter,
            preflight=self.guard,clock=lambda:self.f.now)
        fixture_worker.run_once(row['job_id'])

    def test_cancelled_and_expired_do_not_capture(self):
        with self.f.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET state='cancelled' WHERE job_id=?",(self.rows[0]['job_id'],))
        self.assertEqual(self.run_cli(self.rows[0]['job_id']),0)
        with patch('radioflix.timefree.worker.eligibility',return_value='expired'):
            # Existing eligibility is checked in worker, before any capture.
            self.rows[1]['state']='queued'
            expired_worker=self.worker
            # Use a direct worker target after writing the explicit approved job ID.
            self.write_approval(self.rows[1]['job_id'])
            self.assertEqual(expired_worker.accept_one(self.rows[1]['job_id']),'expired')
        self.assertEqual(self.auth.capture_count,0)
        self.assertEqual(self.f.store.get(self.rows[1]['job_id'])['state'],'expired')

    def test_all_guard_failures_reject_before_capture(self):
        for mode,gate,ready,approved in [('enabled','0',True,True),('enabled','1',False,True),
                                         ('enabled','1',True,False),('disabled','1',True,True)]:
            with self.subTest(mode=mode,gate=gate,ready=ready,approved=approved),patch.dict(os.environ,{
                    'RADIOFLIX_TIMEFREE_BOOT_MODE':mode,'RADIOFLIX_TIMEFREE_ENABLE_WRITES':gate}):
                self.adapter.ready=ready; self.adapter.bridge_approved=approved
                with self.assertRaises(CaptureNotReady): self.worker.accept_one(self.rows[0]['job_id'])
                self.assertEqual(self.states(),['queued','queued'])
        self.assertEqual(self.auth.capture_count,0)

    def test_approval_is_job_bound_expiring_and_not_a_gate_override(self):
        self.write_approval(self.rows[1]['job_id'])
        self.assertTrue(approved_job(self.approval,self.rows[1]['job_id']))
        with self.assertRaises(ValueError): approved_job(self.approval,self.rows[0]['job_id'])
        self.write_approval(self.rows[0]['job_id'],approval=False)
        with self.assertRaises(ValueError): approved_job(self.approval,self.rows[0]['job_id'])
        self.write_approval(self.rows[0]['job_id'],expires=datetime.now(timezone.utc)-timedelta(seconds=1))
        with self.assertRaises(ValueError): approved_job(self.approval,self.rows[0]['job_id'])
        self.write_approval(self.rows[0]['job_id'],mode=0o644)
        with self.assertRaises(ValueError): approved_job(self.approval,self.rows[0]['job_id'])

    def test_failure_stops_and_never_publishes(self):
        for stage,setup in [('capture',lambda:setattr(self.media,'fail',True)),
            ('transcode',lambda:setattr(self.transcoder,'fail',True)),
            ('validator',lambda:setattr(self.transcoder,'wrong_format',True))]:
            with self.subTest(stage=stage):
                # Separate queued target per scenario, same process semantics.
                row=self.rows[0]
                with self.f.store.transaction() as db: db.execute("UPDATE timefree_jobs SET state='queued',execution_kind='fixture' WHERE job_id=?",(row['job_id'],))
                setup()
                self.assertEqual(self.worker.accept_one(row['job_id']),'failed')
                self.assertEqual(self.f.store.get(row['job_id'])['state'],'failed')
                self.assertIsNone(self.f.store.publication(row['job_id']))
                self.assertFalse((self.f.output/row['job_id']).exists())
                captures=self.auth.capture_count
                self.assertEqual(self.worker.accept_one(row['job_id']),'failed')
                self.assertEqual(self.auth.capture_count,captures)
                self.media.fail=False;self.transcoder.fail=False;self.transcoder.wrong_format=False
                with self.f.store.transaction() as db: db.execute("UPDATE timefree_jobs SET state='queued',execution_kind='fixture',started_at=NULL,failed_at=NULL WHERE job_id=?",(row['job_id'],))

    def test_duplicate_output_fails_without_overwrite(self):
        row=self.rows[0]; target=self.f.output/row['job_id'];target.mkdir();(target/'keep').write_text('fixture')
        self.assertEqual(self.worker.accept_one(row['job_id']),'failed')
        self.assertEqual((target/'keep').read_text(),'fixture')
        self.assertIsNone(self.f.store.publication(row['job_id']))

    def test_native_conflict_at_start_and_publish(self):
        for stage in ('start','publish'):
            row=self.rows[0]
            with self.f.store.transaction() as db:
                db.execute("UPDATE timefree_jobs SET state='queued',execution_kind='fixture',started_at=NULL,failed_at=NULL WHERE job_id=?",(row['job_id'],))
            with patch.object(self.worker,'preflight',side_effect=ValueError('native_conflict')):
                # At start fails before capture; publication is separately blocked below.
                if stage=='start':
                    self.assertEqual(self.worker.accept_one(row['job_id']),'failed')
                    self.assertEqual(self.auth.capture_count,0)
                else:
                    original=self.worker.preflight; calls=[]
                    def conflict_after_capture(current):
                        calls.append(current)
                        if len(calls)>1: raise ValueError('native_conflict')
                        # Still execute the actual read-only native and duplicate checks.
                        self.guard(current)
                    self.worker.preflight=conflict_after_capture
                    try:self.worker.accept_one(row['job_id'])
                    finally:self.worker.preflight=original
                    self.assertEqual(self.f.store.get(row['job_id'])['state'],'failed')
                    self.assertEqual(self.auth.capture_count,1)
                    self.assertIsNone(self.f.store.publication(row['job_id']))

    def test_recovery_target_only_never_recaptures_or_touches_second(self):
        row=self.rows[0]
        with self.f.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET state='running' WHERE job_id=?",(row['job_id'],))
        self.assertEqual(self.worker.accept_one(row['job_id']),'unknown')
        self.assertEqual(self.states(),['unknown','queued'])
        self.assertEqual(self.auth.capture_count,0)

    def test_cli_help_and_timeout_process_exit(self):
        help_result=subprocess.run([sys.executable,'-m','radioflix.timefree.acceptance','--help'],
            capture_output=True,text=True,timeout=5,env={**os.environ,'PYTHONPATH':os.pathsep.join((str(Path(__file__).parents[1]),os.environ.get('PYTHONPATH','')))})
        self.assertEqual(help_result.returncode,0);self.assertIn('--accept-job',help_result.stdout)
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run([sys.executable,'-m','radioflix.timefree.acceptance'],capture_output=True,
                timeout=5,check=True,env={**os.environ,'PYTHONPATH':os.pathsep.join((str(Path(__file__).parents[1]),os.environ.get('PYTHONPATH','')))})

    def test_approval_file_symlink_refused(self):
        link=self.f.root/'approval-link';link.symlink_to(self.approval)
        with self.assertRaises(ValueError): approved_job(link,self.rows[0]['job_id'])

    def test_second_job_state_and_events_remain_untouched(self):
        before=self.f.store.get(self.rows[1]['job_id'])
        self.assertEqual(self.run_cli(self.rows[0]['job_id']),0)
        after=self.f.store.get(self.rows[1]['job_id'])
        self.assertEqual(before,after)
        with sqlite3.connect(self.f.store.path) as db:
            self.assertEqual([row[0] for row in db.execute(
                'SELECT state FROM timefree_events WHERE job_id=? ORDER BY seq',
                (self.rows[1]['job_id'],))], ['queued'])

    def test_process_exits_after_only_the_explicit_job(self):
        ctx=multiprocessing.get_context('fork')
        process=ctx.Process(target=_child_accept, args=(self, self.rows[0]['job_id']))
        process.start();process.join(8)
        if process.is_alive(): process.terminate();process.join(2)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode,0)
        self.assertEqual(self.states(),['completed','queued'])
        self.assertEqual(len(list(self.f.output.glob('*/audio.wav'))),1)

    def test_recovery_after_capture_transcode_validation_and_publish_boundaries(self):
        boundaries=('after_capture','after_transcode','after_validate','publish_intent','after_publish')
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                fresh=AcceptanceTests();fresh.setUp()
                try: fresh._crash_at_boundary(boundary)
                finally: fresh.doCleanups()

    def _crash_at_boundary(self,boundary):
        job=self.rows[0]['job_id']
        patcher=None
        if boundary=='after_capture':
            original=self.adapter.media_fetcher.download
            def crash_after_capture(*a,**kw): original(*a,**kw); raise KeyboardInterrupt()
            self.adapter.media_fetcher.download=crash_after_capture
        elif boundary=='after_transcode':
            original=self.adapter.transcoder.convert
            def crash_after_transcode(*a,**kw): original(*a,**kw); raise KeyboardInterrupt()
            self.adapter.transcoder.convert=crash_after_transcode
        elif boundary=='after_validate':
            original=self.worker.preflight; count=[]
            def crash_before_publish(row):
                original(row);count.append(row)
                if len(count)==2: raise KeyboardInterrupt()
            self.worker.preflight=crash_before_publish
        elif boundary=='publish_intent':
            def crash_after_intent(source,target): raise KeyboardInterrupt()
            patcher=patch('radioflix.timefree.publisher.rename_noreplace',side_effect=crash_after_intent)
            patcher.start();self.addCleanup(patcher.stop)
        elif boundary=='after_publish':
            patcher=patch.object(self.worker,'completed',side_effect=KeyboardInterrupt())
            patcher.start();self.addCleanup(patcher.stop)
        with self.assertRaises(KeyboardInterrupt): self.worker.accept_one(job)
        if patcher is not None:
            patcher.stop()
        self.assertEqual(self.f.store.get(job)['state'],'running')
        captures=self.auth.capture_count
        # A subsequent process uses target-only, proof-based reconciliation and never captures again.
        with patch.object(self.adapter.authenticator,'authenticate',side_effect=AssertionError('recapture')):
            result=self.worker.accept_one(job)
        if boundary=='after_publish':
            self.assertEqual(result,'completed')
            self.assertEqual(len(completed_assets(self.f.store,self.f.output,include_fixture=True)),1)
        else:
            self.assertEqual(result,'unknown')
            self.assertEqual(self.f.store.get(job)['state'],'unknown')
        self.assertEqual(self.states()[1],'queued')
        self.assertEqual(self.auth.capture_count,captures)


def _child_accept(test_case, job_id):
    code=test_case.run_cli(job_id)
    raise SystemExit(code)
