"""Closed profiles, never selected by environment or HTTP input."""
from dataclasses import dataclass


@dataclass(frozen=True)
class _Limits:
    metadata_seconds: int
    audio_seconds: int
    output_bytes: int


NORMAL = _Limits(60, 60, 32 * 1024 * 1024)
# Publisher already permits +/-2 seconds against the scheduled interval.
# PCM16, stereo, maximum supported 96 kHz, plus 64 KiB RIFF overhead.
ACCEPTANCE = _Limits(300, 302, 302 * 96000 * 2 * 2 + 65536)


def checked(profile):
    if profile is not NORMAL and profile is not ACCEPTANCE:
        raise ValueError('invalid_capture_profile')
    return profile
