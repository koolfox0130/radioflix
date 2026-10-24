"""Observation-only bounded HLS segment fetcher; never assembles a program."""

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure
from radioflix.timefree.capture.source.models import (HttpRequest, RequestTimeout,
    bounded_timeout)
from radioflix.timefree.capture.source.playlist import MAX_PLAYLIST_BYTES, TimefreePlaylistSource
from radioflix.timefree.capture.source.transport import (HttpTransport, SMARTSTREAM_HOST,
    auth_header, validate_url)


MAX_PRODUCTION_SEGMENTS = 3
MAX_SEGMENT_BYTES = 16 * 1024 * 1024
_PLAYLIST_TYPES = frozenset({'application/x-mpegurl', 'application/vnd.apple.mpegurl',
                             'audio/mpegurl', 'application/mpegurl'})
_SEGMENT_TYPES = frozenset({'audio/aac', 'audio/mp4', 'video/mp2t', 'video/mp4',
                            'application/octet-stream'})


@dataclass(frozen=True, repr=False)
class SegmentArtifact:
    path: Path
    status: int
    content_type: str
    byte_size: int
    elapsed_seconds: float
    media_format: str

    def __repr__(self) -> str:
        return (f'SegmentArtifact(status={self.status}, content_type={self.content_type!r}, '
                f'byte_size={self.byte_size}, elapsed_seconds={self.elapsed_seconds:.3f}, '
                f'media_format={self.media_format!r})')


class ProductionMediaFetcher:
    """Fetch at most three segments into an existing job-specific workspace.

    This stage is deliberately not ready for worker use. Its default transport is
    also network-disabled; the bounded observation mode exists only for an
    explicitly constructed, short-lived diagnostic.
    """

    ready = False

    def __init__(self, transport: HttpTransport, parser: TimefreePlaylistSource,
                 *, work_root: Path, timeout: RequestTimeout = RequestTimeout()):
        self.transport, self.parser, self.timeout = transport, parser, timeout
        self.work_root = Path(work_root)
        self.last_manifest_info: tuple[int, str, int, int] | None = None

    def fetch_segments(self, media_manifest_url: str, auth, workspace: Path, *,
                       max_segments: int = 1, timeout_seconds: float = 30) -> tuple[SegmentArtifact, ...]:
        if isinstance(max_segments, bool) or not isinstance(max_segments, int) or not 1 <= max_segments <= MAX_PRODUCTION_SEGMENTS:
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise SourceFailure(SourceCode.HTTP_TIMEOUT)
        try:
            root = self.work_root.resolve(strict=True)
            directory = Path(workspace)
            resolved = directory.resolve(strict=True)
            manifest_url = validate_url(media_manifest_url)
            parsed = urlsplit(manifest_url)
            if (not directory.is_dir() or directory.is_symlink() or not resolved.is_relative_to(root)
                    or parsed.hostname != SMARTSTREAM_HOST or not parsed.path.startswith('/tf/')):
                raise ValueError
        except Exception:
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED) from None

        deadline = time.monotonic() + timeout_seconds
        saved: list[Path] = []
        artifacts: list[SegmentArtifact] = []
        try:
            manifest = self.transport.request(HttpRequest(
                'GET', manifest_url, headers={
                    'X-Radiko-AreaId': auth.area_id,
                    'X-Radiko-AuthToken': auth_header(auth),
                },
                timeout=bounded_timeout(self.timeout, deadline - time.monotonic()),
                max_response_bytes=MAX_PLAYLIST_BYTES,
            ))
            content_type = _content_type(manifest.headers)
            self.last_manifest_info = (manifest.status, content_type, len(manifest.body), manifest.redirect_count)
            if manifest.status != 200 or content_type not in _PLAYLIST_TYPES or b'#EXT-X-STREAM-INF:' in manifest.body:
                raise SourceFailure(SourceCode.PLAYLIST_INVALID)
            # Radiko may return a sliding timefree media window without ENDLIST.
            # Only the caller-bounded prefix is ever fetched; the manifest is never polled.
            segments = self.parser.parse_hls(manifest.body, manifest_url)
            manifest_parts = urlsplit(manifest_url)
            manifest_dir = manifest_parts.path.rsplit('/', 1)[0] + '/'
            for index, segment_url in enumerate(segments[:max_segments], start=1):
                segment_url = validate_url(segment_url)
                segment_parts = urlsplit(segment_url)
                if (segment_parts.hostname != SMARTSTREAM_HOST
                        or not segment_parts.path.startswith(manifest_dir)):
                    raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
                started = time.monotonic()
                response = self.transport.request(HttpRequest(
                    'GET', segment_url, headers={
                        'X-Radiko-AreaId': auth.area_id,
                        'X-Radiko-AuthToken': auth_header(auth),
                    },
                    timeout=bounded_timeout(self.timeout, deadline - time.monotonic()),
                    max_response_bytes=MAX_SEGMENT_BYTES,
                ))
                media_type = _content_type(response.headers)
                if response.status != 200:
                    raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
                media_format = _validate_segment(response.body, media_type)
                target = resolved / f'segment-{index:03d}.bin'
                if target.exists() or target.is_symlink():
                    raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
                fd, temp_name = tempfile.mkstemp(prefix='.segment-', dir=resolved)
                temp = Path(temp_name)
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(response.body)
                        output.flush()
                        os.fsync(output.fileno())
                    os.link(temp, target)
                    saved.append(target)
                    artifacts.append(SegmentArtifact(
                        target, response.status, media_type, len(response.body),
                        time.monotonic() - started, media_format,
                    ))
                finally:
                    temp.unlink(missing_ok=True)
            if not saved:
                raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
            return tuple(artifacts)
        except SourceFailure:
            for path in saved:
                path.unlink(missing_ok=True)
            raise
        except Exception:
            for path in saved:
                path.unlink(missing_ok=True)
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED) from None


def _content_type(headers) -> str:
    return next((value.split(';', 1)[0].strip().lower()
                 for key, value in headers.items() if key.lower() == 'content-type'), '')


def _validate_segment(body: bytes, content_type: str) -> str:
    if not isinstance(body, bytes) or not body or len(body) > MAX_SEGMENT_BYTES or content_type not in _SEGMENT_TYPES:
        raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
    if content_type == 'video/mp2t' or body.startswith(b'G'):
        if len(body) < 188 or body[0] != 0x47:
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        if any(body[offset] != 0x47 for offset in range(188, len(body), 188)):
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        return 'mpeg-ts'
    if content_type in ('audio/aac', 'application/octet-stream') and body.startswith(b'\xff'):
        if len(body) < 7 or (body[1] & 0xF6) != 0xF0:
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        frame_length = ((body[3] & 0x03) << 11) | (body[4] << 3) | (body[5] >> 5)
        if frame_length < 7 or frame_length > len(body):
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        return 'aac-adts'
    if content_type in ('audio/aac', 'application/octet-stream') and body.startswith(b'ID3'):
        if len(body) < 10 or any(value & 0x80 for value in body[6:10]):
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        offset = 10 + ((body[6] << 21) | (body[7] << 14) | (body[8] << 7) | body[9])
        if (offset + 7 > len(body) or body[offset] != 0xFF
                or (body[offset + 1] & 0xF6) != 0xF0):
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        frame_length = ((body[offset + 3] & 0x03) << 11) | (body[offset + 4] << 3) | (body[offset + 5] >> 5)
        if frame_length < 7 or offset + frame_length > len(body):
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        return 'aac-adts'
    if content_type in ('audio/mp4', 'video/mp4', 'application/octet-stream'):
        if len(body) < 8:
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        box_length = int.from_bytes(body[:4], 'big')
        box_type = body[4:8]
        if box_type not in (b'ftyp', b'styp', b'moof', b'sidx') or (box_length not in (0, 1) and box_length > len(body)):
            raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
        return 'iso-bmff'
    raise SourceFailure(SourceCode.MEDIA_FETCH_FAILED)
