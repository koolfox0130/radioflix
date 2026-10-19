"""Production contract only. No radiko HTTP/HLS implementation is enabled."""

from contextlib import contextmanager

from radioflix.timefree.capture.adapter import CaptureAdapter
from radioflix.timefree.capture.errors import CaptureNotReady
from radioflix.timefree.capture.models import CaptureMetadata


class ProductionCaptureAdapter(CaptureAdapter):
    kind = 'live'
    ready = False
    bridge_approved = False

    def __init__(self, *, store, managed_root, preflight):
        # Ports are explicit placeholders. No HTTP client or executable is
        # constructed until the production boundary is reviewed and approved.
        super().__init__(store=store, managed_root=managed_root, authenticator=None,
                         playlist_provider=None, media_fetcher=None, transcoder=None,
                         preflight=preflight)

    @contextmanager
    def capture_job(self, requested_id: str):
        raise CaptureNotReady()
        yield  # Keeps this method a context manager while always failing closed.

    @staticmethod
    def contract(metadata: CaptureMetadata) -> dict:
        """Validated fields future ports may receive; no caller-selected path/command."""
        return {
            'job_id': metadata.job_id,
            'episode_id': metadata.episode_id,
            'station': metadata.station,
            'start_at': metadata.start_at.isoformat(),
            'end_at': metadata.end_at.isoformat(),
        }
