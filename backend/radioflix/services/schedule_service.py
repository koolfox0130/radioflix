"""Guide projection and recording-folder-independent programme catalogue."""
import json
import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from radioflix.adapters.rfriends import weekly_title_key
from radioflix.schemas.reservations import Broadcast, JST, RecordingError


def overlaps(a, b):
    return (a.station == b.station and a.starts_at < b.ends_at and b.starts_at < a.ends_at)


class ProgramCatalog:
    def __init__(self, store, programs):
        self.store, self.programs = store, programs

    def find_program(self, program_id):
        old = self.programs.find_program(program_id)
        if old:
            return old
        if not self.store.path.exists():
            return None
        with sqlite3.connect(self.store.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if not db.execute("SELECT name FROM sqlite_master WHERE name='program_series'").fetchone():
                return None
            row = db.execute('''SELECT id,title,station FROM program_series WHERE id=?
                OR id IN (SELECT series_id FROM program_aliases WHERE program_id=?)''', (program_id, program_id)).fetchone()
        return {"id": program_id, "title": row[1], "raw_name": row[2] + '_' + row[1]} if row else None

    def save_revision(self, item):
        with self.store.locked() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS broadcast_revisions (
                id TEXT NOT NULL, revision TEXT NOT NULL, snapshot TEXT NOT NULL,
                PRIMARY KEY(id, revision));
                CREATE TABLE IF NOT EXISTS broadcasts (
                id TEXT PRIMARY KEY, station TEXT NOT NULL, starts_at TEXT NOT NULL,
                revision TEXT NOT NULL);""")
            db.execute('INSERT OR IGNORE INTO broadcast_revisions VALUES (?,?,?)',
                       (item['id'], item['schedule_revision'], json.dumps(item)))
            db.execute('INSERT OR REPLACE INTO broadcasts VALUES (?,?,?,?)',
                       (item['id'], item['station'], item['starts_at'], item['schedule_revision']))
            db.commit()

    def resolve(self, b):
        with self.store.locked() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS program_series (
                id TEXT PRIMARY KEY, station TEXT NOT NULL, title TEXT NOT NULL,
                title_key TEXT NOT NULL, weekday INTEGER NOT NULL, anchor TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS program_aliases (
                program_id TEXT PRIMARY KEY, series_id TEXT NOT NULL REFERENCES program_series(id));
                CREATE UNIQUE INDEX IF NOT EXISTS series_anchor ON program_series(station,title_key,weekday,anchor);''')
            key = (b.station, weekly_title_key(b.title), b.starts_at.weekday(), b.starts_at.strftime('%H:%M:%S'))
            rows = db.execute('SELECT id,title FROM program_series WHERE station=? AND title_key=? AND weekday=? AND anchor=?', key).fetchall()
            if rows:
                sid = rows[0]['id']
            else:
                sid = 'series-' + uuid.uuid4().hex
                db.execute('INSERT INTO program_series VALUES (?,?,?,?,?,?)', (sid, b.station, b.title, *key[1:]))
            # Only unambiguous legacy matches become aliases; never invent a folder.
            matches = [p for p in self.programs.get_all_programs()
                       if p.get('raw_name', '').startswith(b.station + '_') and weekly_title_key(p['title']) == key[1]]
            if len(matches) == 1:
                db.execute('INSERT OR IGNORE INTO program_aliases VALUES (?,?)', (matches[0]['id'], sid))
                alias = db.execute('SELECT series_id FROM program_aliases WHERE program_id=?', (matches[0]['id'],)).fetchone()
                if alias['series_id'] == sid:
                    sid = matches[0]['id']
            db.commit()
        return {'id': sid, 'title': b.title, 'raw_name': b.station + '_' + b.title}


@dataclass(frozen=True)
class NativeReservation:
    id: str
    raw_station: str
    station: str | None
    starts_at: datetime
    ends_at: datetime

    @property
    def station_state(self):
        return 'unknown' if self.station is None else 'known'


def native_station(raw, known_stations=None):
    # rfriends3 config_sys_10.php + rf_radiru.php get_radiru_callsign.
    # radiru_rsv_ex_s_fmt1/fmt2 omit the area suffix for Tokyo and r2.
    callsigns = {'tokyo': 'JOAK', 'sendai': 'JOHK', 'nagoya': 'JOCK',
                 'osaka': 'JOBK', 'sapporo': 'JOIK', 'hiroshima': 'JOFK',
                 'matsuyama': 'JOZK', 'fukuoka': 'JOLK'}
    channel, separator, area = raw.partition('_')
    if separator and not area:
        return None
    if channel == 'r2' and (not area or area in callsigns):
        return 'JOAB'
    if channel in ('r1', 'r3') and (area or 'tokyo') in callsigns:
        return callsigns[area or 'tokyo'] + ('-FM' if channel == 'r3' else '')
    if re.fullmatch(r'[A-Z0-9_-]{1,24}', raw) and (known_stations is None or raw in known_stations):
        return raw
    return None


def native_uncertain(broadcast, native):
    return native is not None and any(n.station is None and
        broadcast.starts_at < n.ends_at and n.starts_at < broadcast.ends_at for n in native)


class NativeReservations:
    """Optional read-only .dat snapshot directory. No PHP, locks or inspect calls."""
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else None

    def snapshot(self, known_stations=None):
        if not self.directory:
            return None
        try:
            if not self.directory.is_dir():
                return None
            items = []
            for path in self.directory.iterdir():
                if path.suffix != '.dat':
                    continue
                if path.is_symlink() or path.stat().st_size > 65536:
                    return None
                fields = path.read_text().strip().split(' ')
                if len(fields) < 7:
                    return None
                station = native_station(fields[6], known_stations)
                # Keep the public Broadcast schema strict; validate native dates
                # independently of an unrecognised station identifier.
                timing = Broadcast(id=path.stem, station=station or 'UNKNOWN', title='native',
                    starts_at=datetime.strptime(fields[0], '%Y%m%d%H%M%S').replace(tzinfo=JST),
                    ends_at=datetime.strptime(fields[1], '%Y%m%d%H%M%S').replace(tzinfo=JST))
                items.append(NativeReservation(path.stem, fields[6], station, timing.starts_at, timing.ends_at))
            unknown = sum(n.station is None for n in items)
            if unknown:
                logging.getLogger(__name__).warning('native reservation unknown station count=%d', unknown)
            return items
        except (OSError, ValueError):
            return None


class ScheduleService:
    def __init__(self, adapter, reservations, catalog, native=None, clock=None):
        self.adapter, self.reservations, self.catalog = adapter, reservations, catalog
        self.native = native or NativeReservations()
        self.clock = clock or reservations.clock

    def validate_dates(self, dates):
        today = (self.clock() - timedelta(hours=5)).date()
        if not dates or len(dates) > 15 or any(abs((d - today).days) > 7 for d in dates):
            raise RecordingError('date_range', '日付は放送日の過去7日〜未来7日で指定してください。')

    def native_snapshot(self, rows, stations):
        native = self.native.snapshot(stations)
        if native is None:
            return None
        owned = {j['external_ref'].get('name') for r in rows for j in r['jobs']
                 if j.get('external_ref') and j['state'] in ('scheduled', 'running')}
        return [n for n in native if n.id not in owned or n.station is None]

    def status(self, item, reservations, subscriptions, native):
        b = Broadcast.model_validate(item)
        row = next((r for r in reservations if r['state'] not in ('cancelled', 'completed')
                    and overlaps(b, Broadcast.model_validate(r['broadcast']))), None)
        state, label = 'unreserved', '未予約'
        if row:
            state = row['state']
            label = {'active': '毎週録音中' if row.get('subscription_id') else '今回のみ予約済み',
                     'waiting_write': '書き込み無効・予約待機', 'stale': '予約状態の確認待ち',
                     'create_failed': '予約登録失敗', 'create_unknown': '予約結果不明'}.get(state, '予約処理中')
            if row.get('message'):
                label += '：' + row['message']
        else:
            sub = next((s for s in subscriptions if s['state'] == 'active' and s['station'] == b.station
                        and s['title_key'] == weekly_title_key(b.title) and s['anchor_weekday'] == b.starts_at.weekday()
                        and abs((datetime.combine(b.starts_at.date(), datetime.strptime(s['anchor_time'], '%H:%M:%S').time(), JST) - b.starts_at).total_seconds()) <= 7200), None)
            if sub:
                state, label = 'weekly', ('毎週録音中' if sub['schedule_state'] == 'scheduled' else '毎週録音・次回確認待ち')
        uncertain = native_uncertain(b, native)
        if uncertain:
            state, label = 'native_unknown', '同時間帯の既存予約の放送局を確認できないため予約できません。'
        if native is not None and any(overlaps(b, n) for n in native):
            state, label = 'native_conflict', 'rfriends3で予約済み（変更不可）'
        future = b.starts_at > self.clock() + timedelta(minutes=3)
        return {**item, 'reservation_state': state, 'reservation_label': label,
                'recording_state': 'unknown', 'native_state': 'unknown' if native is None or uncertain else
                    'partial' if any(n.station is None for n in native) else 'checked',
                'allowed_actions': ['once', 'weekly'] if future and state == 'unreserved' else [],
                'timefree_message': 'タイムフリー録音は準備中' if b.starts_at <= self.clock() else ''}

    def schedule(self, station, dates):
        self.validate_dates(dates)
        stations = self.adapter.stations()
        if station and station not in {s['id'] for s in stations}:
            raise RecordingError('station', '放送局を確認してください。')
        rows, subs = self.reservations.list(), self.reservations.list_subscriptions()
        native = self.native_snapshot(rows, {s['id'] for s in stations})
        days = []
        for source in self.adapter.days(dates):
            day = {**source}
            day['broadcasts'] = [self.status(b, rows, subs, native) for b in source['broadcasts'] if not station or b['station'] == station]
            if day['availability'] == 'ok' and not day['broadcasts']:
                day['availability'] = 'station_missing'
            days.append(day)
        successes = sum(d['availability'] == 'ok' for d in days)
        return {'days': days, 'availability': 'ok' if successes == len(days) else 'partial' if successes else 'unavailable',
                'today': (self.clock() - timedelta(hours=5)).date().isoformat(), 'writes_enabled': self.reservations.writes_enabled}

    def reserve(self, bid, request):
        self.validate_dates([request.date])
        stations = {s['id'] for s in self.adapter.stations()}
        day = self.adapter.day(request.date, fresh=True)
        item = next((b for b in day['broadcasts'] if b['id'] == bid), None)
        if day['availability'] != 'ok' or not item or item['schedule_revision'] != request.schedule_revision:
            raise RecordingError('schedule_changed', '番組表が変更されたか取得できません。再読み込みしてください。')
        b = Broadcast.model_validate(item)
        if b.station not in stations:
            raise RecordingError('station', '放送局を確認してください。')
        if b.starts_at <= self.clock() + timedelta(minutes=3):
            raise RecordingError('too_late', '開始3分前を過ぎたため予約できません。タイムフリー録音は準備中です。')
        native = self.native_snapshot(self.reservations.list(), stations)
        if native is not None and any(overlaps(b, n) for n in native):
            raise RecordingError('conflict', 'rfriends3で予約済みです。既存予約は変更していません。')
        if native_uncertain(b, native) or (self.reservations.writes_enabled and native is None):
            raise RecordingError('native_unknown', '既存予約を確認できないため操作を停止しました。')
        self.catalog.save_revision(item)
        return self.reservations.create(self.catalog.resolve(b), b, request.mode)
