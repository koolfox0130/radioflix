"""Shared job-to-audio orchestration with replaceable, bounded stage ports."""

import hashlib
import re
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ValidationError

from radioflix.schemas.reservations import Broadcast, JST
from radioflix.timefree.capture.errors import CaptureFailure, CaptureNotReady
from radioflix.timefree.capture.models import CaptureMetadata, CaptureResult
from radioflix.timefree.publisher import audio_info, job_id
from radioflix.timefree.service import eligibility


ACTIVE_STATES = {'queued', 'running', 'completed', 'unknown'}
SAFE_CODE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


class CaptureAdapter:
    """Fixture-capable orchestrator. All paths are derived beneath managed_root."""

    kind = 'fixture'
    ready = True
    bridge_approved = False

    def __init__(self, *, store, managed_root: Path, authenticator, playlist_provider,
                 media_fetcher, transcoder, preflight, clock=None, timeout_seconds=60):
        self.store = store
        self.managed_root = Path(managed_root)
        self.authenticator = authenticator
        self.playlist_provider = playlist_provider
        self.media_fetcher = media_fetcher
        self.transcoder = transcoder
        self.preflight = preflight
        self.clock = clock or (lambda: datetime.now(JST))
        self.timeout_seconds = timeout_seconds

    @property
    def work_root(self) -> Path:
        return self.managed_root / '.staging' / 'capture-work'

    def _metadata(self, ident: str) -> tuple[dict, CaptureMetadata, float]:
        row = self.store.get(ident)
        if row is None:
            raise CaptureFailure('job_not_found')
        if row.get('job_id') != ident or row.get('state') != 'running' or row.get('execution_kind') != self.kind:
            raise CaptureFailure('job_state_invalid')
        try:
            broadcast = Broadcast.model_validate(row['broadcast'])
            raw_start = datetime.fromisoformat(row['start_at'])
            raw_end = datetime.fromisoformat(row['end_at'])
            if raw_start.tzinfo is None or raw_end.tzinfo is None:
                raise ValueError('naive_datetime')
            start_at = raw_start.astimezone(JST)
            end_at = raw_end.astimezone(JST)
        except (KeyError, TypeError, ValueError, ValidationError, OverflowError):
            raise CaptureFailure('job_metadata_invalid') from None
        episode_id = hashlib.sha256(
            f'{broadcast.station}:{broadcast.starts_at.isoformat()}:{broadcast.ends_at.isoformat()}'.encode()
        ).hexdigest()
        if (broadcast.id != episode_id or row.get('broadcast_episode_id') != episode_id
                or row.get('station') != broadcast.station
                or start_at != broadcast.starts_at or end_at != broadcast.ends_at
                or end_at <= start_at):
            raise CaptureFailure('job_metadata_invalid')
        problem = eligibility(row['broadcast'], self.clock())
        if problem == 'expired':
            raise CaptureFailure('job_expired')
        if problem:
            raise CaptureFailure('job_not_eligible')
        expected = (end_at - start_at).total_seconds()
        metadata = CaptureMetadata(ident, episode_id, broadcast.station, start_at, end_at)
        return row, metadata, expected

    def _check_duplicate(self, row: dict) -> None:
        for other in self.store.list():
            if other['job_id'] == row['job_id'] or other['state'] not in ACTIVE_STATES:
                continue
            if other['broadcast_episode_id'] == row['broadcast_episode_id']:
                raise CaptureFailure('duplicate_job')
            try:
                other_broadcast = Broadcast.model_validate(other['broadcast'])
                current = Broadcast.model_validate(row['broadcast'])
            except (KeyError, TypeError, ValueError, ValidationError):
                raise CaptureFailure('duplicate_state_unknown') from None
            if (other_broadcast.station == current.station
                    and other_broadcast.starts_at < current.ends_at
                    and current.starts_at < other_broadcast.ends_at):
                raise CaptureFailure('duplicate_job')

    def _workspace_root(self) -> Path:
        root = self.managed_root
        try:
            if root.is_symlink() or root.absolute() != root.resolve(strict=True) or not root.is_dir():
                raise CaptureFailure('work_root_invalid')
            staging = root / '.staging'
            if staging.is_symlink():
                raise CaptureFailure('work_root_invalid')
            staging.mkdir(mode=0o700, exist_ok=True)
            capture_root = staging / 'capture-work'
            if capture_root.is_symlink():
                raise CaptureFailure('work_root_invalid')
            capture_root.mkdir(mode=0o700, exist_ok=True)
            if capture_root.resolve(strict=True) != capture_root.absolute():
                raise CaptureFailure('work_root_invalid')
            return capture_root
        except OSError:
            raise CaptureFailure('work_root_unavailable') from None

    @staticmethod
    def _check_work_file(path: Path, workspace: Path, code: str) -> Path:
        try:
            if path.is_symlink() or not path.is_file():
                raise CaptureFailure(code)
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(workspace.resolve(strict=True)):
                raise CaptureFailure(code)
            if path.stat().st_size <= 0:
                raise CaptureFailure(code)
            return resolved
        except OSError:
            raise CaptureFailure(code) from None

    @staticmethod
    def _stage(code: str, operation):
        try:
            return operation()
        except CaptureFailure:
            raise
        except (TimeoutError, subprocess.TimeoutExpired):
            raise CaptureFailure('capture_timeout') from None
        except Exception:
            raise CaptureFailure(code) from None

    def _check_preflight(self, row: dict) -> None:
        if self.preflight is None:
            raise CaptureFailure('preflight_required')
        try:
            self.preflight(row)
        except Exception as error:
            code = getattr(error, 'code', 'preflight_failed')
            if not isinstance(code, str) or not SAFE_CODE.fullmatch(code):
                code = 'preflight_failed'
            raise CaptureFailure(code) from None

    @contextmanager
    def capture_job(self, requested_id: str):
        if not self.ready or (self.kind == 'live' and not self.bridge_approved):
            raise CaptureNotReady()
        try:
            ident = job_id(requested_id)
        except ValueError:
            raise CaptureFailure('invalid_job_id') from None
        row, metadata, expected = self._metadata(ident)
        self._check_duplicate(row)
        self._check_preflight(row)  # Includes native-state and recording conflict checks.
        base = self._workspace_root()
        with tempfile.TemporaryDirectory(prefix=f'{ident}-', dir=base) as temporary:
            workspace = Path(temporary)
            if workspace.is_symlink() or not workspace.resolve(strict=True).is_relative_to(base.resolve(strict=True)):
                raise CaptureFailure('work_path_invalid')
            source_target = workspace / 'media-input.ts'
            output = workspace / 'audio.wav'

            auth = self._stage('auth_failed', lambda: self.authenticator.authenticate(
                metadata, timeout_seconds=self.timeout_seconds))
            playlist = self._stage('playlist_failed', lambda: self.playlist_provider.resolve(
                metadata, auth, timeout_seconds=self.timeout_seconds))
            if not getattr(playlist, 'url', None):
                raise CaptureFailure('playlist_invalid')
            parts = urlsplit(playlist.url)
            if (self.kind == 'fixture' and parts.scheme != 'fixture') or (
                    self.kind == 'live' and parts.scheme != 'https'):
                raise CaptureFailure('playlist_invalid')
            media_path = self._stage('media_failed', lambda: self.media_fetcher.download(
                playlist, auth, source_target, timeout_seconds=self.timeout_seconds))
            media_path = self._check_work_file(Path(media_path), workspace, 'media_invalid')
            if output.exists() or output.is_symlink():
                raise CaptureFailure('output_collision')
            self._stage('ffmpeg_failed', lambda: self.transcoder.convert(
                media_path, output, timeout_seconds=self.timeout_seconds))
            output = self._check_work_file(output, workspace, 'audio_invalid')
            try:
                info = audio_info(output, expected)
            except (OSError, ValueError, TypeError, EOFError, wave.Error) as error:
                code = 'truncated_audio' if str(error) == 'truncated_audio' else 'audio_invalid'
                raise CaptureFailure(code) from None
            yield CaptureResult(ident, workspace, output, info['size'], info['duration'], info['sha256'])
