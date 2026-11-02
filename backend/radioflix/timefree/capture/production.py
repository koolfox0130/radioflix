"""Production stage composition; local readiness never grants external approval."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from radioflix.timefree.runtime_policy import require_runtime_capture
from radioflix.timefree.contracts import CaptureReadiness
from radioflix.timefree.capture.adapter import CaptureAdapter
from radioflix.timefree.capture.argv import FfmpegArgvTranscoder, MAX_INPUT_DURATION_SECONDS
from radioflix.timefree.capture.errors import CaptureFailure
from radioflix.timefree.capture.models import CaptureMetadata
from radioflix.timefree.capture.source.media import HlsMediaSource
from radioflix.timefree.capture.source.playlist import TimefreePlaylistSource
from radioflix.timefree.capture.source.production_auth import ProductionAuthenticator
from radioflix.timefree.capture.source.transport import ProductionHttpTransport


class WorkspaceTranscoder:
    """Translate owned stage filenames, preserving the existing argv contract."""
    def __init__(self, executable=Path('/usr/bin/ffmpeg'), *, preflight_allowlisted_path=None):
        self.executable = Path(executable)
        self.preflight_allowlisted_path = preflight_allowlisted_path

    def _converter(self, root):
        return FfmpegArgvTranscoder(self.executable, workspace=root,
                                   preflight_allowlisted_path=self.preflight_allowlisted_path)

    def preflight(self, root):
        self._converter(root).preflight(
            segment_count=1, expected_duration=MAX_INPUT_DURATION_SECONDS)

    def convert(self, source, destination, *, timeout_seconds):
        source, destination = Path(source), Path(destination)
        if source.parent != destination.parent or source.name != 'media-input.ts' or destination.name != 'audio.wav':
            raise CaptureFailure('media_path_invalid')
        segment = source.parent / 'segment-001.bin'
        # link is no-replace; neither stage can overwrite a previous result.
        os.link(source, segment)
        converter = self._converter(source.parent)
        converter.convert(segment, timeout_seconds=timeout_seconds)
        os.link(source.parent / 'capture.wav', destination)


class GuardedTransport:
    def __init__(self, transport, guard):
        self.transport, self.guard = transport, guard
        self.offline_fixture = bool(getattr(transport, 'offline_fixture', False))

    def request(self, request):
        self.guard()  # Recheck revocation before every external request, including auth.
        return self.transport.request(request)


class ProductionCaptureAdapter(CaptureAdapter):
    kind = 'live'
    bridge_approved = False

    def __init__(self, *, store, managed_root, preflight, transport=None,
                 bridge_approved=False, clock=None, executable=Path('/usr/bin/ffmpeg'),
                 preflight_allowlisted_path=None):
        self.bridge_approved = bridge_approved is True
        self.source_transport = transport
        self._readiness = CaptureReadiness(False, 'preflight_not_run')
        guarded = GuardedTransport(transport, self.require_start)
        playlist = TimefreePlaylistSource(guarded)
        root = Path(managed_root)
        super().__init__(store=store, managed_root=root,
                         authenticator=ProductionAuthenticator(guarded), playlist_provider=playlist,
                         media_fetcher=HlsMediaSource(guarded, playlist,
                             work_root=root / '.staging' / 'capture-work'),
                         transcoder=WorkspaceTranscoder(executable,
                             preflight_allowlisted_path=preflight_allowlisted_path),
                         preflight=preflight, clock=clock)

    def local_preflight(self):
        """No HTTP, auth, schema creation or published-data mutation."""
        if self.source_transport is None or not callable(getattr(self.source_transport, 'request', None)):
            raise CaptureFailure('source_unavailable')
        if isinstance(self.source_transport, ProductionHttpTransport) and not self.source_transport.observation_mode:
            raise CaptureFailure('source_unavailable')
        if not callable(self.preflight):
            raise CaptureFailure('preflight_required')
        for port, method in ((self.authenticator, 'authenticate'),
                             (self.playlist_provider, 'resolve'), (self.media_fetcher, 'download')):
            if not callable(getattr(port, method, None)):
                raise CaptureFailure('source_unavailable')
        root = self.managed_root
        if root.absolute() != root.resolve(strict=True) or not root.is_dir() or not os.access(root, os.W_OK | os.X_OK):
            raise CaptureFailure('work_root_invalid')
        for path in (root / '.staging', self.work_root):
            if path.is_symlink() or (path.exists() and (not path.is_dir()
                    or path.stat().st_dev != root.stat().st_dev or not os.access(path, os.W_OK | os.X_OK))):
                raise CaptureFailure('work_root_invalid')
        path = self.store.path
        if (self.store.read_only or path.is_symlink() or not path.is_file()
                or not os.access(path, os.R_OK | os.W_OK)
                or not os.access(path.parent, os.W_OK | os.X_OK)):
            raise CaptureFailure('store_unavailable')
        with sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=1) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('SELECT job_id,state,execution_kind,station_ids FROM timefree_jobs LIMIT 0')
            db.execute('SELECT job_id,manifest FROM timefree_publications LIMIT 0')
        self.transcoder.preflight(root)

    def refresh_readiness(self) -> CaptureReadiness:
        """Explicit local I/O boundary; do not call from disabled health probes."""
        try:
            self.local_preflight()
        except CaptureFailure as error:
            self._readiness = CaptureReadiness(False, error.code)
        except Exception:
            self._readiness = CaptureReadiness(False, 'local_preflight_failed')
        else:
            self._readiness = CaptureReadiness(True)
        return self._readiness

    @property
    def ready(self):
        # Permission checks only inspect a result, never run ffmpeg or touch DB.
        return self._readiness.ready

    def require_start(self):
        require_runtime_capture(self)

    def _metadata(self, ident):
        row, metadata, expected = super()._metadata(ident)
        if expected > MAX_INPUT_DURATION_SECONDS:
            raise CaptureFailure('media_duration_invalid')
        return row, metadata, expected

    @contextmanager
    def capture_job(self, requested_id):
        self.require_start()
        self.refresh_readiness()  # Revalidate local conditions for this capture.
        self.require_start()
        with super().capture_job(requested_id) as result:
            yield result

    @staticmethod
    def contract(metadata: CaptureMetadata) -> dict:
        return {'job_id': metadata.job_id, 'episode_id': metadata.episode_id,
                'station': metadata.station, 'start_at': metadata.start_at, 'end_at': metadata.end_at}
