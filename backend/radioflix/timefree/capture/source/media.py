"""HLS media fetch source. Writes only to a caller-provided adapter workspace file."""

import os
import tempfile
import time
from pathlib import Path

from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.models import HttpRequest, RequestTimeout, bounded_timeout
from radioflix.timefree.capture.source.playlist import TimefreePlaylistSource
from radioflix.timefree.capture.source.transport import (HttpTransport, MAX_RESPONSE_BYTES,
                                                         auth_header, validate_url)


MAX_SEGMENT_BYTES = 16 * 1024 * 1024


class HlsMediaSource:
    def __init__(self, transport: HttpTransport, playlist_parser: TimefreePlaylistSource,
                 *, work_root: Path, timeout: RequestTimeout = RequestTimeout()):
        self.transport, self.playlist_parser, self.timeout = transport, playlist_parser, timeout
        self.work_root = Path(work_root)
        self.offline_fixture = bool(getattr(transport, 'offline_fixture', False))

    def download(self, playlist, auth, destination: Path, *, timeout_seconds=60) -> Path:
        destination = Path(destination)
        try:
            if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
                raise SourceFailure(SourceCode.HTTP_TIMEOUT)
            deadline = time.monotonic() + timeout_seconds
            root = self.work_root.resolve(strict=True)
            parent = destination.parent.resolve(strict=True)
            if (destination.name != 'media-input.ts' or not parent.is_relative_to(root)
                    or destination.exists() or destination.is_symlink()):
                raise ValueError
        except Exception:
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        try:
            playlist_url = validate_url(playlist.url)
            master = self.transport.request(HttpRequest('GET', playlist_url,
                headers={'X-Radiko-AuthToken': auth_header(auth),
                         'X-Radiko-AreaId': auth.area_id},
                timeout=bounded_timeout(self.timeout, deadline - time.monotonic())))
            if master.status != 200:
                raise SourceFailure(SourceCode.HTTP_REJECTED)
            segments = self.playlist_parser.parse_hls(master.body, playlist_url)
            if b'#EXT-X-STREAM-INF:' in master.body:
                if len(segments) != 1:
                    raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
                variant = segments[0]
                media_playlist = self.transport.request(HttpRequest('GET', variant,
                    headers={'X-Radiko-AuthToken': auth_header(auth),
                             'X-Radiko-AreaId': auth.area_id},
                    timeout=bounded_timeout(self.timeout, deadline - time.monotonic())))
                if media_playlist.status != 200:
                    raise SourceFailure(SourceCode.HTTP_REJECTED)
                if b'#EXT-X-ENDLIST' not in media_playlist.body:
                    raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
                segments = self.playlist_parser.parse_hls(media_playlist.body, variant)
            elif b'#EXT-X-ENDLIST' not in master.body:
                raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
            fd, name = tempfile.mkstemp(prefix='.source-', dir=destination.parent)
            temp = Path(name)
            total = 0
            try:
                with os.fdopen(fd, 'wb') as output:
                    for segment in segments:
                        request_timeout = bounded_timeout(self.timeout, deadline - time.monotonic())
                        response = self.transport.request(HttpRequest('GET', validate_url(segment),
                            headers={'X-Radiko-AuthToken': auth_header(auth),
                                     'X-Radiko-AreaId': auth.area_id}, timeout=request_timeout))
                        if not response.body or len(response.body) > MAX_SEGMENT_BYTES:
                            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
                        total += len(response.body)
                        if total > MAX_RESPONSE_BYTES:
                            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
                        output.write(response.body)
                    output.flush()
                    os.fsync(output.fileno())
                os.link(temp, destination)
                return destination
            finally:
                temp.unlink(missing_ok=True)
        except SourceFailure:
            raise
        except Exception:
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED) from None
