"""Small typed values passed between capture stages."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CaptureMetadata:
    job_id: str
    episode_id: str
    station: str
    start_at: datetime
    end_at: datetime
    # Current live source supports only the ordinary in-area mode.
    areafree: int = 0


@dataclass(frozen=True)
class AuthContext:
    # Never print or serialize the credential. Production auth is not wired.
    credential: str = field(repr=False)
    area_id: str = ''


@dataclass(frozen=True)
class PlaylistReference:
    url: str
    media_kind: str = 'hls'


@dataclass(frozen=True)
class CaptureResult:
    job_id: str
    workspace: Path
    audio_path: Path
    byte_size: int
    duration: float
    sha256: str
