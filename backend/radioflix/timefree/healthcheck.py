"""Container health probe for the disabled, read-only worker mode."""
import json
import os
import sys

from radioflix.timefree.transport import UnixConnection


def main():
    path = os.getenv('RADIOFLIX_TIMEFREE_SOCKET', '/run/timefree/control.sock')
    connection = UnixConnection(path)
    try:
        connection.request('GET', '/health')
        response = connection.getresponse()
        payload = json.loads(response.read(4097))
    except Exception:
        return 1
    finally:
        connection.close()
    if (response.status != 200 or payload.get('boot_mode') != 'disabled_read_only' or
            payload.get('writes_enabled') is not False or payload.get('capture_ready') is not False or
            payload.get('reason') != 'writes_disabled'):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
