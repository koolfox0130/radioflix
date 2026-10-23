"""Safe, structured source-stage errors. Never retain transport exception text."""

from enum import StrEnum


class SourceCode(StrEnum):
    AUTH_FAILED = 'AUTH_FAILED'
    HTTP_TIMEOUT = 'HTTP_TIMEOUT'
    HTTP_REJECTED = 'HTTP_REJECTED'
    INVALID_RESPONSE = 'INVALID_RESPONSE'
    PLAYLIST_INVALID = 'PLAYLIST_INVALID'
    MEDIA_FETCH_FAILED = 'MEDIA_FETCH_FAILED'
    SOURCE_NOT_READY = 'SOURCE_NOT_READY'


class SourceFailure(ValueError):
    def __init__(self, code: SourceCode):
        self.code = code
        super().__init__(code.value)


class SourceNotReady(SourceFailure):
    def __init__(self):
        super().__init__(SourceCode.SOURCE_NOT_READY)
