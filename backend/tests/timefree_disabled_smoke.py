"""Read-only backend-to-worker UDS smoke for the isolated compose topology."""
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, '/app')
from radioflix.timefree.transport import UnixConnection


def request(method, path, body=None):
    connection = UnixConnection(os.getenv('RADIOFLIX_TIMEFREE_SOCKET', '/run/timefree/control.sock'))
    try:
        connection.request(method, path, json.dumps(body) if body is not None else None,
                           {'Content-Type': 'application/json'})
        response = connection.getresponse()
        payload = json.loads(response.read(4097))
        return response.status, payload
    finally:
        connection.close()


def main():
    socket_path = Path(os.getenv('RADIOFLIX_TIMEFREE_SOCKET', '/run/timefree/control.sock'))
    info = socket_path.stat(follow_symlinks=False)
    assert stat.S_ISSOCK(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o660
    assert info.st_uid == 10001 and info.st_gid == 20000

    status, health = request('GET', '/health')
    assert status == 200
    assert health == {'capture_ready': False, 'writes_enabled': False,
                      'boot_mode': 'disabled_read_only', 'reason': 'writes_disabled'}
    status, snapshot = request('GET', '/status')
    assert status == 200 and snapshot['job_count'] == 0
    status, result = request('POST', '/dispatch', {'job_id': '0' * 32})
    assert status == 409 and result == {'detail': {'code': 'writes_disabled'}}
    print('health=PASS status=PASS dispatch=blocked:writes_disabled socket=0660:10001:20000')


if __name__ == '__main__':
    main()
