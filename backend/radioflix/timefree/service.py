import os
import uuid
from datetime import datetime, timedelta, time

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


def live_gate():
    return os.getenv('RFRIENDS_ENABLE_WRITES') == '1' and os.getenv('RADIOFLIX_TIMEFREE_ENABLE_WRITES') == '1'


class TimefreeService:
    # Test-only constructor injection. No env/request can select mock execution.
    def __init__(self, store, schedule, *, clock=None, fixture=False, dispatcher=None, output_root=None):
        self.store, self.schedule, self.fixture = store, schedule, fixture
        self.clock = clock or (lambda: datetime.now(JST))
        self.writes_enabled = True  # Require existing Bearer auth even with all gates OFF.
        self.dispatcher = dispatcher
        self.output_root = output_root

    def dispatch_pending(self):
        if not self.dispatcher or not live_gate():
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
        if not self.fixture and not live_gate():
            raise RecordingError('writes_disabled', 'タイムフリー録音は無効です。')
        # Production transport is deliberately not installed by this offline milestone.
        if not self.fixture and (not self.dispatcher or not self.dispatcher.ready()):
            raise RecordingError('worker_unavailable', '隔離workerの本番受入が未完了です。')
        kind = 'fixture' if self.fixture else 'live'
        import json
        with self.store.transaction() as db:
            for old in db.execute("SELECT * FROM timefree_jobs WHERE state IN ('queued','running','completed','unknown')"):
                if old['broadcast_episode_id'] == b.id:
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
        self.dispatch_pending()
        return self.get(job_id)

    def cancel(self, job_id):
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
