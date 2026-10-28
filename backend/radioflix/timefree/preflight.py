"""Read-only start/publication checks. Uncertain inventory always blocks capture."""
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from radioflix.schemas.reservations import Broadcast, JST
from radioflix.services.schedule_service import NativeReservations, overlaps
from radioflix.timefree.publisher import job_id


class StartBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


_RECORDING_NAME = re.compile(
    r'(?:(?P<marker>\[SHT\]))?'
    r'(?P<station>[A-Z0-9_-]+?)_(?P<title>.+)_'
    r'(?P<day>\d{8})_(?P<start>\d{4})_(?P<end>\d{4})'
    r'(?:_.*)?\.(?P<extension>m4a|mp3|aac|wav)'
)


def _parse_recording_name(name):
    """Parse only canonical names and the documented rfriends [SHT] marker."""
    if not isinstance(name, str) or '/' in name or '\\' in name or '\0' in name:
        return None
    match = _RECORDING_NAME.fullmatch(name)
    if not match:
        return None
    try:
        starts = datetime.strptime(match['day'] + match['start'], '%Y%m%d%H%M').replace(tzinfo=JST)
        ends = datetime.strptime(match['day'] + match['end'], '%Y%m%d%H%M').replace(tzinfo=JST)
    except ValueError:
        return None
    if ends <= starts:
        ends += timedelta(days=1)
    return match['station'], starts, ends


class RecordingInventory:
    # Known rfriends names only. Ambiguous audio fails closed; mtime/title alone
    # never prove absence or completion. No mutation and no media subprocesses.
    def __init__(self, roots):
        self.roots = [Path(p) for p in roots]

    def check(self, broadcast):
        if not self.roots:
            raise StartBlocked('recordings_unknown')
        for root in self.roots:
            if not root.is_dir() or root.absolute() != root.resolve():
                raise StartBlocked('recordings_unknown')
            def onerror(_):
                raise StartBlocked('recordings_unknown')
            for folder, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
                if any((Path(folder) / d).is_symlink() for d in dirs):
                    raise StartBlocked('recordings_unknown')
                for name in files:
                    path = Path(folder) / name
                    if path.suffix.lower() not in ('.m4a', '.mp3', '.aac', '.wav'):
                        continue
                    if path.is_symlink():
                        raise StartBlocked('recordings_unknown')
                    parsed = _parse_recording_name(name)
                    if parsed is None:
                        raise StartBlocked('recordings_unknown')
                    station, starts, ends = parsed
                    # Even incomplete/zero-byte matching files block a duplicate.
                    if station == broadcast.station and starts < broadcast.ends_at and broadcast.starts_at < ends:
                        raise StartBlocked('recording_exists')


class Preflight:
    def __init__(self, store, native_dir, recording_roots, managed_root=None):
        self.store = store
        self.managed_root = Path(managed_root) if managed_root else None
        self.native = NativeReservations(native_dir)
        self.inventory = RecordingInventory(recording_roots)

    def __call__(self, row):
        job_id(row['job_id'])
        current = self.store.get(row['job_id'])
        if not current or any(current[k] != row[k] for k in
                ('broadcast', 'broadcast_episode_id', 'station', 'start_at', 'end_at', 'execution_kind')):
            raise StartBlocked('metadata_changed')
        b = Broadcast.model_validate(row['broadcast'])
        canonical = hashlib.sha256(f'{b.station}:{b.starts_at.isoformat()}:{b.ends_at.isoformat()}'.encode()).hexdigest()
        if (b.id != canonical or row['broadcast_episode_id'] != b.id or row['station'] != b.station
                or row['start_at'] != b.starts_at.isoformat() or row['end_at'] != b.ends_at.isoformat()):
            raise StartBlocked('metadata_mismatch')
        stations = json.loads(row.get('station_ids', '[]'))
        if not isinstance(stations, list) or b.station not in stations or not all(isinstance(s, str) for s in stations):
            raise StartBlocked('native_unknown')
        native = self.native.snapshot(set(stations))
        if native is None or any(n.station is None for n in native):
            raise StartBlocked('native_unknown')
        if any(overlaps(b, n) for n in native):
            raise StartBlocked('native_conflict')
        self.inventory.check(b)
        jobs = self.store.list()
        if self.managed_root:
            if self.managed_root.is_symlink() or not self.managed_root.is_dir():
                raise StartBlocked('recordings_unknown')
            known = {j['job_id'] for j in jobs}
            for entry in self.managed_root.iterdir():
                if entry.name.startswith('.'):
                    continue
                if entry.is_symlink() or entry.name not in known:
                    raise StartBlocked('recordings_unknown')
                if entry.name == row['job_id']:
                    raise StartBlocked('output_collision')
        for other in jobs:
            if other['job_id'] == row['job_id'] or other['state'] in ('failed', 'expired', 'cancelled'):
                continue
            if other['broadcast_episode_id'] == b.id or overlaps(b, Broadcast.model_validate(other['broadcast'])):
                raise StartBlocked('duplicate_job')
        with sqlite3.connect(self.store.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'broadcasts' in tables:
                latest = db.execute('SELECT revision FROM broadcasts WHERE id=?', (b.id,)).fetchone()
                if latest and latest[0] != row['broadcast'].get('schedule_revision'):
                    raise StartBlocked('schedule_changed')
            if 'recording_jobs' in tables:
                for payload, state in db.execute('SELECT payload,state FROM recording_jobs'):
                    if state not in ('failed', 'cancelled', 'absent') and overlaps(b, Broadcast.model_validate(json.loads(payload))):
                        raise StartBlocked('radioflix_recording_conflict')
