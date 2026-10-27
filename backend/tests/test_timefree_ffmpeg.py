"""Bounded ffmpeg tests. Fixture generation and conversion use local files only."""

import os
import struct
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from radioflix.timefree.capture.argv import (FfmpegArgvTranscoder, _adts_duration,
    _ffprobe_wav, _wav_diagnostic)
from radioflix.timefree.capture.errors import CaptureFailure


class ProductionFfmpegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = shutil.which('ffmpeg')
        probe = shutil.which('ffprobe')
        if not configured or not probe:
            raise unittest.SkipTest('ffmpeg and ffprobe required for production argv integration tests')
        cls.ffmpeg = Path(configured).resolve(strict=True)
        cls.ffprobe = Path(probe).resolve(strict=True)
        fixture_dir = tempfile.TemporaryDirectory(prefix='radioflix-aac-fixture-')
        cls.addClassCleanup(fixture_dir.cleanup)
        fixture_path = Path(fixture_dir.name) / 'synthetic.aac'
        result = subprocess.run([
            str(cls.ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=mono:sample_rate=44100',
            '-t', '0.35', '-c:a', 'aac', '-b:a', '64k', '-f', 'adts', '-y', str(fixture_path),
        ], shell=False, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
           check=False, close_fds=True)
        if result.returncode != 0:
            raise RuntimeError('local synthetic AAC fixture generation failed')
        cls.fixture_bytes = fixture_path.read_bytes()
        cls.fixture_matrix = {}
        for rate, channels, bitrate in ((44100, 1, '64k'), (44100, 2, '96k'),
                                        (48000, 1, '64k'), (48000, 2, '96k')):
            layout = 'mono' if channels == 1 else 'stereo'
            target = Path(fixture_dir.name) / f'synthetic-{rate}-{channels}.aac'
            result = subprocess.run([
                str(cls.ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', f'anullsrc=channel_layout={layout}:sample_rate={rate}',
                '-t', '0.37', '-c:a', 'aac', '-profile:a', 'aac_low', '-b:a', bitrate,
                '-f', 'adts', '-y', str(target),
            ], shell=False, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
               check=False, close_fds=True)
            if result.returncode != 0:
                raise RuntimeError('local AAC matrix fixture generation failed')
            cls.fixture_matrix[(rate, channels)] = target.read_bytes()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='radioflix-ffmpeg-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.transcoder = FfmpegArgvTranscoder(
            self.ffmpeg, workspace=self.workspace, preflight_allowlisted_path=self.ffmpeg,
            ffprobe_executable=self.ffprobe)

    def make_aac(self, index):
        target = self.workspace / f'segment-{index:03d}.bin'
        target.write_bytes(self.fixture_bytes)
        return target

    def test_preflight_reports_fixed_ffmpeg_version(self):
        version = self.transcoder.preflight(segment_count=1, expected_duration=1)
        self.assertRegex(version, r'^[A-Za-z0-9._+-]{1,64}$')
        self.assertRegex(self.transcoder.ffprobe_version, r'^[A-Za-z0-9._+-]{1,64}$')

    def test_decoded_rate_sets_wav_contract_when_adts_core_rate_is_doubled(self):
        source = self.workspace / 'segment-001.bin'
        # Minimal ADTS framing at 24 kHz; fake decoder metadata models the
        # observed 48 kHz effective AAC output rate.
        payload_size = 32
        frame_length = 7 + payload_size
        source.write_bytes(bytes((0xFF, 0xF1, 0x58, 0x80 | ((frame_length >> 11) & 3),
                                  (frame_length >> 3) & 0xFF,
                                  ((frame_length & 7) << 5) | 0x1F, 0xFC)) + b'\x00' * payload_size)
        core_rate, duration = _adts_duration(source)
        self.assertEqual(core_rate, 24000)

        def write_wav(argv, **kwargs):
            self.assertFalse(kwargs['shell'])
            self.assertEqual(argv[0], str(self.ffmpeg))
            frames = round(duration * 48000)
            with wave.open(argv[-1], 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(48000)
                out.writeframes(b'\x00\x00' * frames)
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')

        with patch('radioflix.timefree.capture.argv._probe_aac_sample_rate', return_value=(48000, 1)) as probe:
            with patch('radioflix.timefree.capture.argv.subprocess.run', side_effect=write_wav):
                self.transcoder.convert(source, timeout_seconds=10)
        probe.assert_called_once()
        self.assertIsNone(_wav_diagnostic(self.workspace / 'capture.wav', 48000)[0])
        self.assertEqual(_wav_diagnostic(self.workspace / 'capture.wav', 24000)[0], 'UNEXPECTED_SAMPLE_RATE')

    def test_real_ffmpeg_decodes_and_concatenates_one_two_three_segments(self):
        for count in (1, 2, 3):
            sources = [self.make_aac(i) for i in range(1, count + 1)]
            self.transcoder.convert(sources, timeout_seconds=30)
            output = self.workspace / 'capture.wav'
            self.assertGreater(output.stat().st_size, 44)
            with wave.open(str(output), 'rb') as wav:
                self.assertEqual(wav.getcomptype(), 'NONE')
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), 44100)
                self.assertGreater(wav.getnframes(), 0)
            output.unlink()
            for source in sources:
                source.unlink()

    def test_real_ffmpeg_matrix_rates_channels_and_variable_segment_durations(self):
        for rate, channels in ((44100, 1), (44100, 2), (48000, 1), (48000, 2)):
            fixture = self.fixture_matrix[(rate, channels)]
            for count in (1, 2, 3):
                sources = []
                for index in range(1, count + 1):
                    source = self.workspace / f'segment-{index:03d}.bin'
                    # Vary duration by trimming complete ADTS frames, then keep the
                    # framing valid. Different source starts exercise timestamp reset.
                    source.write_bytes(fixture if index % 2 else _drop_last_adts_frame(fixture))
                    sources.append(source)
                self.transcoder.convert(sources, timeout_seconds=30)
                reason, properties = _wav_diagnostic(self.workspace / 'capture.wav', rate)
                self.assertIsNone(reason)
                self.assertEqual(properties['channels'], channels)
                self.assertEqual(properties['sample_rate'], rate)
                self.assertGreater(properties['data_bytes'], 0)
                (self.workspace / 'capture.wav').unlink()
                for source in sources:
                    source.unlink()

    def test_id3_prefixed_adts_is_accepted(self):
        source = self.workspace / 'segment-001.bin'
        source.write_bytes(b'ID3\x04\x00\x00\x00\x00\x00\x00' + self.fixture_bytes)
        self.transcoder.convert([source], timeout_seconds=30)
        self.assertIsNone(_wav_diagnostic(self.workspace / 'capture.wav', 44100)[0])

    def test_ffprobe_diagnostic_matches_wav_parser_without_exposing_media(self):
        source = self.make_aac(1)
        self.transcoder.convert([source], timeout_seconds=30)
        configured_ffprobe = shutil.which('ffprobe')
        if not configured_ffprobe:
            self.skipTest('ffprobe unavailable in isolated test image')
        ffprobe = Path(configured_ffprobe).resolve(strict=True)
        info = _ffprobe_wav(ffprobe, self.workspace / 'capture.wav', workspace=self.workspace)
        self.assertEqual(info['format_name'], 'wav')
        self.assertEqual(info['codec'], 'pcm_s16le')
        self.assertEqual(info['sample_rate'], 44100)
        self.assertEqual(info['channels'], 1)
        self.assertGreater(info['size'], 44)
        self.assertGreater(info['duration'], 0)

    def test_riff_chunk_order_extra_fmt_and_trailing_metadata(self):
        payload = b'\x00\x00' * 100
        fmt = struct.pack('<HHIIHH', 1, 1, 44100, 88200, 2, 16) + b'EXTRA'
        chunks = [_riff_chunk(b'JUNK', b'abc'), _riff_chunk(b'LIST', b'INFO'),
                  _riff_chunk(b'fmt ', fmt), _riff_chunk(b'fact', struct.pack('<I', 100)),
                  _riff_chunk(b'data', payload), _riff_chunk(b'bext', b'meta')]
        wav = self.workspace / 'chunked.wav'
        wav.write_bytes(b'RIFF' + struct.pack('<I', 4 + sum(map(len, chunks))) + b'WAVE' + b''.join(chunks))
        reason, info = _wav_diagnostic(wav, 44100)
        self.assertIsNone(reason)
        self.assertEqual(info['data_bytes'], len(payload))
        self.assertAlmostEqual(info['duration'], 100 / 44100)

    def test_wav_diagnostics_reject_truncation_zero_and_bad_alignment(self):
        payload = b'\x00\x00' * 10
        fmt = struct.pack('<HHIIHH', 1, 2, 44100, 176400, 4, 16)
        wav = self.workspace / 'diagnostic.wav'
        chunks = [_riff_chunk(b'fmt ', fmt), _riff_chunk(b'data', payload)]
        full = b'RIFF' + struct.pack('<I', 4 + sum(map(len, chunks))) + b'WAVE' + b''.join(chunks)
        wav.write_bytes(full[:-2])
        self.assertEqual(_wav_diagnostic(wav)[0], 'TRUNCATED_DATA')
        zero = [_riff_chunk(b'fmt ', fmt), _riff_chunk(b'data', b'')]
        wav.write_bytes(b'RIFF' + struct.pack('<I', 4 + sum(map(len, zero))) + b'WAVE' + b''.join(zero))
        self.assertEqual(_wav_diagnostic(wav)[0], 'ZERO_AUDIO_DATA')
        bad_fmt = struct.pack('<HHIIHH', 1, 2, 44100, 176400, 2, 16)
        bad = [_riff_chunk(b'fmt ', bad_fmt), _riff_chunk(b'data', payload)]
        wav.write_bytes(b'RIFF' + struct.pack('<I', 4 + sum(map(len, bad))) + b'WAVE' + b''.join(bad))
        self.assertEqual(_wav_diagnostic(wav)[0], 'INVALID_BLOCK_ALIGN')

    def test_preflight_rejects_invalid_bounds_and_output_collision(self):
        for count in (0, 4, True):
            with self.assertRaises(CaptureFailure):
                self.transcoder.preflight(segment_count=count, expected_duration=1)
        (self.workspace / 'capture.wav').write_bytes(b'x')
        with self.assertRaises(CaptureFailure) as error:
            self.transcoder.preflight(segment_count=1, expected_duration=1)
        self.assertEqual(error.exception.code, 'output_collision')

    def test_zero_byte_truncated_invalid_and_missing_inputs_rejected(self):
        zero = self.workspace / 'segment-001.bin'
        zero.write_bytes(b'')
        with self.assertRaises(CaptureFailure):
            self.transcoder.convert([zero], timeout_seconds=10)
        zero.write_bytes(b'\xff\xf1\x50\x80\x00')
        with self.assertRaises(CaptureFailure):
            self.transcoder.convert([zero], timeout_seconds=10)
        zero.write_bytes(b'not ADTS')
        with self.assertRaises(CaptureFailure):
            self.transcoder.convert([zero], timeout_seconds=10)
        with self.assertRaises(CaptureFailure) as error:
            self.transcoder.convert([self.workspace / 'segment-002.bin'], timeout_seconds=10)
        self.assertEqual(error.exception.code, 'media_missing')

    def test_duplicate_symlink_traversal_and_injection_names_rejected(self):
        source = self.make_aac(1)
        for inputs in ([source, source], [self.workspace / '..' / source.name]):
            with self.assertRaises(CaptureFailure):
                self.transcoder.convert(inputs, timeout_seconds=10)
        link = self.workspace / 'segment-002.bin'
        link.symlink_to(source)
        with self.assertRaises(CaptureFailure):
            self.transcoder.convert([link], timeout_seconds=10)
        injected = self.workspace / 'segment-003;touch-pwned.bin'
        injected.write_bytes(source.read_bytes())
        with self.assertRaises(CaptureFailure):
            self.transcoder.convert([injected], timeout_seconds=10)

    def test_duration_and_segment_count_bounds(self):
        sources = [self.make_aac(i) for i in range(1, 4)]
        with self.assertRaises(CaptureFailure):
            self.transcoder.convert(sources + [sources[0]], timeout_seconds=10)
        with self.assertRaises(CaptureFailure):
            self.transcoder.convert(sources, timeout_seconds=0)

    def test_output_collision_is_never_overwritten(self):
        source = self.make_aac(1)
        target = self.workspace / 'capture.wav'
        target.write_bytes(b'keep')
        with self.assertRaises(CaptureFailure) as error:
            self.transcoder.convert([source], timeout_seconds=10)
        self.assertEqual(error.exception.code, 'output_collision')
        self.assertEqual(target.read_bytes(), b'keep')

    def test_exit_failure_timeout_oversized_stderr_bad_format_and_duration_cleanup(self):
        source = self.make_aac(1)
        failure_cases = [
            (SimpleNamespace(returncode=1, stdout=b'', stderr=b'ffmpeg failed'), 'ffmpeg_failed'),
            (SimpleNamespace(returncode=-9, stdout=b'', stderr=b''), 'ffmpeg_failed'),
            (SimpleNamespace(returncode=0, stdout=b'', stderr=b'x' * (1024 * 1024 + 1)), 'ffmpeg_stderr_too_large'),
        ]
        for result, expected in failure_cases:
            with patch('radioflix.timefree.capture.argv._probe_aac_sample_rate', return_value=(44100, 1)):
                with patch('radioflix.timefree.capture.argv.subprocess.run', return_value=result):
                    with self.assertRaises(CaptureFailure) as error:
                        self.transcoder.convert([source], timeout_seconds=10)
            self.assertEqual(error.exception.code, expected)
            self.assertEqual(list(self.workspace.glob('.capture-*.wav')), [])

        with patch('radioflix.timefree.capture.argv._probe_aac_sample_rate', return_value=(44100, 1)):
            with patch('radioflix.timefree.capture.argv.subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 1)):
                with self.assertRaises(CaptureFailure) as error:
                    self.transcoder.convert([source], timeout_seconds=1)
        self.assertEqual(error.exception.code, 'ffmpeg_timeout')
        self.assertEqual(list(self.workspace.glob('.capture-*.wav')), [])

        def bad_output(argv, **kwargs):
            Path(argv[-1]).write_bytes(b'not a wav')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        with patch('radioflix.timefree.capture.argv._probe_aac_sample_rate', return_value=(44100, 1)):
            with patch('radioflix.timefree.capture.argv.subprocess.run', side_effect=bad_output):
                with self.assertRaises(CaptureFailure) as error:
                    self.transcoder.convert([source], timeout_seconds=10)
        self.assertEqual(error.exception.code, 'ffmpeg_output_invalid')
        self.assertFalse((self.workspace / 'capture.wav').exists())

        def wrong_duration(argv, **kwargs):
            with wave.open(argv[-1], 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(44100)
                out.writeframes(b'\x00\x00')
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        with patch('radioflix.timefree.capture.argv._probe_aac_sample_rate', return_value=(44100, 1)):
            with patch('radioflix.timefree.capture.argv.subprocess.run', side_effect=wrong_duration):
                with self.assertRaises(CaptureFailure) as error:
                    self.transcoder.convert([source], timeout_seconds=10)
        self.assertEqual(error.exception.code, 'ffmpeg_duration_mismatch')
        self.assertFalse((self.workspace / 'capture.wav').exists())


if __name__ == '__main__':
    unittest.main()


def _riff_chunk(name, payload):
    return name + struct.pack('<I', len(payload)) + payload + (b'\x00' if len(payload) & 1 else b'')


def _drop_last_adts_frame(data):
    offset = 0
    last = 0
    while offset + 7 <= len(data):
        frame_length = ((data[offset + 3] & 3) << 11) | (data[offset + 4] << 3) | (data[offset + 5] >> 5)
        if frame_length < 7 or offset + frame_length > len(data):
            break
        last = offset
        offset += frame_length
    return data[:last] if last else data
