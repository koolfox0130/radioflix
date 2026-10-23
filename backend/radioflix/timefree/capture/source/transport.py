"""One HTTP boundary, strict URL policy, a deterministic fake, and NotReady live port."""

import ipaddress
import re
from typing import Protocol
from urllib.parse import unquote, urlsplit

from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure, SourceNotReady
from radioflix.timefree.capture.source.models import HttpRequest, HttpResponse, RetryPolicy, Secret


ALLOWED_HOSTS = frozenset({'radiko.jp', 'api.radiko.jp', 'cdn.radiko.jp'})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_HEADER = re.compile(r'^[!#$%&\'*+.^_`|~0-9A-Za-z-]+$')


def validate_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 32 for c in url):
        raise SourceFailure(SourceCode.HTTP_REJECTED)
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme != 'https' or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError
        try:
            ipaddress.ip_address(host.strip('[]'))
        except ValueError:
            pass
        else:
            raise ValueError
        if host not in ALLOWED_HOSTS:
            raise ValueError
        decoded_path = unquote(parsed.path)
        if any(part in ('.', '..') for part in decoded_path.split('/')) or '\\' in decoded_path:
            raise ValueError
        return url
    except Exception:
        raise SourceFailure(SourceCode.HTTP_REJECTED) from None


def validate_request(request: HttpRequest) -> None:
    if not isinstance(request, HttpRequest) or request.method not in {'GET', 'POST'}:
        raise SourceFailure(SourceCode.HTTP_REJECTED)
    validate_url(request.url)
    if len(request.headers) > 32:
        raise SourceFailure(SourceCode.HTTP_REJECTED)
    for name, value in request.headers.items():
        if not isinstance(name, str) or not _HEADER.fullmatch(name):
            raise SourceFailure(SourceCode.HTTP_REJECTED)
        raw = value.reveal_for_transport() if isinstance(value, Secret) else value
        if not isinstance(raw, str) or len(raw) > 4096 or '\r' in raw or '\n' in raw:
            raise SourceFailure(SourceCode.HTTP_REJECTED)
    if request.body is not None and (not isinstance(request.body, bytes) or len(request.body) > 64 * 1024):
        raise SourceFailure(SourceCode.HTTP_REJECTED)


def auth_header(auth) -> Secret:
    credential = getattr(auth, 'credential', None)
    if not isinstance(credential, Secret):
        raise SourceFailure(SourceCode.AUTH_FAILED)
    return credential


class HttpTransport(Protocol):
    def request(self, request: HttpRequest) -> HttpResponse: ...


class ProductionHttpTransport:
    """No socket/client is constructed here. Every production request fails closed."""

    ready = False
    offline_fixture = False

    def request(self, request: HttpRequest) -> HttpResponse:
        validate_request(request)
        raise SourceNotReady()


class FakeHttpTransport:
    """Scripted transport with no imports or calls to DNS, sockets, or HTTP libraries."""

    offline_fixture = True

    def __init__(self, responses: list[HttpResponse | BaseException], *, policy=RetryPolicy()):
        self._responses = list(responses)
        self.policy = policy
        self.requests: list[HttpRequest] = []

    def request(self, request: HttpRequest) -> HttpResponse:
        validate_request(request)
        self.requests.append(request)
        last = None
        for attempt in range(self.policy.max_attempts):
            if not self._responses:
                raise SourceFailure(SourceCode.HTTP_REJECTED)
            response = self._responses.pop(0)
            if isinstance(response, TimeoutError):
                last = SourceCode.HTTP_TIMEOUT
                if attempt + 1 < self.policy.max_attempts:
                    continue
                raise SourceFailure(last) from None
            if isinstance(response, Exception):
                raise SourceFailure(SourceCode.HTTP_REJECTED) from None
            if (not isinstance(response, HttpResponse) or not isinstance(response.status, int)
                    or not 100 <= response.status <= 599 or not isinstance(response.body, bytes)):
                raise SourceFailure(SourceCode.INVALID_RESPONSE)
            if response.status in (301, 302, 303, 307, 308):
                location = next((v for k, v in response.headers.items() if k.lower() == 'location'), '')
                validate_url(location)
                raise SourceFailure(SourceCode.HTTP_REJECTED)
            if response.status >= 500:
                last = SourceCode.HTTP_REJECTED
                if attempt + 1 < self.policy.max_attempts:
                    continue
                raise SourceFailure(last) from None
            if response.status < 200 or response.status >= 300:
                raise SourceFailure(SourceCode.HTTP_REJECTED)
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise SourceFailure(SourceCode.INVALID_RESPONSE)
            return response
        raise SourceFailure(last or SourceCode.HTTP_REJECTED)
