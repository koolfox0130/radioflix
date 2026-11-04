"""Target -> real admission CLI/service -> runner -> offline capture; no Docker/HTTP.

Only Docker/process and external HTTP ports are replaced. Store, guards, approval
readers, runner ordering, worker, transcoder, publisher and API Range are real.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from radioflix.api.timefree import TimefreeRequest
from radioflix.timefree import admission, acceptance
from radioflix.timefree.acceptance_probe import inspect_state
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.service import TimefreeService
from radioflix.timefree.capture.source.models import HttpResponse
from radioflix.services.program_service import ProgramService
from radioflix.services.recording_catalog import RecordingCatalog
import test_timefree
import test_timefree_acceptance_profile
import test_timefree_onejob_runner
import test_recording_catalog

runner = test_timefree_onejob_runner.runner


class AdmissionRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_timefree_acceptance_profile.FiveMinuteTests.setUpClass.__func__(cls)

    stack = test_timefree_acceptance_profile.FiveMinuteTests.stack

    def setUp(self):
        self.f = test_timefree.TimefreeTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.output.mkdir()
        self.normal_root = self.f.root / 'normal'; self.normal_root.mkdir()
        self.native_timefree = self.f.root / 'native-timefree'; self.native_timefree.mkdir()
        normal_dir = self.normal_root / 'existing'; normal_dir.mkdir()
        (normal_dir / 'TBS_Existing_20300101_1200_1205.wav').write_bytes(b'fixture-audio' * 200)
        self.guard = Preflight(self.f.store, self.f.guide.native_dir,
                               [self.normal_root, self.native_timefree], self.f.output)
        self.live = TimefreeService(self.f.store, self.f.guide.service, clock=lambda: self.f.now,
                                   acceptance_recording_roots=[self.normal_root, self.native_timefree])
        self.set_target(300)
        self.target = self.f.request()
        self.candidate = copy.deepcopy(self.f.item)
        # JOB-B is a non-acceptance fixture job. An additional live queued job
        # must block the workflow; a non-acceptance job must remain untouched.
        self.set_target(300, offset=10)
        self.other = self.f.service.create(TimefreeRequest(**self.f.request()))
        self.f.item = copy.deepcopy(self.candidate)
        self.before_other = self.f.store.get(self.other['job_id'])
        self.rows = []
        self.directory = self.f.root / 'runner'; self.directory.mkdir()
        self.approval = self.directory / 'approval.json'
        self.service, self.data = test_timefree_onejob_runner.RunnerTests.rendered_fixture(self)
        self.service['image'] = 'fixture:revision'
        self.before = {'backend': {'image': 'fixture'}, 'timefree-worker': {'image': 'fixture'}}
        self.failure = None
        self.capture_calls = 0
        self.admit_calls = 0
        self.socket_calls = []
        self.programs = ProgramService(self.normal_root)
        self.catalog = RecordingCatalog(self.programs, self.f.store, self.f.output)
        self.client = test_recording_catalog.RecordingCatalogTests.api_client(self)
        self.addCleanup(self.client.close)
        self.env = {'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '0', 'RFRIENDS_ENABLE_WRITES': '0',
                    'RADIOFLIX_TIMEFREE_BOOT_MODE': 'disabled', 'RADIOFLIX_DB_PATH': str(self.f.store.path),
                    'RADIOFLIX_TIMEFREE_ADMISSION_APPROVAL_FILE': str(self.directory/'admission.json'),
                    'RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE': str(self.approval)}
        for patcher in (patch.dict(os.environ, self.env),
                        patch.object(runner, 'execution_context', side_effect=self.context),
                        patch.object(runner, 'render', side_effect=self.render),
                        patch.object(runner, 'docker', side_effect=self.docker),
                        patch.object(runner, 'safety', side_effect=self.safety),
                        patch.object(runner, 'smoke', side_effect=self.normal_smoke),
                        patch('socket.create_connection', side_effect=AssertionError('network forbidden')),
                        patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden'))):
            patcher.start(); self.addCleanup(patcher.stop)

    def set_target(self, seconds, offset=0):
        start = datetime.fromisoformat(self.f.item['starts_at']) + timedelta(minutes=offset)
        end = start + timedelta(seconds=seconds)
        self.f.item.update(starts_at=start.isoformat(), ends_at=end.isoformat())
        self.f.item['id'] = hashlib.sha256(f"{self.f.item['station']}:{start.isoformat()}:{end.isoformat()}".encode()).hexdigest()
        self.f.item.pop('schedule_revision', None)
        self.f.item['schedule_revision'] = hashlib.sha256(json.dumps(self.f.item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def context(self, ident, directory):
        base, env, service, data = self.render('fixture:revision', ident, self.approval)
        return 'fixture:revision', base, env, service, data, self.safety()

    def render(self, image, ident, approval):
        self.service['command'] = ['--accept-job', ident]
        return ['compose'], os.environ.copy(), self.service, self.data

    def safety(self):
        self.assertEqual(os.environ['RADIOFLIX_TIMEFREE_ENABLE_WRITES'], '0')
        self.assertEqual(os.environ['RFRIENDS_ENABLE_WRITES'], '0')
        self.assertEqual(os.environ['RADIOFLIX_TIMEFREE_BOOT_MODE'], 'disabled')
        return self.before

    def normal_smoke(self):
        programs = self.client.get('/api/programs').json()
        normal = next(p for p in programs if p.get('source', 'normal') == 'normal')
        episodes = self.client.get('/api/programs/' + normal['id'] + '/episodes').json()
        response = self.client.get(episodes[0]['audio_url'], headers={'Range': 'bytes=0-1023'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 1024)

    def docker(self, *args, **kwargs):
        if args[0] in ('ps', 'network'):
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'compose':
            if self.failure == 'launch':
                raise ValueError('fixture_launch_failed')
            self.capture_calls += 1
            ident = self.service['command'][1]
            self.rows = [self.f.store.get(ident), self.before_other]
            if self.failure == 'approval':
                data = json.loads(self.approval.read_text()); data['job_id'] = '0'*32
                self.approval.write_text(json.dumps(data))
            with patch.dict(os.environ, {'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '1',
                                        'RADIOFLIX_TIMEFREE_BOOT_MODE': 'enabled'}):
                self.stack(63 if self.failure == 'segments' else 61)
                if self.failure == 'capture': self.responses[7] = HttpResponse(403)
                if self.failure == 'wire': self.http.wire_requests = 73
                if self.failure == 'validation':
                    self.responses[-1] = HttpResponse(200, body=b'not-adts')
                with patch.object(self.http, '_public_addresses', return_value=('8.8.8.8',)), patch.object(
                        self.http, '_open_once', side_effect=self.responses), contextlib.redirect_stdout(io.StringIO()):
                    code = acceptance.main(['--accept-job', ident], worker_factory=lambda **kw: self.worker)
            return subprocess.CompletedProcess(args, code, '', '')
        self.assertEqual(args[0], 'run')
        self.assertIn('--read-only', args)
        if '-c' in args:  # root helper: only a temporary fixture authorization
            filename, payload = args[-2:]
            self.assertIn(filename, ('admission.json', 'approval.json'))
            data = json.loads(payload)
            data.update(approved=True, expires_at=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat())
            path = self.directory / filename
            with path.open('x') as stream: json.dump(data, stream)
            path.chmod(0o600)
            return subprocess.CompletedProcess(args, 0, '', '')
        module = args[args.index('-m')+1]
        if module == 'radioflix.timefree.admission':
            argv = list(args[args.index('-m')+2:])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = admission.main(argv, service_factory=lambda: self.live)
            if '--execute' in argv:
                self.admit_calls += 1
                if self.failure == 'after_admission': raise ValueError('lost_admission_response')
            if code: raise ValueError('admission_rejected')
            return subprocess.CompletedProcess(args, 0, output.getvalue(), '')
        self.assertEqual(module, 'radioflix.timefree.acceptance_probe')
        ident = args[args.index('--job')+1]
        result = inspect_state(ident, self.f.store, self.f.output, self.guard, self.f.now, final='--final' in args)
        return subprocess.CompletedProcess(args, 0, json.dumps(result), '')

    def run_target(self, execute=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = runner.run_target(self.target, self.directory, execute=execute)
        self.summary = json.loads(output.getvalue().splitlines()[-1])
        return code

    def assert_clean(self):
        self.assertFalse(self.approval.exists())
        self.assertFalse((self.directory/'admission.json').exists())
        self.assertEqual(self.f.store.get(self.other['job_id']), self.before_other)
        self.safety()

    def test_dry_run_has_zero_mutations(self):
        before = self.f.store.path.read_bytes()
        self.assertEqual(self.run_target(), 0)
        self.assertEqual(self.f.store.path.read_bytes(), before)
        self.assertEqual(self.admit_calls, 0); self.assertEqual(self.capture_calls, 0)
        self.assertEqual(list(self.f.output.iterdir()), [])
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assert_clean()

    def test_integrated_execute_only_job_a_completed_and_range(self):
        self.assertEqual(self.run_target(True), 0)
        self.assertEqual(self.admit_calls, 1); self.assertEqual(self.capture_calls, 1)
        self.assertEqual(len(self.f.store.list()), 2)
        self.assertEqual(self.summary['final_state'], 'completed')
        self.assertEqual(self.summary['output_count'], 1)
        self.assertEqual(self.summary['published_count'], 1)
        self.assertEqual(self.summary['range_check'], 'PASS')
        self.assertEqual(self.summary['final_gates'], 'OFF')
        self.assert_clean()
        with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(len(self.f.store.list()), 2)
        self.assertEqual(self.capture_calls, 1)

    def test_admission_response_lost_recovery_fails_closed(self):
        self.failure = 'after_admission'
        self.assertEqual(self.run_target(True), 2)
        rows = self.f.store.list(); self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['state']=='queued' for r in rows))
        self.assertEqual(self.capture_calls, 0); self.assert_clean()
        self.failure = None
        with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(self.f.store.list(), rows)

    def test_launch_failure_preserves_queued_and_rejects_retry(self):
        self.failure = 'launch'
        self.assertEqual(self.run_target(True), 2)
        self.assertEqual(len(self.f.store.list()), 2)
        self.assert_clean()
        with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(self.capture_calls, 0)

    def test_301_seconds_rejected_without_admission(self):
        self.set_target(301); self.target = self.f.request()
        with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(len(self.f.store.list()), 1); self.assert_clean()

    def test_unknown_target_rejected_without_admission(self):
        self.target['broadcast_episode_id'] = '0'*64
        with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(len(self.f.store.list()), 1); self.assert_clean()

    def test_native_conflict_rejected_without_admission(self):
        # Inject a parsed native reservation at the inventory boundary.
        from radioflix.services.schedule_service import NativeReservation
        b = self.f.item
        native = NativeReservation('native', b['station'], b['station'], datetime.fromisoformat(b['starts_at']),
                                 datetime.fromisoformat(b['ends_at']))
        with patch.object(self.f.guide.service, 'native_snapshot', return_value=[native]):
            with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(len(self.f.store.list()), 1); self.assert_clean()

    def test_normal_recording_duplicate_rejected(self):
        (self.normal_root/'JORF_Duplicate_20300107_1200_1205.wav').write_bytes(b'existing')
        with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(len(self.f.store.list()), 1); self.assert_clean()

    def test_other_active_live_job_rejected(self):
        with self.f.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET execution_kind='live' WHERE job_id=?", (self.other['job_id'],))
        self.before_other = self.f.store.get(self.other['job_id'])
        with self.assertRaises(ValueError): self.run_target(True)
        self.assertEqual(len(self.f.store.list()), 1); self.assert_clean()

    def test_capture_failure_never_runs_second_job(self):
        self.failure = 'capture'; self.assertEqual(self.run_target(True), 1)
        self.assertEqual(self.summary['final_state'], 'failed'); self.assert_clean()

    def test_segment_63_rejected_never_runs_second_job(self):
        self.failure = 'segments'; self.assertEqual(self.run_target(True), 1)
        self.assertEqual(self.http.wire_requests, 7); self.assert_clean()

    def test_wire_74_rejected_never_runs_second_job(self):
        self.failure = 'wire'; self.assertEqual(self.run_target(True), 1)
        self.assertEqual(self.http.wire_requests, 73); self.assert_clean()

    def test_validation_failure_never_runs_second_job(self):
        self.failure = 'validation'; self.assertEqual(self.run_target(True), 1)
        self.assertEqual(self.summary['output_count'], 0); self.assert_clean()

    def test_capture_approval_mismatch_rejected(self):
        self.failure = 'approval'; self.assertEqual(self.run_target(True), 1)
        self.assertEqual(self.summary['final_state'], 'queued'); self.assert_clean()

    def test_authorizations_are_not_interchangeable(self):
        request = TimefreeRequest(**self.target)
        path = self.directory/'admission.json'
        payload = {'job_id': 'a'*32, 'approved': True,
                   'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        path.write_text(json.dumps(payload)); path.chmod(0o600)
        with self.assertRaises(ValueError): admission.read_approval(path, request)
        payload = {**self.target, 'approved': True, 'expires_at': payload['expires_at']}
        path.write_text(json.dumps(payload))
        with self.assertRaises(ValueError): acceptance.approved_job(path, 'a'*32)
        path.unlink()


    def test_admission_approval_mismatch_and_expiry_leave_no_job(self):
        for change in ({'broadcast_episode_id': '0'*64},
                       {'expires_at': (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}):
            payload = {**self.target, 'approved': True,
                       'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(), **change}
            path = self.directory/'admission.json'
            path.write_text(json.dumps(payload)); path.chmod(0o600)
            with contextlib.redirect_stdout(io.StringIO()):
                code = admission.main([*runner.target_arguments(self.target), '--execute'],
                                      service_factory=lambda: self.live)
            self.assertEqual(code, 2)
            self.assertEqual(len(self.f.store.list()), 1)
            path.unlink()
        self.assert_clean()

    def test_admission_requires_regular_owner_only_authorization(self):
        path = self.directory/'admission.json'
        payload = {**self.target, 'approved': True,
                   'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        path.write_text(json.dumps(payload)); path.chmod(0o644)
        request = TimefreeRequest(**self.target)
        with self.assertRaises(ValueError): admission.read_approval(path, request)
        path.chmod(0o600)
        alias = self.directory/'alias.json'; alias.symlink_to(path)
        with self.assertRaises(ValueError): admission.read_approval(alias, request)
        alias.unlink(); path.unlink()
        self.assert_clean()

    def test_queued_target_race_allows_only_one_admission(self):
        from concurrent.futures import ThreadPoolExecutor
        request = TimefreeRequest(**self.target)
        approval = {**self.target, 'approved': True,
                    'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        def attempt(_):
            try: return self.live.admit_for_acceptance(request, approval)['job_id']
            except Exception: return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertEqual(len(self.f.store.list()), 2)
        self.assertEqual(self.capture_calls, 0)
        self.assert_clean()
