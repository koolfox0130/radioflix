"""Dependency-free capture policy values and sanitized failures.

This layer must not import API, capture implementations, I/O or worker code.
"""
from dataclasses import dataclass


class CaptureFailure(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CaptureNotReady(CaptureFailure):
    def __init__(self):
        super().__init__('capture_not_ready')


@dataclass(frozen=True)
class CaptureAdmission:
    boot_mode: str
    timefree_writes: bool
    ready: bool
    bridge_approved: bool


@dataclass(frozen=True)
class CaptureReadiness:
    ready: bool
    reason: str | None = None
