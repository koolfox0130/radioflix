"""Bounded timefree playlist and HLS parser using only the injected transport."""

import json
import re
from urllib.parse import quote, urljoin

from radioflix.timefree.capture.models import PlaylistReference
from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.models import HttpRequest, RequestTimeout, bounded_timeout
from radioflix.timefree.capture.source.transport import HttpTransport, MAX_RESPONSE_BYTES, auth_header, validate_url


PLAYLIST_URL = 'https://api.radiko.jp/v2/api/ts/playlist'
MAX_PLAYLIST_BYTES = 256 * 1024
MAX_SEGMENTS = 2000


class TimefreePlaylistSource:
    def __init__(self, transport: HttpTransport, *, timeout: RequestTimeout = RequestTimeout()):
        self.transport, self.timeout = transport, timeout
        self.offline_fixture = bool(getattr(transport, 'offline_fixture', False))

    def resolve(self, metadata, auth, *, timeout_seconds=15) -> PlaylistReference:
        station = metadata.station
        if not re.fullmatch(r'[A-Z0-9]{3,8}', station):
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        start, end = metadata.start_at.strftime('%Y%m%d%H%M%S'), metadata.end_at.strftime('%Y%m%d%H%M%S')
        request = HttpRequest('GET', f'{PLAYLIST_URL}?station_id={quote(station)}&ft={start}&to={end}',
                              headers={'X-Radiko-AuthToken': auth_header(auth)},
                              timeout=bounded_timeout(self.timeout, timeout_seconds))
        try:
            response = self.transport.request(request)
            if len(response.body) > MAX_PLAYLIST_BYTES:
                raise SourceFailure(SourceCode.PLAYLIST_INVALID)
            data = json.loads(response.body.decode('utf-8'))
            url = validate_url(data['playlist_url'])
            return PlaylistReference(url, 'hls')
        except SourceFailure:
            raise
        except Exception:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID) from None

    def parse_hls(self, body: bytes, base_url: str) -> tuple[str, ...]:
        validate_url(base_url)
        if not isinstance(body, bytes) or not body or len(body) > MAX_PLAYLIST_BYTES:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        try:
            text = body.decode('utf-8-sig', errors='strict')
        except UnicodeDecodeError:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID) from None
        lines = [line.strip() for line in text.splitlines()]
        if not lines or lines[0] != '#EXTM3U' or len(lines) > MAX_SEGMENTS * 3:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        refs = []
        next_uri_tag = False
        for line in lines[1:]:
            if not line:
                continue
            if line.startswith('#EXT-X-KEY') or line.startswith('#EXT-X-MAP'):
                raise SourceFailure(SourceCode.PLAYLIST_INVALID)
            if line.startswith('#EXTINF:') or line.startswith('#EXT-X-STREAM-INF:'):
                next_uri_tag = True
                continue
            if line.startswith('#'):
                continue
            if not next_uri_tag:
                raise SourceFailure(SourceCode.PLAYLIST_INVALID)
            absolute = validate_url(urljoin(base_url, line))
            refs.append(absolute)
            if len(refs) > MAX_SEGMENTS or len(set(refs)) != len(refs):
                raise SourceFailure(SourceCode.PLAYLIST_INVALID)
            next_uri_tag = False
        if not refs:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        return tuple(refs)
