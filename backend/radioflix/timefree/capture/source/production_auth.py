"""Normal pc_html5 authentication source; transport remains independently gated."""

import base64
import re

from radioflix.timefree.capture.models import AuthContext
from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.full_key import extract_pc_html5_full_key
from radioflix.timefree.capture.source.models import HttpRequest, RequestTimeout, Secret, bounded_timeout
from radioflix.timefree.capture.source.transport import HttpTransport


PLAYER_JS_URL = 'https://radiko.jp/apps/js/playerCommon.js'
AUTH1_URL = 'https://radiko.jp/v2/api/auth1'
AUTH2_URL = 'https://radiko.jp/v2/api/auth2'
_PC_PROFILE = {
    'X-Radiko-App': 'pc_html5',
    'X-Radiko-App-Version': '0.0.1',
    'X-Radiko-Device': 'pc',
    'X-Radiko-User': 'dummy_user',
}
_MAX_AUTH_FIELD = 4096


def _header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


class ProductionAuthenticator:
    """Implements only ordinary pc_html5 auth; no premium/session inputs exist."""

    ready = False

    def __init__(self, transport: HttpTransport, *, timeout: RequestTimeout = RequestTimeout()):
        self.transport, self.timeout = transport, timeout

    def _request(self, method, url, headers, timeout_seconds):
        request = HttpRequest(
            method, url, headers=headers,
            timeout=bounded_timeout(self.timeout, timeout_seconds),
        )
        try:
            return self.transport.request(request)
        except SourceFailure as error:
            if error.code in (SourceCode.HTTP_TIMEOUT, SourceCode.SOURCE_NOT_READY):
                raise
            raise SourceFailure(SourceCode.AUTH_FAILED) from None
        except Exception:
            raise SourceFailure(SourceCode.AUTH_FAILED) from None

    def authenticate(self, metadata=None, *, timeout_seconds=15) -> AuthContext:
        # Metadata is intentionally unused: callers cannot select a URL, profile,
        # Premium mode, session, cookie, or auth endpoint.
        player = self._request('GET', PLAYER_JS_URL, {}, timeout_seconds)
        full_key = extract_pc_html5_full_key(player.body)

        auth1 = self._request('GET', AUTH1_URL, _PC_PROFILE, timeout_seconds)
        token = _header(auth1.headers, 'X-Radiko-AuthToken')
        offset_text = _header(auth1.headers, 'X-Radiko-KeyOffset')
        length_text = _header(auth1.headers, 'X-Radiko-KeyLength')
        if (not isinstance(token, str) or not token or len(token) > _MAX_AUTH_FIELD
                or not isinstance(offset_text, str) or not offset_text.isdecimal()
                or not isinstance(length_text, str) or not length_text.isdecimal()):
            raise SourceFailure(SourceCode.AUTH_FAILED)
        offset, length = int(offset_text), int(length_text)
        if length < 1 or length > _MAX_AUTH_FIELD or offset < 0 or offset + length > len(full_key):
            raise SourceFailure(SourceCode.AUTH_FAILED)

        partial_key = base64.b64encode(full_key[offset:offset + length]).decode('ascii')
        if not partial_key or len(partial_key) > _MAX_AUTH_FIELD:
            raise SourceFailure(SourceCode.AUTH_FAILED)
        auth2 = self._request('GET', AUTH2_URL, {
            'X-Radiko-Device': 'pc',
            'X-Radiko-User': 'dummy_user',
            'X-Radiko-AuthToken': Secret(token),
            'X-Radiko-PartialKey': Secret(partial_key),
        }, timeout_seconds)
        try:
            area = auth2.body.split(b',', 1)[0].decode('ascii', errors='strict').strip()
        except UnicodeDecodeError:
            raise SourceFailure(SourceCode.AUTH_FAILED) from None
        if not re.fullmatch(r'JP[0-9]{2}', area):
            raise SourceFailure(SourceCode.AUTH_FAILED)
        return AuthContext(Secret(token), area)
