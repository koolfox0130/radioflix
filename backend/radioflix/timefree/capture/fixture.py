"""Deterministic fixture ports. They never open sockets or invoke subprocesses."""

import wave
from datetime import datetime
from pathlib import Path

from radioflix.timefree.capture.errors import CaptureFailure
from radioflix.timefree.capture.models import AuthContext, PlaylistReference


class FixtureAuthenticator:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def authenticate(self, metadata, *, timeout_seconds):
        self.calls.append(metadata)
        if self.fail:
            raise CaptureFailure('auth_failed')
        return AuthContext('fixture-only', 'JP13')


class FixturePlaylistProvider:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def resolve(self, metadata, auth, *, timeout_seconds):
        self.calls.append((metadata, auth))
        if self.fail:
            raise CaptureFailure('playlist_failed')
        return PlaylistReference('fixture://synthetic/timefree.m3u8')


class FixtureMediaFetcher:
    def __init__(self, fail=False, *, timeout=False, traversal=False, output_collision=False):
        self.fail, self.timeout = fail, timeout
        self.traversal, self.output_collision = traversal, output_collision
        self.calls = []

    def download(self, playlist, auth, destination: Path, *, timeout_seconds):
        self.calls.append((playlist, auth, timeout_seconds))
        if self.timeout:
            raise TimeoutError()
        if self.fail:
            raise CaptureFailure('media_failed')
        path = destination.parent.parent / 'outside.ts' if self.traversal else destination
        path = destination.parent / 'audio.wav' if self.output_collision else path
        path.write_bytes(b'synthetic-media-fixture')
        return path


class SyntheticAudioTranscoder:
    def __init__(self, duration: int, *, fail=False, timeout=False,
                 truncated=False, zero_bytes=False, wrong_format=False):
        self.duration, self.fail, self.timeout = duration, fail, timeout
        self.truncated, self.zero_bytes, self.wrong_format = truncated, zero_bytes, wrong_format
        self.calls = []

    def convert(self, source: Path, destination: Path, *, timeout_seconds):
        self.calls.append((source, destination, timeout_seconds))
        if self.timeout:
            raise TimeoutError()
        if self.fail:
            raise CaptureFailure('ffmpeg_failed')
        if self.zero_bytes:
            destination.write_bytes(b'')
            return
        if self.wrong_format:
            destination.write_bytes(b'not a wave file')
            return
        with wave.open(str(destination), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(1)
            audio.setframerate(1)
            audio.writeframes(b'\x80' * self.duration)
        if self.truncated:
            with destination.open('r+b') as audio:
                audio.truncate(44)
