"""Typed source transport values with redacted credentials and payloads."""

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Secret:
    _value: str = field(repr=False)

    def reveal_for_transport(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return 'Secret(<redacted>)'

    __str__ = __repr__


@dataclass(frozen=True)
class RequestTimeout:
    connect_seconds: float = 3.0
    read_seconds: float = 10.0

    def __post_init__(self):
        if not (0 < self.connect_seconds <= 15 and 0 < self.read_seconds <= 60):
            raise ValueError('invalid_timeout')


def bounded_timeout(config: RequestTimeout, remaining_seconds: float) -> RequestTimeout:
    if not isinstance(remaining_seconds, (int, float)) or remaining_seconds <= 0:
        from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
        raise SourceFailure(SourceCode.HTTP_TIMEOUT)
    return RequestTimeout(min(config.connect_seconds, remaining_seconds),
                          min(config.read_seconds, remaining_seconds))


@dataclass(frozen=True, repr=False)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str | Secret] = field(default_factory=dict, repr=False)
    body: bytes | None = field(default=None, repr=False)
    timeout: RequestTimeout = field(default_factory=RequestTimeout)

    def __repr__(self) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(self.url)
        return f'HttpRequest(method={self.method!r}, host={parsed.hostname!r}, path={parsed.path!r}, body=<redacted>)'


@dataclass(frozen=True, repr=False)
class HttpResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    body: bytes = field(default=b'', repr=False)

    def __repr__(self) -> str:
        return f'HttpResponse(status={self.status}, headers=<redacted>, body=<redacted>)'


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3

    def __post_init__(self):
        if not 1 <= self.max_attempts <= 5:
            raise ValueError('invalid_retry_limit')
