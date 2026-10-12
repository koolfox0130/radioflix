"""Backend -> dedicated worker control, HTTP over a private Unix socket only."""
import http.client
import json
import socket

from radioflix.timefree.publisher import job_id
from radioflix.timefree.service import live_gate


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=3)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class WorkerClient:
    def __init__(self, socket_path):
        self.socket_path = str(socket_path)

    def request(self, method, path, body=None):
        connection = UnixConnection(self.socket_path)
        try:
            connection.request(method, path, json.dumps(body) if body is not None else None,
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = response.read(4097)
            if response.status not in (200, 202) or len(data) > 4096:
                raise ValueError('worker_unavailable')
            return json.loads(data)
        except (OSError, ValueError, http.client.HTTPException):
            raise ValueError('worker_unavailable') from None
        finally:
            connection.close()

    def ready(self):
        try:
            return self.request('GET', '/health').get('capture_ready') is True
        except ValueError:
            return False

    def dispatch(self, ident):
        job_id(ident)  # Reject injection before opening any socket.
        if not live_gate():
            return False
        response = self.request('POST', '/dispatch', {'job_id': ident})
        if response != {'job_id': ident, 'accepted': True}:
            raise ValueError('worker_unavailable')
        return True
