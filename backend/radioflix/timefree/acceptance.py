"""Explicit one-job process; never creates a controller, scheduler or server."""
import argparse
import json
import os
import stat
from datetime import datetime, timezone, timedelta
from pathlib import Path

from radioflix.timefree.acceptance_profile import acceptance_worker
from radioflix.timefree.publisher import job_id
from radioflix.timefree.store import TimefreeStore


TERMINAL = frozenset({'completed', 'failed', 'cancelled', 'expired'})
EXIT_CODES = {'completed': 0, 'cancelled': 0, 'failed': 1, 'expired': 1, 'unknown': 3}


def approved_job(path, ident, *, now=None):
    """Read an operator-owned, short-lived approval for exactly this job.

    This is authorization for one invocation, not a gate/ready override. The
    file contains no credentials. Removing it prevents subsequent invocations;
    stopping a running process requires the documented interrupt procedure.
    """
    ident = job_id(ident)
    path = Path(path)
    if not path.is_absolute() or path.absolute() != path.resolve(strict=True):
        raise ValueError('approval_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) not in (0o400, 0o600) or info.st_size > 2048):
            raise ValueError('approval_invalid')
        data = json.loads(stream.read(2049))
    if (not isinstance(data, dict) or set(data) != {'job_id', 'approved', 'expires_at'}
            or data['job_id'] != ident or data['approved'] is not True):
        raise ValueError('approval_invalid')
    expires = datetime.fromisoformat(data['expires_at'])
    now = now or datetime.now(timezone.utc)
    if expires.tzinfo is None or not now < expires <= now + timedelta(minutes=30):
        raise ValueError('approval_expired')
    return True


def main(argv=None, *, worker_factory=acceptance_worker):
    parser = argparse.ArgumentParser(description=(
        'Process only the explicit existing Timefree job, then exit. No loop, '
        'discovery, new jobs or automatic capture retry. Existing terminal jobs are read-only no-ops.'))
    parser.add_argument('--accept-job', required=True, type=job_id, metavar='JOB_ID',
                        help='required 32-character lowercase hex job ID; never select another job')
    args = parser.parse_args(argv)
    ident = args.accept_job
    try:
        db_path = os.environ['RADIOFLIX_DB_PATH']
        # Read first: completed/unknown IDs never construct a capture stack.
        row = TimefreeStore(db_path, read_only=True).get(ident)
        if row is None:
            raise ValueError('job_not_found')
        if row['state'] in TERMINAL:
            state = row['state']
        else:
            approval = approved_job(os.environ['RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE'], ident)
            worker = worker_factory(ident=ident, bridge_approved=approval)
            # Fail closed if a caller accidentally constructed a different store.
            if worker.store.path.resolve() != Path(db_path).resolve():
                raise ValueError('store_mismatch')
            state = worker.accept_one(ident)
        print(json.dumps({'job_id': ident, 'state': state}, sort_keys=True))
        return EXIT_CODES.get(state, 3)
    except Exception:
        # Never print raw exceptions (paths, upstream responses, credentials).
        print(json.dumps({'job_id': ident, 'state': 'rejected'}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
