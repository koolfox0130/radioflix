"""Capture-start policy and explicit one-target job admission CLI.

Importing the capture guard must not load the API or construct runtime services.
"""
import argparse
import json
import os
import stat
from datetime import datetime, timezone, timedelta
from pathlib import Path

from radioflix.timefree.contracts import CaptureAdmission, CaptureNotReady


def require_capture_start(state: CaptureAdmission) -> None:
    if (not isinstance(state, CaptureAdmission) or state.boot_mode != 'enabled'
            or state.timefree_writes is not True or state.ready is not True
            or state.bridge_approved is not True):
        raise CaptureNotReady()

def read_approval(path, request):
    path = Path(path)
    if not path.is_absolute() or path.absolute() != path.resolve(strict=True):
        raise ValueError('approval_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) not in (0o400, 0o600) or info.st_size > 2048):
            raise ValueError('approval_invalid')
        approval = json.loads(stream.read(2049))
    expected = {'broadcast_episode_id': request.broadcast_episode_id,
                'schedule_revision': request.schedule_revision, 'date': request.date.isoformat()}
    if (not isinstance(approval, dict) or set(approval) != {*expected, 'approved', 'expires_at'}
            or approval.get('approved') is not True
            or any(approval.get(k) != v for k, v in expected.items())):
        raise ValueError('approval_invalid')
    expires = datetime.fromisoformat(approval['expires_at'])
    now = datetime.now(timezone.utc)
    if expires.tzinfo is None or not now < expires <= now + timedelta(minutes=10):
        raise ValueError('approval_expired')
    return approval


def main(argv=None, *, service_factory=None):
    # CLI-only dependencies must not enter the capture policy import graph.
    from radioflix.api.timefree import TimefreeRequest
    from radioflix.timefree.service import TimefreeService
    from radioflix.timefree.store import TimefreeStore

    parser = argparse.ArgumentParser(description='Admit exactly one explicitly approved Timefree target.')
    parser.add_argument('--episode-id', required=True, type=lambda s: s if len(s) == 64 and all(c in '0123456789abcdef' for c in s) else parser.error('invalid episode id'))
    parser.add_argument('--schedule-revision', required=True, type=lambda s: s if len(s) == 64 and all(c in '0123456789abcdef' for c in s) else parser.error('invalid schedule revision'))
    parser.add_argument('--date', required=True)
    args = parser.parse_args(argv)
    try:
        request = TimefreeRequest(broadcast_episode_id=args.episode_id,
                                  schedule_revision=args.schedule_revision, date=args.date)
        approval = read_approval(os.environ['RADIOFLIX_TIMEFREE_ADMISSION_APPROVAL_FILE'], request)
        if service_factory is None:
            # The API's schedule/native validation graph is reused, while this
            # short-lived process owns a separately opened writable TimefreeStore.
            import app
            store = TimefreeStore(os.environ['RADIOFLIX_DB_PATH'], read_only=False)
            service = TimefreeService(store, app.schedule_service, dispatcher=None)
        else:
            service = service_factory()
        row = service.admit_for_acceptance(request, approval)
        print(json.dumps({'job_id': row['job_id'], 'state': row['state']}, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'state': 'rejected'}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
