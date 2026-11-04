import os
import uuid
from datetime import datetime, timedelta, time, timezone

from radioflix.schemas.reservations import Broadcast, JST, RecordingError
from radioflix.services.schedule_service import overlaps, native_uncertain

LABELS = {'queued': '録音待ち', 'running': '録音中…', 'completed': '録音済み',
          'failed': '録音失敗', 'expired': '期限切れ', 'cancelled': '取消済み', 'unknown': '録音状態確認待ち'}


def deadline(b):
    # rf_calc_radiodate/rf_diff_timefree: 05:00 boundary, [-7,0] radio days.
    day = (b.starts_at - timedelta(hours=5)).date()
    return datetime.combine(day + timedelta(days=8), time(5), JST)


def eligibility(item, now):
    b = Broadcast.model_validate(item)
    if now >= deadline(b):
        return 'expired'
    if now < b.ends_at + timedelta(seconds=120):
        return 'not_ready'
    metadata = item.get('metadata', {})
    if any(str(metadata.get(k)) != '0' for k in ('failed_record', 'ts_in_ng', 'ts_out_ng')):
        return 'restricted'
    return None


def timefree_gate():
    """Timefree writes are independent of native reservation writes."""
    return os.getenv('RADIOFLIX_TIMEFREE_ENABLE_WRITES') == '1'


class TimefreeService:
    # Test-only constructor injection. No env/request can select mock execution.
    def __init__(self, store, schedule, *, clock=None, fixture=False, dispatcher=None, output_root=None, acceptance_recording_roots=None):
        self.store, self.schedule, self.fixture = store, schedule, fixture
        self.clock = clock or (lambda: datetime.now(JST))
        self.writes_enabled = True  # Require existing Bearer auth even with all gates OFF.
        self.dispatcher = dispatcher
        self.output_root = output_root
        self.acceptance_recording_roots = (acceptance_recording_roots if acceptance_recording_roots is not None
                                           else ('/recordings', '/native-timefree'))

    def dispatch_pending(self):
        if not self.dispatcher or not timefree_gate():
            return
        for row in self.store.list():
            if row['state'] == 'queued' and row['execution_kind'] == 'live':
                try:
                    self.dispatcher.dispatch(row['job_id'])
                except ValueError:
                    return  # Durable DB queue survives backend/transport restarts.

    def list(self):
        rows = self.store.list()
        if self.output_root is not None:
            from radioflix.timefree.publisher import Publisher
            import wave
            publisher = Publisher(self.output_root, self.store)
            for row in rows:
                if row['state'] != 'completed':
                    continue
                try:
                    publisher.verify(row)
                except (OSError, ValueError, KeyError, TypeError, EOFError, wave.Error):
                    row.update(state='unknown', error_code='output_unverified',
                               error_message='保存済み音声を確認できません。')
        return rows

    def get(self, job_id):
        row = next((r for r in self.list() if r['job_id'] == job_id), None)
        if not row:
            raise RecordingError('not_found', '録音ジョブが見つかりません。')
        return row

    def create(self, request):
        return self._create(request, acceptance_approval=None)

    def admit_for_acceptance(self, request, approval):
        """Queue one explicitly approved live target without enabling API writes.

        The approval is target-bound and short-lived. The same schedule,
        eligibility, native-conflict and database admission logic used by the
        API remains authoritative; this path never dispatches a worker.
        """
        expected = {
            'broadcast_episode_id': request.broadcast_episode_id,
            'schedule_revision': request.schedule_revision,
            'date': request.date.isoformat(),
        }
        if (not isinstance(approval, dict) or set(approval) != {
                'broadcast_episode_id', 'schedule_revision', 'date', 'approved', 'expires_at'}
                or approval.get('approved') is not True
                or any(approval.get(k) != v for k, v in expected.items())):
            raise RecordingError('approval_invalid', '受入対象の承認を確認できません。')
        try:
            expires = datetime.fromisoformat(approval['expires_at'])
        except (TypeError, ValueError):
            raise RecordingError('approval_invalid', '受入対象の承認を確認できません。') from None
        now = datetime.now(timezone.utc)
        if expires.tzinfo is None or not now < expires <= now + timedelta(minutes=10):
            raise RecordingError('approval_expired', '受入対象の承認期限が切れています。')
        return self._create(request, acceptance_approval=approval)

    def preview_for_acceptance(self, request):
        """Same shared guards, no transaction, approval, dispatch or schema writes."""
        return self._create(request, acceptance_approval=None, preview=True)

    @staticmethod
    def _acceptance_jobs(b, rows):
        for old in rows:
            if old['broadcast_episode_id'] == b.id:
                # Recovery deliberately refuses even queued/failed/completed targets.
                raise RecordingError('duplicate', '既存jobを確認してください。自動再実行しません。')
            if old['execution_kind'] == 'live' and old['state'] in ('queued', 'running', 'unknown'):
                raise RecordingError('acceptance_busy', '別の受入jobがあります。')
            if old['station'] == b.station and old['start_at'] < b.ends_at.isoformat() and b.starts_at.isoformat() < old['end_at']:
                raise RecordingError('conflict', '同じ時間帯の録音ジョブがあります。')

    def _create(self, request, *, acceptance_approval, preview=False):
        acceptance = preview or acceptance_approval is not None
        self.schedule.validate_dates([request.date])
        stations = {s['id'] for s in self.schedule.adapter.stations()}
        day = self.schedule.adapter.day(request.date, fresh=True)
        item = next((b for b in day['broadcasts'] if b['id'] == request.broadcast_episode_id), None)
        if day['availability'] != 'ok' or not item or item['schedule_revision'] != request.schedule_revision:
            raise RecordingError('schedule_changed', '番組表を再読み込みしてください。')
        b = Broadcast.model_validate(item)
        if b.station not in stations:
            raise RecordingError('station', '放送局を確認できません。')
        problem = eligibility(item, self.clock())
        if problem:
            raise RecordingError(problem, {'expired': '期限切れです。', 'not_ready': '放送終了・配信準備を待ってください。',
                                          'restricted': '配信対象であることを確認できません。'}[problem])
        native = self.schedule.native_snapshot(self.schedule.reservations.list(), stations)
        if native is None or native_uncertain(b, native):
            raise RecordingError('native_unknown', '既存予約を確認できません。')
        if any(overlaps(b, n) for n in native):
            raise RecordingError('native_conflict', 'rfriends3で予約済みです。')
        if not self.fixture and not acceptance and not timefree_gate():
            raise RecordingError('writes_disabled', 'タイムフリー録音は無効です。')
        # Production transport is deliberately not installed by this offline milestone.
        if not self.fixture and not acceptance and (not self.dispatcher or not self.dispatcher.ready()):
            raise RecordingError('worker_unavailable', '隔離workerの本番受入が未完了です。')
        kind = 'fixture' if self.fixture else 'live'
        if acceptance:
            import hashlib
            from radioflix.timefree.preflight import RecordingInventory
            canonical = hashlib.sha256(f'{b.station}:{b.starts_at.isoformat()}:{b.ends_at.isoformat()}'.encode()).hexdigest()
            if b.id != canonical:
                raise RecordingError('metadata_mismatch', '番組identityが一致しません。')
            if not 0 < (b.ends_at - b.starts_at).total_seconds() <= 300:
                raise RecordingError('duration_limit', '受入対象の番組尺が上限を超えています。')
            RecordingInventory(self.acceptance_recording_roots).check(b)
            for reservation in self.schedule.reservations.list():
                if reservation['state'] not in ('cancelled', 'completed') and overlaps(b, Broadcast.model_validate(reservation['broadcast'])):
                    raise RecordingError('native_conflict', '通常予約と競合しています。')
            rows = self.store.list()
            self._acceptance_jobs(b, rows)
            if preview:
                return {'broadcast_episode_id': b.id, 'schedule_revision': item['schedule_revision'],
                        'date': request.date.isoformat(), 'station': b.station, 'title': b.title,
                        'start': b.starts_at.isoformat(), 'end': b.ends_at.isoformat(),
                        'duration': (b.ends_at - b.starts_at).total_seconds(),
                        'existing_job_count': len(rows), 'duplicate': False, 'native_conflict': False}
        import json
        with self.store.transaction() as db:
            if acceptance:
                self._acceptance_jobs(b, [self.store.decode(r) for r in db.execute('SELECT * FROM timefree_jobs')])
            rows = db.execute('SELECT * FROM timefree_jobs' if acceptance_approval is not None else
                "SELECT * FROM timefree_jobs WHERE state IN ('queued','running','completed','unknown')")
            for old in rows:
                if old['broadcast_episode_id'] == b.id:
                    if acceptance_approval is not None:
                        raise RecordingError('duplicate', '同じ番組のタイムフリーjobがあります。')
                    return self.store.decode(old)
                if old['station'] == b.station and old['start_at'] < b.ends_at.isoformat() and b.starts_at.isoformat() < old['end_at']:
                    raise RecordingError('conflict', '同じ時間帯の録音ジョブがあります。')
            job_id = uuid.uuid4().hex
            now = self.clock().isoformat()
            db.execute('''INSERT INTO timefree_jobs(job_id,broadcast_episode_id,station,title,start_at,end_at,state,
                created_at,snapshot,deadline,execution_kind,station_ids) VALUES (?,?,?,?,?,?,'queued',?,?,?,?,?)''',
                (job_id, b.id, b.station, b.title, b.starts_at.isoformat(), b.ends_at.isoformat(), now,
                 json.dumps(item, ensure_ascii=False), deadline(b).isoformat(), kind, json.dumps(sorted(stations))))
            self.store.event(db, job_id, 'queued', now)
        if acceptance_approval is None:
            self.dispatch_pending()
        return self.get(job_id)

    def cancel(self, job_id):
        if not self.fixture and not timefree_gate():
            raise RecordingError('writes_disabled', 'タイムフリー録音は無効です。')
        self.get(job_id)
        with self.store.transaction() as db:
            row = db.execute('SELECT state FROM timefree_jobs WHERE job_id=?', (job_id,)).fetchone()
            if row['state'] not in ('queued', 'cancelled'):
                raise RecordingError('busy', '開始済みの録音はこのAPIから取り消せません。')
            db.execute("UPDATE timefree_jobs SET state='cancelled' WHERE job_id=?", (job_id,))
            self.store.event(db, job_id, 'cancelled', self.clock().isoformat())
        return self.get(job_id)

    def project(self, item, jobs):
        b = Broadcast.model_validate(item)
        job = next((r for r in jobs if r['broadcast_episode_id'] == b.id), None)
        problem = eligibility(item, self.clock())
        state = job['state'] if job else problem or 'available'
        return {'timefree_state': state, 'timefree_label': LABELS.get(state, '録音' if state == 'available' else
                '配信準備待ち' if state == 'not_ready' else '対象外・確認不可'),
                'timefree_job_id': job['job_id'] if job else None,
                'timefree_enabled': bool(self.fixture and state == 'available')}
