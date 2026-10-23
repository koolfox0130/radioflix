"""Authentication source contract. The current production implementation stays disabled."""

import json

from radioflix.timefree.capture.models import AuthContext
from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.models import HttpRequest, RequestTimeout, Secret, bounded_timeout
from radioflix.timefree.capture.source.transport import HttpTransport


AUTH_URL = 'https://api.radiko.jp/v2/api/auth1'


class RadikoAuthenticationSource:
    def __init__(self, transport: HttpTransport, *, credential: Secret | None = None,
                 timeout: RequestTimeout = RequestTimeout()):
        self.transport, self.credential, self.timeout = transport, credential, timeout
        self.offline_fixture = bool(getattr(transport, 'offline_fixture', False))

    def authenticate(self, metadata, *, timeout_seconds=15) -> AuthContext:
        if not isinstance(self.credential, Secret):
            raise SourceFailure(SourceCode.AUTH_FAILED)
        request = HttpRequest('POST', AUTH_URL, headers={
            'X-Radiko-Device': 'radioflix-fixture-client',
            'X-Radiko-User': 'dummy@example.invalid',
            'X-Radiko-AuthToken': self.credential,
        }, timeout=bounded_timeout(self.timeout, timeout_seconds))
        try:
            response = self.transport.request(request)
            data = json.loads(response.body.decode('utf-8'))
            token = data['auth_token']
            area = data.get('area_id', '')
            if not isinstance(token, str) or not token or len(token) > 4096 or not isinstance(area, str):
                raise ValueError
            return AuthContext(Secret(token), area)
        except SourceFailure as error:
            if error.code == SourceCode.HTTP_TIMEOUT:
                raise
            raise SourceFailure(SourceCode.AUTH_FAILED) from None
        except Exception:
            raise SourceFailure(SourceCode.AUTH_FAILED) from None
