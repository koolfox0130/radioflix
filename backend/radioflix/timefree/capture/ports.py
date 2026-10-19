"""Injectable capture stage contracts; implementations receive bounded inputs."""

from pathlib import Path
from typing import Protocol

from radioflix.timefree.capture.models import AuthContext, CaptureMetadata, PlaylistReference


class Authenticator(Protocol):
    def authenticate(self, metadata: CaptureMetadata, *, timeout_seconds: int) -> AuthContext: ...


class PlaylistProvider(Protocol):
    def resolve(self, metadata: CaptureMetadata, auth: AuthContext, *, timeout_seconds: int) -> PlaylistReference: ...


class MediaFetcher(Protocol):
    def download(self, playlist: PlaylistReference, auth: AuthContext, destination: Path,
                 *, timeout_seconds: int) -> Path: ...


class AudioTranscoder(Protocol):
    def convert(self, source: Path, destination: Path, *, timeout_seconds: int) -> None: ...
