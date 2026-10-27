"""Bounded, shell-free ADTS-to-WAV transcoding for a job workspace."""

import os
import json
import re
import shutil
import stat
import subprocess
import uuid
import struct
from pathlib import Path
from typing import Sequence

from radioflix.timefree.capture.errors import CaptureFailure


MAX_INPUTS = 3
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_INPUT_DURATION_SECONDS = 60.0
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_STDERR_BYTES = 1024 * 1024
MAX_TIMEOUT_SECONDS = 120
MIN_FREE_BYTES = 128 * 1024 * 1024
_INPUT_NAME = re.compile(r'^segment-[0-9]{3}\.bin$')
_SAMPLE_RATES = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
                 16000, 12000, 11025, 8000, 7350)


class FfmpegArgvTranscoder:
    """Decode one to three validated AAC/ADTS files into a workspace WAV.

    The executable must be a fixed system path or exactly the executable path
    recorded by preflight. Input/output names and all ffmpeg options are owned
    by this class; metadata and callers cannot add arguments.
    """

    def __init__(self, executable: Path, *, workspace: Path,
                 preflight_allowlisted_path: Path | None = None,
                 ffprobe_executable: Path | None = None):
        self.executable = Path(executable)
        self.workspace = Path(workspace)
        self.ffprobe_executable = (Path(ffprobe_executable) if ffprobe_executable is not None
                                   else self.executable.with_name('ffprobe'))
        self.preflight_allowlisted_path = (
            Path(preflight_allowlisted_path) if preflight_allowlisted_path is not None else None
        )
        self.version: str | None = None
        self.ffprobe_version: str | None = None

    def _workspace(self) -> Path:
        try:
            if self.workspace.is_symlink():
                raise ValueError
            root = self.workspace.resolve(strict=True)
            if not root.is_dir() or root != self.workspace.absolute():
                raise ValueError
            return root
        except Exception:
            raise CaptureFailure('work_root_invalid') from None

    def _executable(self) -> Path:
        path = self.executable
        try:
            resolved = path.resolve(strict=True)
            fixed_paths = {Path('/usr/bin/ffmpeg'), Path('/usr/local/bin/ffmpeg')}
            preflight_path = self.preflight_allowlisted_path
            preflight_ok = (
                preflight_path is not None and preflight_path.is_absolute()
                and not preflight_path.is_symlink()
                and resolved == preflight_path.resolve(strict=True)
            )
            fixed_ok = path.is_absolute() and not path.is_symlink() and resolved in fixed_paths
            if (not (fixed_ok or preflight_ok) or not stat.S_ISREG(resolved.stat().st_mode)
                    or not os.access(resolved, os.X_OK)):
                raise CaptureFailure('ffmpeg_not_allowlisted')
            return resolved
        except CaptureFailure:
            raise
        except OSError:
            raise CaptureFailure('ffmpeg_unavailable') from None

    def _ffprobe_executable(self) -> Path:
        candidate = self.ffprobe_executable
        try:
            resolved = candidate.resolve(strict=True)
            if (not candidate.is_absolute() or candidate.is_symlink() or candidate.name != 'ffprobe'
                    or resolved.parent != self._executable().parent
                    or not stat.S_ISREG(resolved.stat().st_mode) or not os.access(resolved, os.X_OK)):
                raise CaptureFailure('ffprobe_not_allowlisted')
            return resolved
        except CaptureFailure:
            raise
        except OSError:
            raise CaptureFailure('ffprobe_unavailable') from None

    def preflight(self, *, segment_count: int, expected_duration: float,
                  timeout_seconds: int = 15) -> str:
        """Validate executable/version and workspace capacity before capture."""
        if (isinstance(segment_count, bool) or not isinstance(segment_count, int)
                or not 1 <= segment_count <= MAX_INPUTS
                or isinstance(expected_duration, bool)
                or not isinstance(expected_duration, (int, float))
                or not 0 < expected_duration <= MAX_INPUT_DURATION_SECONDS
                or isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int)
                or not 1 <= timeout_seconds <= 30):
            raise CaptureFailure('ffmpeg_preflight_invalid')
        root = self._workspace()
        if (root / 'capture.wav').exists() or (root / 'capture.wav').is_symlink():
            raise CaptureFailure('output_collision')
        try:
            if not os.access(root, os.W_OK) or shutil.disk_usage(root).free < MIN_FREE_BYTES:
                raise CaptureFailure('work_root_unavailable')
        except OSError:
            raise CaptureFailure('work_root_unavailable') from None
        executable = self._executable()
        try:
            result = subprocess.run([str(executable), '-version'], shell=False, cwd=root,
                                    timeout=timeout_seconds, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=False, close_fds=True)
        except subprocess.TimeoutExpired:
            raise CaptureFailure('ffmpeg_timeout') from None
        except OSError:
            raise CaptureFailure('ffmpeg_unavailable') from None
        if result.returncode != 0 or len(result.stdout) > 16 * 1024 or len(result.stderr) > MAX_STDERR_BYTES:
            raise CaptureFailure('ffmpeg_preflight_failed')
        first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else b''
        match = re.fullmatch(rb'ffmpeg version ([A-Za-z0-9._+-]{1,64})(?: .*)?', first_line)
        if not match:
            raise CaptureFailure('ffmpeg_preflight_failed')
        self.version = match.group(1).decode('ascii')
        probe = self._ffprobe_executable()
        try:
            probe_result = subprocess.run([str(probe), '-version'], shell=False, cwd=root,
                                           timeout=timeout_seconds, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, check=False, close_fds=True)
        except subprocess.TimeoutExpired:
            raise CaptureFailure('ffprobe_timeout') from None
        except OSError:
            raise CaptureFailure('ffprobe_unavailable') from None
        if (probe_result.returncode != 0 or len(probe_result.stdout) > 16 * 1024
                or len(probe_result.stderr) > MAX_STDERR_BYTES):
            raise CaptureFailure('ffprobe_preflight_failed')
        probe_line = probe_result.stdout.splitlines()[0] if probe_result.stdout.splitlines() else b''
        probe_match = re.fullmatch(rb'ffprobe version ([A-Za-z0-9._+-]{1,64})(?: .*)?', probe_line)
        if not probe_match:
            raise CaptureFailure('ffprobe_preflight_failed')
        self.ffprobe_version = probe_match.group(1).decode('ascii')
        return self.version

    def convert(self, source: Path | Sequence[Path], destination: Path | None = None,
                *, timeout_seconds: int) -> None:
        sources = (Path(source),) if isinstance(source, (str, os.PathLike)) else tuple(Path(p) for p in source)
        root = self._workspace()
        if (not 1 <= len(sources) <= MAX_INPUTS or len(set(sources)) != len(sources)
                or isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int)
                or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS):
            raise CaptureFailure('ffmpeg_request_invalid')
        target = root / 'capture.wav'
        if destination is not None:
            requested = Path(destination)
            try:
                if requested.parent.resolve(strict=True) != root or requested.name != target.name:
                    raise CaptureFailure('media_path_invalid')
            except OSError:
                raise CaptureFailure('media_path_invalid') from None
        if target.exists() or target.is_symlink():
            raise CaptureFailure('output_collision')

        durations: list[float] = []
        sample_rate = None
        identities: set[tuple[int, int]] = set()
        for path in sources:
            if (not path.is_absolute() or '..' in path.parts or path.is_symlink()
                    or path.name == '' or not _INPUT_NAME.fullmatch(path.name)):
                raise CaptureFailure('media_path_invalid')
            try:
                if path.parent != root or path.parent.resolve(strict=True) != root:
                    raise CaptureFailure('media_path_invalid')
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_INPUT_BYTES:
                    raise CaptureFailure('media_invalid')
                identity = (info.st_dev, info.st_ino)
                if identity in identities:
                    raise CaptureFailure('media_invalid')
                identities.add(identity)
                core_rate, duration = _adts_duration(path)
                decoded_rate, _channels = _probe_aac_sample_rate(
                    self._ffprobe_executable(), path, workspace=root,
                )
            except CaptureFailure:
                raise
            except OSError:
                raise CaptureFailure('media_missing') from None
            # ADTS sampling_frequency_index is the AAC core rate. AAC SBR can
            # make the decoder output rate twice that value, so the WAV contract
            # follows ffprobe's bounded local decoder result, not the core rate.
            if decoded_rate not in (core_rate, core_rate * 2) or decoded_rate not in _SAMPLE_RATES:
                raise CaptureFailure('media_invalid')
            if sample_rate is not None and decoded_rate != sample_rate:
                raise CaptureFailure('media_invalid')
            sample_rate = decoded_rate
            durations.append(duration)
        expected = sum(durations)
        if expected <= 0 or expected > MAX_INPUT_DURATION_SECONDS:
            raise CaptureFailure('media_duration_invalid')

        executable = self._executable()
        temp = root / f'.capture-{uuid.uuid4().hex}.wav'
        argv = [str(executable), '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-xerror', '-threads', '1', '-filter_threads', '1']
        for path in sources:
            argv.extend(['-protocol_whitelist', 'file', '-f', 'aac', '-i', str(path)])
        if len(sources) == 1:
            argv.extend(['-map', '0:a:0'])
        else:
            chain = ''.join(f'[{index}:a:0]' for index in range(len(sources)))
            argv.extend(['-filter_complex', f'{chain}concat=n={len(sources)}:v=0:a=1[outa]',
                         '-map', '[outa]'])
        argv.extend(['-vn', '-c:a', 'pcm_s16le', '-f', 'wav', '-n', str(temp)])
        try:
            result = subprocess.run(argv, shell=False, cwd=root, timeout=timeout_seconds,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    check=False, close_fds=True)
            if len(result.stderr) > MAX_STDERR_BYTES:
                raise CaptureFailure('ffmpeg_stderr_too_large')
            if result.returncode != 0:
                raise CaptureFailure('ffmpeg_failed')
            _validate_wav(temp, expected, len(sources), sample_rate)
            if temp.stat().st_size > MAX_OUTPUT_BYTES:
                raise CaptureFailure('ffmpeg_output_too_large')
            os.link(temp, target)
        except subprocess.TimeoutExpired:
            raise CaptureFailure('ffmpeg_timeout') from None
        except CaptureFailure:
            raise
        except FileExistsError:
            raise CaptureFailure('output_collision') from None
        except Exception:
            raise CaptureFailure('ffmpeg_failed') from None
        finally:
            temp.unlink(missing_ok=True)


def _adts_duration(path: Path) -> tuple[int, float]:
    data = path.read_bytes()
    offset = 0
    if data.startswith(b'ID3'):
        if len(data) < 10 or any(value & 0x80 for value in data[6:10]):
            raise CaptureFailure('media_invalid')
        offset = 10 + ((data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9])
    total_samples = 0
    sample_rate = None
    while offset < len(data):
        if offset + 7 > len(data) or data[offset] != 0xFF or (data[offset + 1] & 0xF6) != 0xF0:
            raise CaptureFailure('media_truncated')
        rate_index = (data[offset + 2] >> 2) & 0x0F
        if rate_index >= len(_SAMPLE_RATES):
            raise CaptureFailure('media_invalid')
        rate = _SAMPLE_RATES[rate_index]
        header_size = 7 if data[offset + 1] & 1 else 9
        frame_length = ((data[offset + 3] & 0x03) << 11) | (data[offset + 4] << 3) | (data[offset + 5] >> 5)
        if frame_length < header_size or offset + frame_length > len(data):
            raise CaptureFailure('media_truncated')
        if sample_rate is not None and rate != sample_rate:
            raise CaptureFailure('media_invalid')
        sample_rate = rate
        total_samples += 1024 * ((data[offset + 6] & 0x03) + 1)
        offset += frame_length
    if sample_rate is None or total_samples == 0:
        raise CaptureFailure('media_invalid')
    duration = total_samples / sample_rate
    if duration > MAX_INPUT_DURATION_SECONDS:
        raise CaptureFailure('media_duration_invalid')
    return sample_rate, duration


def _probe_aac_sample_rate(ffprobe: Path, path: Path, *, workspace: Path,
                           timeout_seconds: int = 10) -> tuple[int, int]:
    """Return the local AAC decoder output rate and channel count.

    For HE-AAC/SBR, ffprobe reports the effective decoded rate (which can be
    twice the ADTS core rate). Only a bounded local ADTS file is accepted.
    """
    root = Path(workspace).resolve(strict=True)
    target = Path(path)
    executable = Path(ffprobe)
    try:
        if (target.is_symlink() or target.resolve(strict=True).parent != root
                or not stat.S_ISREG(target.stat().st_mode)
                or executable.is_symlink() or not executable.is_absolute()
                or executable.name != 'ffprobe' or not stat.S_ISREG(executable.stat().st_mode)
                or not os.access(executable, os.X_OK) or not 1 <= timeout_seconds <= 30):
            raise CaptureFailure('media_probe_path_invalid')
    except CaptureFailure:
        raise
    except OSError:
        raise CaptureFailure('media_missing') from None
    argv = [str(executable), '-v', 'error', '-protocol_whitelist', 'file', '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name,sample_rate,channels', '-of', 'json', str(target)]
    try:
        result = subprocess.run(argv, shell=False, cwd=root, timeout=timeout_seconds,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                                close_fds=True)
    except subprocess.TimeoutExpired:
        raise CaptureFailure('ffprobe_timeout') from None
    except OSError:
        raise CaptureFailure('ffprobe_unavailable') from None
    if result.returncode or len(result.stdout) > 65536 or len(result.stderr) > 4096:
        raise CaptureFailure('media_probe_failed')
    try:
        parsed = json.loads(result.stdout)
        stream = parsed['streams'][0]
        rate = int(stream['sample_rate'])
        channels = int(stream['channels'])
        if stream['codec_name'] != 'aac' or rate not in _SAMPLE_RATES or channels not in (1, 2):
            raise ValueError
        return rate, channels
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise CaptureFailure('media_probe_invalid') from None


def _validate_wav(path: Path, expected_duration: float, segment_count: int, sample_rate: int) -> None:
    reason, info = _wav_diagnostic(path, sample_rate)
    if reason:
        raise CaptureFailure('ffmpeg_output_invalid')
    tolerance = max(0.15, segment_count * 2048 / sample_rate)
    if abs(info['duration'] - expected_duration) > tolerance:
        raise CaptureFailure('ffmpeg_duration_mismatch')


def _wav_diagnostic(path: Path, expected_sample_rate: int | None = None) -> tuple[str | None, dict]:
    """Return a non-sensitive validator reason and PCM properties.

    RIFF chunks may appear between fmt and data, and metadata chunks may follow
    data. This parser walks the declared RIFF extent instead of assuming a
    canonical 44-byte header. Only integer format tag 1 (PCM) is accepted.
    """
    empty = {}
    try:
        if path.is_symlink() or not path.is_file():
            return 'INVALID_FILE', empty
        size = path.stat().st_size
        if size > MAX_OUTPUT_BYTES or size < 12:
            return 'SIZE_MISMATCH', empty
        with path.open('rb') as stream:
            header = stream.read(12)
            if header[:4] != b'RIFF':
                return 'INVALID_RIFF', empty
            if header[8:12] != b'WAVE':
                return 'INVALID_WAVE', empty
            riff_size = struct.unpack_from('<I', header, 4)[0]
            riff_end = 8 + riff_size
            if riff_size < 4 or riff_end > size:
                return 'TRUNCATED_DATA', empty
            offset = 12
            fmt = None
            data_offset = data_size = None
            chunks = []
            while offset < riff_end:
                if riff_end - offset < 8:
                    return 'INVALID_DATA_CHUNK', empty
                stream.seek(offset)
                chunk_header = stream.read(8)
                if len(chunk_header) != 8:
                    return 'INVALID_DATA_CHUNK', empty
                chunk_id, chunk_size = chunk_header[:4], struct.unpack_from('<I', chunk_header, 4)[0]
                chunks.append(chunk_id.decode('ascii', errors='replace'))
                payload = offset + 8
                chunk_end = payload + chunk_size
                padded_end = chunk_end + (chunk_size & 1)
                if chunk_end < payload or padded_end > riff_end:
                    return ('TRUNCATED_DATA' if chunk_id == b'data' else 'INVALID_DATA_CHUNK'), empty
                if chunk_id == b'fmt ':
                    if fmt is not None or chunk_size < 16:
                        return 'INVALID_FMT', empty
                    stream.seek(payload)
                    raw = stream.read(min(chunk_size, 64))
                    if len(raw) < 16:
                        return 'INVALID_FMT', empty
                    tag, channels, rate, byte_rate, align, bits = struct.unpack_from('<HHIIHH', raw)
                    if tag == 0xFFFE:
                        if chunk_size < 40 or len(raw) < 40 or struct.unpack_from('<H', raw, 16)[0] < 22:
                            return 'INVALID_FMT', empty
                        # KSDATAFORMAT_SUBTYPE_PCM GUID, little-endian fields.
                        if raw[24:40] != bytes.fromhex('0100000000001000800000aa00389b71'):
                            return 'UNEXPECTED_CODEC', empty
                    elif tag != 1:
                        return 'UNEXPECTED_CODEC', empty
                    fmt = (tag, channels, rate, byte_rate, align, bits, chunk_size)
                elif chunk_id == b'data':
                    if data_offset is not None:
                        return 'INVALID_DATA_CHUNK', empty
                    data_offset, data_size = payload, chunk_size
                offset = padded_end
            if offset != riff_end:
                return 'INVALID_DATA_CHUNK', empty
            if fmt is None:
                return 'INVALID_FMT', empty
            if data_offset is None or data_size is None:
                return 'INVALID_DATA_CHUNK', empty
            tag, channels, rate, byte_rate, align, bits, fmt_size = fmt
            if channels not in (1, 2) or bits != 16 or rate <= 0 or align <= 0:
                return 'UNEXPECTED_CODEC', empty
            expected_align = channels * (bits // 8)
            if align != expected_align or byte_rate != rate * align:
                return 'INVALID_BLOCK_ALIGN', empty
            if data_size == 0:
                return 'ZERO_AUDIO_DATA', empty
            if data_size > size - data_offset:
                return 'TRUNCATED_DATA', empty
            if data_size % align:
                return 'INVALID_BLOCK_ALIGN', empty
            frames = data_size // align
            if frames <= 0:
                return 'IMPOSSIBLE_SAMPLE_COUNT', empty
            if expected_sample_rate is not None and rate != expected_sample_rate:
                return 'UNEXPECTED_SAMPLE_RATE', empty
            return None, {'channels': channels, 'sample_rate': rate, 'sample_width': bits // 8,
                          'frames': frames, 'data_bytes': data_size,
                          'duration': frames / rate, 'file_size': size,
                          'riff_size': riff_size, 'riff_end': riff_end, 'chunks': tuple(chunks),
                          'format_tag': tag, 'fmt_size': fmt_size, 'byte_rate': byte_rate,
                          'block_align': align, 'bits_per_sample': bits,
                          'data_offset': data_offset, 'declared_data_size': data_size,
                          'actual_data_bytes': min(data_size, max(0, size - data_offset)),
                          'trailing_bytes': size - riff_end}
    except (OSError, OverflowError, struct.error):
        return 'INVALID_DATA_CHUNK', empty


def _ffprobe_wav(ffprobe: Path, path: Path, *, workspace: Path,
                 timeout_seconds: int = 10) -> dict:
    """Test/diagnostic-only bounded ffprobe. Not called by capture execution."""
    root = Path(workspace).resolve(strict=True)
    target = Path(path)
    executable = Path(ffprobe)
    if (target.is_symlink() or target.resolve(strict=True).parent != root
            or executable.is_symlink() or not executable.is_absolute()
            or not stat.S_ISREG(executable.stat().st_mode) or not os.access(executable, os.X_OK)
            or not 1 <= timeout_seconds <= 30):
        raise ValueError('probe_path_invalid')
    argv = [str(executable), '-v', 'error', '-show_entries',
            'format=format_name,duration,size,bit_rate:stream=codec_name,sample_rate,channels,sample_fmt,bits_per_sample',
            '-of', 'json', str(target)]
    try:
        result = subprocess.run(argv, shell=False, cwd=root, timeout=timeout_seconds,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                                close_fds=True)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('probe_failed') from None
    if result.returncode or len(result.stdout) > 65536 or len(result.stderr) > 4096:
        raise ValueError('probe_failed')
    try:
        parsed = json.loads(result.stdout)
        fmt = parsed['format']
        stream = parsed['streams'][0]
        return {'format_name': fmt['format_name'], 'duration': float(fmt['duration']),
                'size': int(fmt['size']), 'bit_rate': int(fmt.get('bit_rate', 0)),
                'codec': stream['codec_name'], 'sample_rate': int(stream['sample_rate']),
                'channels': int(stream['channels']), 'sample_fmt': stream['sample_fmt'],
                'bits_per_sample': int(stream.get('bits_per_sample', 0))}
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError('probe_result_invalid') from None
