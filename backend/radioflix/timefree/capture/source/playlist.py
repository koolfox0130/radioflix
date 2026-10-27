"""Timefree stream discovery and bounded HLS playlist parsing."""

import re
import secrets
import xml.etree.ElementTree as ET
from datetime import timezone, timedelta
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from radioflix.timefree.capture.models import PlaylistReference
from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.models import HttpRequest, RequestTimeout, bounded_timeout
from radioflix.timefree.capture.source.transport import (ALLOWED_HOSTS, HttpTransport,
    validate_url)


STREAM_XML_URL = 'https://radiko.jp/v3/station/stream/pc_html5/{station}.xml'
SMARTSTREAM_HOSTS = frozenset({
    'tf-f-rpaa-radiko.smartstream.ne.jp',
    'tf-c-rpaa-radiko.smartstream.ne.jp',
})
MAX_STREAM_XML_BYTES = 256 * 1024
MAX_PLAYLIST_BYTES = 256 * 1024
MAX_SEGMENTS = 2000
TIMEFREE_SEGMENT_SECONDS = 300
JST = timezone(timedelta(hours=9))


class TimefreePlaylistSource:
    """Resolve the station stream XML, then build its timefree GET URL.

    Normal pc_html5 capture currently supports areafree=0 only. The value is
    fixed into RadioFlix metadata; callers cannot supply a URL or alter it.
    """

    def __init__(self, transport: HttpTransport, *, timeout: RequestTimeout = RequestTimeout()):
        self.transport, self.timeout = transport, timeout
        self.offline_fixture = bool(getattr(transport, 'offline_fixture', False))
        self.candidate_diagnostics: tuple[dict, ...] = ()

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit('}', 1)[-1]

    @staticmethod
    def _check_station_identity(root: ET.Element, station: str) -> None:
        for element in root.iter():
            for key in ('station_id',):
                value = element.attrib.get(key)
                if value and value.upper() != station:
                    raise SourceFailure(SourceCode.PLAYLIST_INVALID)
            if TimefreePlaylistSource._local_name(element.tag) == 'station':
                value = element.attrib.get('id')
                if value and value.upper() != station:
                    raise SourceFailure(SourceCode.PLAYLIST_INVALID)

    def _selected_base(self, body: bytes, station: str, areafree: int) -> str:
        if (not body or len(body) > MAX_STREAM_XML_BYTES
                or b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper()):
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        try:
            root = ET.fromstring(body)
            TimefreePlaylistSource._check_station_identity(root, station)
        except SourceFailure:
            raise
        except (ET.ParseError, ValueError, UnicodeError):
            raise SourceFailure(SourceCode.PLAYLIST_INVALID) from None

        candidates = []
        for element in root.iter():
            if (TimefreePlaylistSource._local_name(element.tag) != 'url'
                    or element.attrib.get('timefree') != '1'
                    or element.attrib.get('areafree') != str(areafree)):
                continue
            values = [child.text.strip() for child in element.iter()
                      if TimefreePlaylistSource._local_name(child.tag) == 'playlist_create_url'
                      and child.text and child.text.strip()]
            candidate_index = len(candidates) + 1
            if len(values) != 1:
                candidates.append({
                    'index': candidate_index, 'timefree': '1', 'areafree': str(areafree),
                    'scheme': '', 'hostname': '', 'path': '', 'approved': False,
                })
                continue
            url = values[0]
            try:
                parsed = urlsplit(url)
                hostname = (parsed.hostname or '').lower().rstrip('.')
                path = parsed.path
                valid = validate_url(url)
                approved = (valid == url and parsed.scheme == 'https'
                            and hostname in SMARTSTREAM_HOSTS and hostname in ALLOWED_HOSTS
                            and path.startswith('/tf/') and not parsed.query
                            and not parsed.fragment)
            except Exception:
                parsed = None
                hostname, path, approved = '', '', False
            candidates.append({
                'index': candidate_index, 'timefree': '1', 'areafree': str(areafree),
                'scheme': parsed.scheme if parsed else '', 'hostname': hostname,
                'path': path, 'approved': bool(approved),
                'url': url if approved else None,
            })
        self.candidate_diagnostics = tuple({k: v for k, v in candidate.items() if k != 'url'}
                                           for candidate in candidates)
        selected = next((candidate for candidate in candidates if candidate.get('approved')), None)
        if selected is None:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        return selected['url']

    @staticmethod
    def _time(value) -> str:
        if not hasattr(value, 'tzinfo') or value.tzinfo is None:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        return value.astimezone(JST).strftime('%Y%m%d%H%M%S')

    def resolve(self, metadata, auth, *, timeout_seconds=15) -> PlaylistReference:
        station = getattr(metadata, 'station', None)
        areafree = getattr(metadata, 'areafree', 0)
        if (not isinstance(station, str) or not re.fullmatch(r'[A-Z0-9]{3,8}', station)
                or isinstance(areafree, bool) or areafree != 0):
            raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        try:
            start = self._time(metadata.start_at)
            end = self._time(metadata.end_at)
            duration = (metadata.end_at - metadata.start_at).total_seconds()
            if end <= start or not 0 < duration <= TIMEFREE_SEGMENT_SECONDS:
                raise SourceFailure(SourceCode.PLAYLIST_INVALID)
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise SourceFailure(SourceCode.PLAYLIST_INVALID) from None

        stream_url = STREAM_XML_URL.format(station=station)
        try:
            response = self.transport.request(HttpRequest(
                'GET', stream_url,
                timeout=bounded_timeout(self.timeout, timeout_seconds),
                max_response_bytes=MAX_STREAM_XML_BYTES,
            ))
        except SourceFailure:
            raise
        except Exception:
            raise SourceFailure(SourceCode.PLAYLIST_INVALID) from None
        if response.status != 200:
            raise SourceFailure(SourceCode.HTTP_REJECTED)
        base = self._selected_base(response.body, station, areafree)

        # Match rf_radiko_make_rectime_tf30(): one 300-second window, no
        # user-controlled URL/query fields, ordinary in-area type=b.
        params = [
            ('station_id', station), ('start_at', start), ('ft', start),
            ('end_at', end), ('to', end), ('preroll', '0'), ('seek', start),
            ('l', str(TIMEFREE_SEGMENT_SECONDS)),
            ('lsid', secrets.token_hex(16)), ('type', 'b'),
        ]
        parsed = urlsplit(base)
        playlist_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                   urlencode(params), ''))
        validate_url(playlist_url)
        # Authentication is attached to the playlist GET, never to a URL or log.
        return PlaylistReference(playlist_url, 'hls')

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
