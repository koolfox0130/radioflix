"""One HTTP boundary, strict URL policy, a deterministic fake, and NotReady live port."""

import http.client
import ipaddress
import re
import socket
import ssl
import time
from typing import Protocol
from urllib.parse import unquote, urljoin, urlsplit

from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure, SourceNotReady
from radioflix.timefree.capture.source.models import (HttpRequest, HttpResponse,
    MAX_REQUEST_RESPONSE_BYTES, RetryPolicy, Secret)


ALLOWED_HOSTS = frozenset({
    'radiko.jp', 'api.radiko.jp', 'cdn.radiko.jp',
    'tf-f-rpaa-radiko.smartstream.ne.jp',
})
SMARTSTREAM_HOST = 'tf-f-rpaa-radiko.smartstream.ne.jp'
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 2
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
    if (not isinstance(request.max_response_bytes, int)
            or not 1 <= request.max_response_bytes <= MAX_REQUEST_RESPONSE_BYTES):
        raise SourceFailure(SourceCode.HTTP_REJECTED)


def auth_header(auth) -> Secret:
    credential = getattr(auth, 'credential', None)
    if not isinstance(credential, Secret):
        raise SourceFailure(SourceCode.AUTH_FAILED)
    return credential


class HttpTransport(Protocol):
    def request(self, request: HttpRequest) -> HttpResponse: ...


class ProductionHttpTransport:
    """Pinned-TLS HTTP transport, disabled except for an explicit bounded observation."""

    ready = False
    offline_fixture = False

    def __init__(self, *, observation_mode: bool = False, max_wire_requests: int = 0,
                 policy: RetryPolicy = RetryPolicy()):
        if observation_mode:
            if not 1 <= max_wire_requests <= 8:
                raise ValueError('invalid_observation_budget')
        elif max_wire_requests != 0:
            raise ValueError('observation_budget_requires_observation_mode')
        self.observation_mode = observation_mode
        self.max_wire_requests = max_wire_requests
        self.wire_requests = 0
        self.policy = policy

    @staticmethod
    def _public_addresses(host: str) -> tuple[str, ...]:
        try:
            results = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            addresses = tuple(dict.fromkeys(row[4][0] for row in results))
            if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
                raise ValueError
            return addresses
        except Exception:
            raise SourceFailure(SourceCode.HTTP_REJECTED) from None

    @staticmethod
    def _open_once(request: HttpRequest, url: str, address: str) -> HttpResponse:
        parsed = urlsplit(url)

        class PinnedHttpsConnection(http.client.HTTPSConnection):
            def connect(self):
                raw = socket.create_connection((address, 443), timeout=request.timeout.connect_seconds)
                self.sock = self._context.wrap_socket(raw, server_hostname=parsed.hostname)

        connection = PinnedHttpsConnection(
            parsed.hostname, port=443, timeout=request.timeout.connect_seconds,
            context=ssl.create_default_context(),
        )
        try:
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            headers = {
                name: value.reveal_for_transport() if isinstance(value, Secret) else value
                for name, value in request.headers.items()
            }
            connection.request('GET', path, headers=headers)
            if connection.sock is not None:
                connection.sock.settimeout(request.timeout.read_seconds)
            response = connection.getresponse()
            response_headers = {name: value for name, value in response.getheaders()}
            length = next((v for k, v in response_headers.items() if k.lower() == 'content-length'), None)
            if length is not None:
                if not length.isdecimal() or int(length) > request.max_response_bytes:
                    raise SourceFailure(SourceCode.INVALID_RESPONSE)
            body = bytearray()
            while True:
                block = response.read(min(64 * 1024, request.max_response_bytes + 1 - len(body)))
                if not block:
                    break
                body.extend(block)
                if len(body) > request.max_response_bytes:
                    raise SourceFailure(SourceCode.INVALID_RESPONSE)
            if length is not None and len(body) != int(length):
                raise SourceFailure(SourceCode.INVALID_RESPONSE)
            return HttpResponse(response.status, response_headers, bytes(body))
        except SourceFailure:
            raise
        except (TimeoutError, socket.timeout):
            raise SourceFailure(SourceCode.HTTP_TIMEOUT) from None
        except Exception:
            raise SourceFailure(SourceCode.HTTP_REJECTED) from None
        finally:
            connection.close()

    def request(self, request: HttpRequest) -> HttpResponse:
        validate_request(request)
        if not self.observation_mode:
            raise SourceNotReady()
        if request.method != 'GET' or request.body is not None:
            raise SourceFailure(SourceCode.HTTP_REJECTED)

        original_host = urlsplit(request.url).hostname
        current_url = request.url
        for attempt in range(self.policy.max_attempts):
            redirect_count = 0
            while True:
                if self.wire_requests >= self.max_wire_requests:
                    raise SourceNotReady()
                validate_url(current_url)
                current_host = urlsplit(current_url).hostname
                if current_host != original_host:
                    raise SourceFailure(SourceCode.HTTP_REJECTED)
                addresses = self._public_addresses(current_host)
                self.wire_requests += 1
                try:
                    response = self._open_once(request, current_url, addresses[0])
                except SourceFailure as error:
                    if error.code == SourceCode.HTTP_TIMEOUT and attempt + 1 < self.policy.max_attempts:
                        break
                    raise
                if 300 <= response.status < 400:
                    location = next((v for k, v in response.headers.items() if k.lower() == 'location'), None)
                    if location is None or redirect_count >= MAX_REDIRECTS:
                        raise SourceFailure(SourceCode.HTTP_REJECTED)
                    target = urljoin(current_url, location)
                    validate_url(target)
                    if urlsplit(target).hostname != original_host:
                        raise SourceFailure(SourceCode.HTTP_REJECTED)
                    current_url = target
                    redirect_count += 1
                    continue
                if response.status >= 500 and attempt + 1 < self.policy.max_attempts:
                    break
                if not 200 <= response.status < 300:
                    raise SourceFailure(SourceCode.HTTP_REJECTED)
                if redirect_count:
                    response = HttpResponse(response.status, response.headers, response.body, redirect_count)
                return response
        raise SourceFailure(SourceCode.HTTP_REJECTED)


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
            if len(response.body) > request.max_response_bytes:
                raise SourceFailure(SourceCode.INVALID_RESPONSE)
            return response
        raise SourceFailure(last or SourceCode.HTTP_REJECTED)
