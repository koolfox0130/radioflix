"""One-job-only composition. control.production_worker never imports this factory.

No environment-selectable limits, endpoints, transport or fixture implementation.
"""
import math
import os
from datetime import datetime
from pathlib import Path

from radioflix.timefree.capture.adapter import CaptureAdapter
from radioflix.timefree.capture.argv import FfmpegArgvTranscoder
from radioflix.timefree.capture.errors import CaptureFailure
from radioflix.timefree.capture.limits import ACCEPTANCE
from radioflix.timefree.capture.production import ProductionCaptureAdapter, WorkspaceTranscoder, GuardedTransport
from radioflix.timefree.capture.source.production_auth import ProductionAuthenticator
from radioflix.timefree.capture.source.station_area import StationAreaSource
from radioflix.timefree.capture.source.media import HlsMediaSource
from radioflix.timefree.capture.source.models import RetryPolicy
from radioflix.timefree.capture.source.transport import ProductionHttpTransport
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker

FIXED_OVERHEAD = 7  # player JS + auth1 + auth2 + area catalog + stream XML + master + media
RETRY_REDIRECT_ALLOWANCE = 4  # shared, not per request
MAX_SEGMENTS = 62  # ceil(300 / 5) + two boundary segments; observed five-minute item: 61
MAX_WIRE_REQUESTS = FIXED_OVERHEAD + MAX_SEGMENTS + RETRY_REDIRECT_ALLOWANCE


def budget(duration):
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= 300:
        raise ValueError('acceptance_duration_invalid')
    segments = min(MAX_SEGMENTS, math.ceil(duration / 5) + 2)
    return {'duration': duration, 'max_audio_duration': ACCEPTANCE.audio_seconds,
            'max_segments': segments, 'fixed_overhead': FIXED_OVERHEAD,
            'retry_redirect_allowance': RETRY_REDIRECT_ALLOWANCE,
            'max_wire_requests': FIXED_OVERHEAD + segments + RETRY_REDIRECT_ALLOWANCE,
            'absolute_wire_max': MAX_WIRE_REQUESTS}


def row_budget(row):
    return budget((datetime.fromisoformat(row['end_at']) - datetime.fromisoformat(row['start_at'])).total_seconds())


class AcceptanceTransport(ProductionHttpTransport):
    def __init__(self, duration):
        super().__init__(observation_mode=True, max_wire_requests=8, policy=RetryPolicy(max_attempts=3))
        self._acceptance_limit = budget(duration)['max_wire_requests']

    def _wire_limit(self):
        return min(self._acceptance_limit, MAX_WIRE_REQUESTS)

    def manifest_budget(self, count):
        if type(count) is not int or not 1 <= count <= MAX_SEGMENTS:
            raise ValueError('acceptance_segment_limit')
        self._acceptance_limit = min(self._wire_limit(), FIXED_OVERHEAD + count + RETRY_REDIRECT_ALLOWANCE)


class AreaAuthenticator(ProductionAuthenticator):
    def authenticate(self, metadata=None, *, timeout_seconds=15):
        auth = super().authenticate(metadata, timeout_seconds=timeout_seconds)
        catalog = StationAreaSource(self.transport).load_catalog(timeout_seconds=timeout_seconds)
        if catalog.area_by_station.get(metadata.station) != auth.area_id:
            raise CaptureFailure('auth_area_mismatch')
        return auth


class AcceptanceMedia(HlsMediaSource):
    def __init__(self, *args, duration, source_transport, **kwargs):
        super().__init__(*args, **kwargs)
        self.segment_limit = budget(duration)['max_segments']
        self.source_transport = source_transport

    def check_segments(self, segments):
        if not 1 <= len(segments) <= min(self.segment_limit, MAX_SEGMENTS):
            raise CaptureFailure('acceptance_segment_limit')
        self.source_transport.manifest_budget(len(segments))


class AcceptanceTranscoder(WorkspaceTranscoder):
    def _converter(self, root):
        return FfmpegArgvTranscoder(self.executable, workspace=root,
            preflight_allowlisted_path=self.preflight_allowlisted_path, _profile=ACCEPTANCE)


class AcceptanceCapture(ProductionCaptureAdapter):
    def __init__(self, *, duration, **kwargs):
        budget(duration)
        super().__init__(**kwargs)
        guarded = GuardedTransport(self.source_transport, self.require_start)
        self.authenticator = AreaAuthenticator(guarded)
        self.media_fetcher = AcceptanceMedia(guarded, self.playlist_provider,
            work_root=self.work_root, duration=duration, source_transport=self.source_transport)
        self.transcoder = AcceptanceTranscoder(self.transcoder.executable,
            preflight_allowlisted_path=self.transcoder.preflight_allowlisted_path)

    def _metadata(self, ident):
        row, metadata, expected = CaptureAdapter._metadata(self, ident)
        budget(expected)  # before auth, storage or media work
        return row, metadata, expected


def acceptance_worker(*, ident, bridge_approved=False):
    # CLI has validated the exact approval before this factory is reached.
    if bridge_approved is not True or os.getenv('RFRIENDS_ENABLE_WRITES') != '0':
        raise ValueError('acceptance_not_approved')
    from radioflix.timefree.acceptance import approved_job
    approval_path = os.environ['RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE']
    approved_job(approval_path, ident)
    store = TimefreeStore(os.environ['RADIOFLIX_DB_PATH'])
    row = store.get(ident)
    limits = row_budget(row)
    root = Path(os.environ['RADIOFLIX_TIMEFREE_ROOT'])
    guard = Preflight(store, '/native-reservations', ['/recordings', '/native-timefree'], root)
    capture = AcceptanceCapture(duration=limits['duration'], store=store, managed_root=root,
        preflight=guard, transport=AcceptanceTransport(limits['duration']), bridge_approved=True)
    capture.refresh_readiness()
    from radioflix.timefree.runtime_policy import require_runtime_capture
    require_runtime_capture(capture)
    return TimefreeWorker(store, root, capture, preflight=guard)
