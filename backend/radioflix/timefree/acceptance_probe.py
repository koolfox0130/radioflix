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
    rows = store.list()
    row = store.get(ident)
    if len(rows) != 1 or row is None or row['execution_kind'] != 'live':
        raise ValueError('exactly_one_live_job_required')
    root = Path('/timefree')
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 10001 or info.st_gid != 20000 or stat.S_IMODE(info.st_mode) != 0o750:
        raise ValueError('publish_root_permissions')
    limits = row_budget(row)
    if not final:
        if row['state'] != 'queued' or eligibility(row['broadcast'], datetime.now(JST)):
            raise ValueError('job_not_eligible')
        Preflight(store, '/native-reservations', ['/recordings', '/native-timefree'], root)(row)
        if any(root.iterdir()):
            raise ValueError('publish_root_not_empty')
    elif row['state'] == 'completed':
        Publisher(root, store).verify(row)
        if len(list(root.glob('*/audio.wav'))) != 1:
            raise ValueError('output_count')
    elif list(root.glob('*/audio.wav')):
        raise ValueError('unexpected_output')
    return {'job_id': ident, 'state': row['state'], 'job_count': len(rows), 'limits': limits}


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
