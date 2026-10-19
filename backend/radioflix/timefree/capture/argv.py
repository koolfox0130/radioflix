"""Shell-free ffmpeg invocation for a future reviewed media pipeline.

This component accepts only adapter-owned paths. The production adapter does
not expose it yet; live capture remains unavailable.
"""

import os
import stat
import subprocess
from pathlib import Path

from radioflix.timefree.capture.errors import CaptureFailure


class FfmpegArgvTranscoder:
    """Convert an adapter-owned media file without invoking a shell."""

    def __init__(self, executable: Path, *, preflight_allowlisted_path: Path | None = None):
        self.executable = Path(executable)
        self.preflight_allowlisted_path = (
            Path(preflight_allowlisted_path) if preflight_allowlisted_path is not None else None
        )

    def _executable(self) -> Path:
        path = self.executable
        try:
            resolved = path.resolve(strict=True)
            fixed_paths = {Path('/usr/bin/ffmpeg'), Path('/usr/local/bin/ffmpeg')}
            preflight_path = self.preflight_allowlisted_path
            allowed = resolved in fixed_paths or (
                preflight_path is not None and preflight_path.is_absolute()
                and resolved == preflight_path.resolve(strict=True)
            )
            if (not allowed or not path.is_absolute() or path.name != 'ffmpeg' or path.is_symlink()
                    or not stat.S_ISREG(resolved.stat().st_mode)
                    or not os.access(resolved, os.X_OK)):
                raise CaptureFailure('ffmpeg_not_allowlisted')
        except OSError:
            raise CaptureFailure('ffmpeg_unavailable') from None
        return resolved

    def convert(self, source: Path, destination: Path, *, timeout_seconds: int) -> None:
        source, destination = Path(source), Path(destination)
        if source.parent.resolve() != destination.parent.resolve():
            raise CaptureFailure('media_path_invalid')
        if source.is_symlink() or not source.is_file():
            raise CaptureFailure('media_missing')
        if destination.exists() or destination.is_symlink():
            raise CaptureFailure('output_collision')
        argv = [
            str(self._executable()), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-protocol_whitelist', 'file,pipe', '-i', str(source), '-map', '0:a:0',
            '-vn', '-c:a', 'pcm_s16le', '-f', 'wav', '-n', str(destination),
        ]
        try:
            result = subprocess.run(argv, shell=False, cwd=source.parent, timeout=timeout_seconds,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                                    close_fds=True)
        except subprocess.TimeoutExpired:
            raise CaptureFailure('capture_timeout') from None
        except OSError:
            raise CaptureFailure('ffmpeg_unavailable') from None
        if result.returncode != 0:
            raise CaptureFailure('ffmpeg_failed')
