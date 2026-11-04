"""Network-free read-only host-runner probe; no schema migration or recovery."""
import argparse
import json
import os
import stat
from pathlib import Path
from datetime import datetime

from radioflix.schemas.reservations import JST
from radioflix.timefree.acceptance_profile import row_budget
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.publisher import job_id, Publisher
from radioflix.timefree.service import eligibility
from radioflix.timefree.store import TimefreeStore


def inspect_job(ident, *, final=False):
    store = TimefreeStore('/data/radioflix.sqlite3', read_only=True)
    root = Path('/timefree')
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 10001 or info.st_gid != 20000 or stat.S_IMODE(info.st_mode) != 0o750:
        raise ValueError('publish_root_permissions')
    guard = Preflight(store, '/native-reservations', ['/recordings', '/native-timefree'], root)
    return inspect_state(ident, store, root, guard, datetime.now(JST), final=final)


def inspect_state(ident, store, root, guard, now, *, final=False):
    rows = store.list()
    row = store.get(ident)
    if row is None or row['execution_kind'] != 'live':
        raise ValueError('exactly_one_live_job_required')
    if any(r['job_id'] != ident and r['execution_kind'] == 'live' and
           r['state'] in ('queued', 'running', 'unknown') for r in rows):
        raise ValueError('other_active_acceptance_job')
    limits = row_budget(row)
    if not final:
        if row['state'] != 'queued' or eligibility(row['broadcast'], now):
            raise ValueError('job_not_eligible')
        guard(row)
        if (root / ident).exists():
            raise ValueError('output_collision')
    elif row['state'] == 'completed':
        Publisher(root, store).verify(row)
        if not (root / ident / 'audio.wav').is_file():
            raise ValueError('output_count')
    elif (root / ident / 'audio.wav').exists():
        raise ValueError('unexpected_output')
    return {'job_id': ident, 'state': row['state'], 'job_count': len(rows), 'limits': limits,
            'broadcast_episode_id': row['broadcast_episode_id'],
            'schedule_revision': row['broadcast']['schedule_revision'],
            'output_count': int((root / ident / 'audio.wav').is_file()),
            'published_count': int(store.publication(ident) is not None)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--job', required=True, type=job_id)
    p.add_argument('--final', action='store_true')
    args = p.parse_args()
    try:
        print(json.dumps(inspect_job(args.job, final=args.final), sort_keys=True))
        return 0
    except Exception:
        print('{"error":"acceptance_preflight_failed"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
