"""One-shot isolated worker. Never starts from an HTTP request or app lifespan."""
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from radioflix.timefree.publisher import Publisher, job_id, audio_info, fsync_dir
from datetime import datetime
from pathlib import Path

from radioflix.schemas.reservations import JST
from radioflix.timefree.service import eligibility, timefree_gate


def safe_file(root, relative):
    if not re.fullmatch(r'[a-f0-9]{32}/audio\.wav', relative):
        raise ValueError('output_path')
    root = Path(root).resolve(strict=True)
    candidate = root / relative
    if candidate.parent.is_symlink() or candidate.is_symlink() or candidate.resolve().parent.parent != root:
        raise ValueError('output_path')
    if not stat.S_ISREG(candidate.stat().st_mode):
        raise ValueError('output_type')
    return candidate


class FixturePHP:
    """Only available by explicit test construction; never selected via API/env."""
    kind = 'fixture'

    def __init__(self, command, source_dir, scenario='success'):
        self.command, self.source_dir, self.scenario = command, str(source_dir), scenario

    def run(self, row, work):
        payload = {'job_id': row['job_id'], 'broadcast': row['broadcast'], 'work': str(work),
                   'scenario': self.scenario, 'source_dir': self.source_dir}
        runner = Path(__file__).with_name('worker.php')
        result = subprocess.run([*self.command, str(runner), '--fixture'], input=json.dumps(payload),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                                env={**os.environ, 'RFRIENDS_ENABLE_WRITES': '0', 'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '0'})
        # No raw PHP stdout/stderr/exception text goes into the API or journal.
        if result.returncode or len(result.stdout) > 2048:
            raise ValueError('worker_failed')
        answer = json.loads(result.stdout)
        if answer.get('state') != 'completed':
            raise ValueError('worker_failed')
        return work / 'output' / 'audio.wav'


class TimefreeWorker:
    def __init__(self, store, root, transport, *, clock=None, preflight=None, read_only=False):
        self.store, self.root, self.transport = store, Path(root), transport
        self.clock = clock or (lambda: datetime.now(JST))
        self.preflight = preflight
        self.read_only = bool(read_only or getattr(store, 'read_only', False))
        self.publisher = Publisher(self.root, store)

    @contextmanager
    def locked(self):
        # DB-scoped lock: changing the output root cannot bypass worker ownership.
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.store.path) + '.timefree.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def completed(self, row, manifest):
        with self.store.transaction() as db:
            db.execute("""UPDATE timefree_jobs SET state='completed',completed_at=?,
                output_path=?,output_sha256=?,output_size=?,duration=?,error_code=NULL,error_message=NULL
                WHERE job_id=? AND state IN ('running','unknown','completed')""",
                (self.clock().isoformat(), manifest['relative_path'], manifest['sha256'],
                 manifest['size'], manifest['duration'], row['job_id']))
            self.store.event(db, row['job_id'], 'completed', self.clock().isoformat())

    def failed(self, row, state, code):
        with self.store.transaction() as db:
            db.execute('UPDATE timefree_jobs SET state=?,failed_at=?,error_code=?,error_message=? WHERE job_id=?',
                       (state, self.clock().isoformat(), code, '録音結果または開始条件を確認してください。', row['job_id']))
            self.store.event(db, row['job_id'], state, self.clock().isoformat())

    def _reconcile(self):
        for row in self.store.list():
            if row['execution_kind'] != self.transport.kind or row['state'] not in ('running', 'unknown', 'completed'):
                continue
            try:
                manifest = self.publisher.verify(row)
                # Complete only after durable intent + final manifest + actual audio agree.
                fsync_dir(self.root / row['job_id'])
                fsync_dir(self.root)
            except (OSError, ValueError, TypeError, KeyError, EOFError, wave.Error):
                if row['state'] != 'unknown':
                    self.failed(row, 'unknown', 'recovery_unverified')
            else:
                if row['state'] != 'completed':
                    self.completed(row, manifest)
        # Orphan .staging/work files are preserved, never promoted or listed.

    def reconcile(self):
        if self.read_only:
            return False
        if not self.store.path.exists():
            return
        with self.locked() as acquired:
            if acquired:
                self._reconcile()

    def run_once(self, requested_id=None):
        if requested_id is not None:
            job_id(requested_id)
        if self.read_only:
            return None
        if self.transport.kind != 'fixture' and not timefree_gate():
            return None
        with self.locked() as acquired:
            if not acquired:
                return None
            self.publisher.prepare_root()
            self._reconcile()
            with self.store.transaction() as db:
                candidate = db.execute("""SELECT * FROM timefree_jobs WHERE state='queued'
                    AND execution_kind=? AND (? IS NULL OR job_id=?) ORDER BY created_at,job_id LIMIT 1""",
                    (self.transport.kind, requested_id, requested_id)).fetchone()
                if not candidate:
                    return None
                row = self.store.decode(candidate)
                db.execute("UPDATE timefree_jobs SET state='running',started_at=? WHERE job_id=?",
                           (self.clock().isoformat(), row['job_id']))
                self.store.event(db, row['job_id'], 'running', self.clock().isoformat())
            work = None
            publishing = False

            def publish_capture(output, capture_workspace=None):
                nonlocal publishing
                output = Path(output)
                if output.is_symlink() or not stat.S_ISREG(output.stat().st_mode):
                    raise ValueError('invalid_output')
                if capture_workspace is None:
                    if work is None or (work / 'output').is_symlink() or output.resolve().parent != work.resolve() / 'output':
                        raise ValueError('invalid_output')
                else:
                    capture_workspace = Path(capture_workspace)
                    capture_root = (self.root / '.staging' / 'capture-work').resolve(strict=True)
                    if (capture_workspace.is_symlink() or not capture_workspace.resolve(strict=True).is_relative_to(capture_root)
                            or output.resolve().parent != capture_workspace.resolve(strict=True)):
                        raise ValueError('invalid_output')
                audio_info(output, expected)
                if eligibility(row['broadcast'], self.clock()):
                    raise ValueError('expired_before_publish')
                if self.preflight:
                    self.preflight(row)  # Native/file conflicts appearing during capture also block publication.
                publishing = True
                manifest = self.publisher.publish(row, output, expected)
                self.completed(row, manifest)

            try:
                job_id(row['job_id'])
                problem = eligibility(row['broadcast'], self.clock())
                if problem:
                    self.failed(row, 'expired' if problem == 'expired' else 'failed', problem)
                    return row['job_id']
                if self.preflight:
                    self.preflight(row)
                elif self.transport.kind != 'fixture':
                    raise ValueError('preflight_required')
                # Last gate check immediately before any real capture transport.
                if self.transport.kind != 'fixture' and not timefree_gate():
                    raise ValueError('writes_disabled')
                expected = (datetime.fromisoformat(row['end_at']) - datetime.fromisoformat(row['start_at'])).total_seconds()
                capture_job = getattr(self.transport, 'capture_job', None)
                if callable(capture_job):
                    with capture_job(row['job_id']) as captured:
                        publish_capture(captured.audio_path, captured.workspace)
                else:
                    work = Path(tempfile.mkdtemp(prefix='work-', dir=self.root / '.staging'))
                    publish_capture(self.transport.run(row, work))
            except Exception as error:
                uncertain = publishing or isinstance(error, (subprocess.TimeoutExpired, FileExistsError))
                self.failed(row, 'unknown' if uncertain else 'failed',
                            getattr(error, 'code', 'worker_uncertain' if uncertain else 'worker_failed'))
            finally:
                if work is not None:
                    shutil.rmtree(work)
            return row['job_id']


def completed_assets(store, root, *, include_fixture=False):
    """Read-only integration boundary for the future recordings catalogue."""
    result = []
    for row in store.list():
        if row['state'] != 'completed' or (row['execution_kind'] == 'fixture' and not include_fixture):
            continue
        try:
            manifest = Publisher(root, store).verify(row)
            if manifest['relative_path'] != row['output_path'] or manifest['sha256'] != row['output_sha256'] or manifest['size'] != row['output_size']:
                continue
            result.append({'asset_id': row['job_id'], 'source': 'radioflix-timefree',
                           'broadcast_episode_id': row['broadcast_episode_id'],
                           'station': row['station'], 'title': row['title'],
                           'start_at': row['start_at'], 'end_at': row['end_at'],
                           'broadcast': row['broadcast'], 'relative_path': row['output_path'],
                           'duration': row['duration'], 'size': row['output_size'],
                           'completed_at': row['completed_at']})
        except (OSError, ValueError, TypeError, KeyError, EOFError, wave.Error):
            continue
    return result
