"""Capture adapter security tests using offline ports and synthetic WAV only."""

import inspect
import os
import stat
import subprocess
import tempfile
import unittest
import wave
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from radioflix.schemas.reservations import JST
from radioflix.timefree.capture.adapter import CaptureAdapter
from radioflix.timefree.capture.argv import FfmpegArgvTranscoder
from radioflix.timefree.capture.errors import CaptureFailure, CaptureNotReady
from radioflix.timefree.capture.fixture import (FixtureAuthenticator, FixtureMediaFetcher,
                                                FixturePlaylistProvider, SyntheticAudioTranscoder)
from radioflix.timefree.capture.production import ProductionCaptureAdapter
from radioflix.timefree.service import deadline
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker, completed_assets
import test_timefree


class CaptureAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_timefree.TimefreeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.output.mkdir(parents=True)
        self.auth = FixtureAuthenticator()
        self.playlist = FixturePlaylistProvider()
        self.media = FixtureMediaFetcher()
        self.transcoder = SyntheticAudioTranscoder(self.duration)
        self.preflight_calls = []

    @property
    def duration(self):
        item = self.fixture.item
        return int((datetime.fromisoformat(item['ends_at']) - datetime.fromisoformat(item['starts_at'])).total_seconds())

    def queued(self):
        return self.fixture.post().json()

    def running(self):
        row = self.queued()
        with self.fixture.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET state='running' WHERE job_id=?", (row['job_id'],))
        return row

    def make_adapter(self, **overrides):
        args = {
            'store': self.fixture.store,
            'managed_root': self.fixture.output,
            'authenticator': self.auth,
            'playlist_provider': self.playlist,
            'media_fetcher': self.media,
            'transcoder': self.transcoder,
            'preflight': lambda row: self.preflight_calls.append(row['job_id']),
            'clock': lambda: self.fixture.now,
        }
        args.update(overrides)
        return CaptureAdapter(**args)

    def assert_capture_error(self, adapter, ident, code):
        with self.assertRaises(CaptureFailure) as error:
            with adapter.capture_job(ident):
                self.fail('capture should fail before yielding')
        self.assertEqual(error.exception.code, code)

    def test_fixture_pipeline_runs_through_worker_and_publisher(self):
        row = self.queued()
        adapter = self.make_adapter()
        worker = TimefreeWorker(self.fixture.store, self.fixture.output, adapter,
                                clock=lambda: self.fixture.now)
        self.assertEqual(worker.run_once(row['job_id']), row['job_id'])
        self.assertEqual(self.fixture.store.get(row['job_id'])['state'], 'completed')
        self.assertEqual(len(completed_assets(self.fixture.store, self.fixture.output, include_fixture=True)), 1)
        self.assertEqual(self.preflight_calls, [row['job_id']])
        self.assertTrue(self.auth.calls and self.playlist.calls and self.media.calls and self.transcoder.calls)
        self.assertEqual(list(adapter.work_root.iterdir()), [])

    def test_capture_job_accepts_only_job_id_input(self):
        self.assertEqual(list(inspect.signature(CaptureAdapter.capture_job).parameters), ['self', 'requested_id'])

    def test_invalid_job_id(self):
        self.assert_capture_error(self.make_adapter(), 'g' * 32, 'invalid_job_id')

    def test_path_traversal_job_id(self):
        self.assert_capture_error(self.make_adapter(), '../' + 'a' * 32, 'invalid_job_id')

    def test_absolute_path_job_id(self):
        self.assert_capture_error(self.make_adapter(), '/tmp/radioflix-output', 'invalid_job_id')

    def test_shell_metacharacters_in_job_id(self):
        self.assert_capture_error(self.make_adapter(), 'a' * 32 + ';touch', 'invalid_job_id')

    def test_invalid_station_rejected_before_auth(self):
        row = self.running()
        with self.fixture.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET station='JORF;touch' WHERE job_id=?", (row['job_id'],))
        self.assert_capture_error(self.make_adapter(), row['job_id'], 'job_metadata_invalid')
        self.assertEqual(self.auth.calls, [])

    def test_invalid_start_time_rejected(self):
        row = self.running()
        with self.fixture.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET start_at='not-a-date' WHERE job_id=?", (row['job_id'],))
        self.assert_capture_error(self.make_adapter(), row['job_id'], 'job_metadata_invalid')

    def test_invalid_end_time_rejected(self):
        row = self.running()
        with self.fixture.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET end_at='2000-01-01T00:00:00+09:00' WHERE job_id=?", (row['job_id'],))
        self.assert_capture_error(self.make_adapter(), row['job_id'], 'job_metadata_invalid')

    def test_naive_start_time_rejected(self):
        row = self.running()
        with self.fixture.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET start_at='2030-01-01T12:00:00' WHERE job_id=?", (row['job_id'],))
        self.assert_capture_error(self.make_adapter(), row['job_id'], 'job_metadata_invalid')

    def test_expired_job_rejected_before_auth(self):
        row = self.running()
        from radioflix.timefree.service import eligibility
        from radioflix.schemas.reservations import Broadcast
        cutoff = deadline(Broadcast.model_validate(row['broadcast']))
        adapter = self.make_adapter(clock=lambda: cutoff)
        self.assert_capture_error(adapter, row['job_id'], 'job_expired')
        self.assertEqual(self.auth.calls, [])

    def test_duplicate_rechecked_before_auth(self):
        row = self.running()
        with self.fixture.store.transaction() as db:
            columns = [c[1] for c in db.execute('PRAGMA table_info(timefree_jobs)')]
            old = dict(db.execute('SELECT * FROM timefree_jobs WHERE job_id=?', (row['job_id'],)).fetchone())
            old.update(job_id='f' * 32, broadcast_episode_id='e' * 64, state='queued')
            db.execute(f"INSERT INTO timefree_jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       [old[c] for c in columns])
        self.assert_capture_error(self.make_adapter(), row['job_id'], 'duplicate_job')
        self.assertEqual(self.auth.calls, [])

    def test_native_state_unknown_blocks_before_auth(self):
        row = self.running()
        adapter = self.make_adapter(preflight=lambda _: (_ for _ in ()).throw(CaptureFailure('native_unknown')))
        self.assert_capture_error(adapter, row['job_id'], 'native_unknown')
        self.assertEqual(self.auth.calls, [])

    def test_absolute_and_traversal_media_output_rejected(self):
        row = self.running()
        outside = self.fixture.root / 'outside.ts'
        outside.write_bytes(b'fixture')
        media = self.make_adapter(media_fetcher=FixtureMediaFetcher(traversal=True))
        self.assert_capture_error(media, row['job_id'], 'media_invalid')
        self.assertTrue(outside.is_file())

    def test_auth_failure_is_sanitized(self):
        row = self.running()
        self.assert_capture_error(self.make_adapter(authenticator=FixtureAuthenticator(fail=True)),
                                  row['job_id'], 'auth_failed')

    def test_playlist_failure_is_sanitized(self):
        row = self.running()
        self.assert_capture_error(self.make_adapter(playlist_provider=FixturePlaylistProvider(fail=True)),
                                  row['job_id'], 'playlist_failed')

    def test_invalid_playlist_scheme_rejected(self):
        class BadPlaylist:
            def resolve(self, *_args, **_kwargs):
                return SimpleNamespace(url='https://unapproved.invalid/media.m3u8')
        row = self.running()
        self.assert_capture_error(self.make_adapter(playlist_provider=BadPlaylist()), row['job_id'], 'playlist_invalid')

    def test_media_failure_is_sanitized(self):
        row = self.running()
        self.assert_capture_error(self.make_adapter(media_fetcher=FixtureMediaFetcher(fail=True)),
                                  row['job_id'], 'media_failed')

    def test_media_timeout_maps_to_safe_code(self):
        row = self.running()
        self.assert_capture_error(self.make_adapter(media_fetcher=FixtureMediaFetcher(timeout=True)),
                                  row['job_id'], 'capture_timeout')

    def test_ffmpeg_failure_is_sanitized(self):
        row = self.running()
        transcoder = SyntheticAudioTranscoder(self.duration, fail=True)
        self.assert_capture_error(self.make_adapter(transcoder=transcoder), row['job_id'], 'ffmpeg_failed')

    def test_ffmpeg_timeout_maps_to_safe_code(self):
        row = self.running()
        transcoder = SyntheticAudioTranscoder(self.duration, timeout=True)
        self.assert_capture_error(self.make_adapter(transcoder=transcoder), row['job_id'], 'capture_timeout')

    def test_ffmpeg_argument_injection_is_shell_free(self):
        row = self.running()
        snapshot = row['broadcast']
        snapshot['title'] = '$(touch /tmp/pwned); `id`'
        import json
        with self.fixture.store.transaction() as db:
            db.execute('UPDATE timefree_jobs SET snapshot=? WHERE job_id=?', (json.dumps(snapshot), row['job_id']))
        executable = Path(os.environ.get('RADIOFLIX_TEST_EXEC_ROOT', self.fixture.root)) / 'allowlisted' / 'ffmpeg'
        executable.parent.mkdir(exist_ok=True)
        executable.write_bytes(b'fixture executable')
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        ffmpeg = FfmpegArgvTranscoder(executable, preflight_allowlisted_path=executable)
        self.assertEqual(executable.resolve(), ffmpeg.preflight_allowlisted_path.resolve())
        self.assertTrue(os.access(executable.resolve(), os.X_OK))

        def controlled_run(argv, **kwargs):
            self.assertIsInstance(argv, list)
            self.assertFalse(kwargs['shell'])
            self.assertEqual(argv[0], str(executable))
            self.assertNotIn(snapshot['title'], argv)
            self.assertIn('-protocol_whitelist', argv)
            self.assertIn('-n', argv)
            destination = Path(argv[-1])
            with wave.open(str(destination), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(1); audio.setframerate(1)
                audio.writeframes(b'\x80' * self.duration)
            return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')

        adapter = self.make_adapter(transcoder=ffmpeg)
        with patch('radioflix.timefree.capture.argv.subprocess.run', side_effect=controlled_run) as run:
            with adapter.capture_job(row['job_id']) as result:
                self.assertTrue(result.audio_path.is_file())
        run.assert_called_once()

    def test_ffmpeg_executable_requires_allowlist(self):
        executable = self.fixture.root / 'unapproved' / 'ffmpeg'
        executable.parent.mkdir()
        executable.write_bytes(b'fixture executable')
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        with self.assertRaises(CaptureFailure) as error:
            FfmpegArgvTranscoder(executable)._executable()
        self.assertEqual(error.exception.code, 'ffmpeg_not_allowlisted')

    def test_truncated_audio_rejected(self):
        row = self.running()
        transcoder = SyntheticAudioTranscoder(self.duration, truncated=True)
        self.assert_capture_error(self.make_adapter(transcoder=transcoder), row['job_id'], 'truncated_audio')

    def test_zero_byte_audio_rejected(self):
        row = self.running()
        transcoder = SyntheticAudioTranscoder(self.duration, zero_bytes=True)
        self.assert_capture_error(self.make_adapter(transcoder=transcoder), row['job_id'], 'audio_invalid')

    def test_wrong_audio_format_rejected(self):
        row = self.running()
        transcoder = SyntheticAudioTranscoder(self.duration, wrong_format=True)
        self.assert_capture_error(self.make_adapter(transcoder=transcoder), row['job_id'], 'audio_invalid')

    def test_output_collision_never_overwrites(self):
        row = self.running()
        media = FixtureMediaFetcher(output_collision=True)
        self.assert_capture_error(self.make_adapter(media_fetcher=media), row['job_id'], 'output_collision')

    def test_work_directory_cleaned_after_success_and_failure(self):
        row = self.running()
        adapter = self.make_adapter()
        with adapter.capture_job(row['job_id']) as result:
            workspace = result.workspace
            self.assertTrue(workspace.exists())
        self.assertFalse(workspace.exists())
        row = self.running()
        adapter = self.make_adapter(authenticator=FixtureAuthenticator(fail=True))
        with self.assertRaises(CaptureFailure):
            with adapter.capture_job(row['job_id']):
                pass
        self.assertEqual(list(adapter.work_root.iterdir()), [])

    def test_worker_interruption_recovers_without_replay(self):
        row = self.queued()

        class InterruptedMedia(FixtureMediaFetcher):
            def download(self, *_args, **_kwargs):
                raise KeyboardInterrupt()

        adapter = self.make_adapter(media_fetcher=InterruptedMedia())
        worker = TimefreeWorker(self.fixture.store, self.fixture.output, adapter,
                                clock=lambda: self.fixture.now)
        with self.assertRaises(KeyboardInterrupt):
            worker.run_once(row['job_id'])
        self.assertEqual(self.fixture.store.get(row['job_id'])['state'], 'running')
        self.assertEqual(list(adapter.work_root.iterdir()), [])
        worker.reconcile()
        self.assertEqual(self.fixture.store.get(row['job_id'])['state'], 'unknown')
        self.assertFalse((self.fixture.output / row['job_id']).exists())

    def test_gate_off_production_adapter_does_not_run_ports(self):
        row = self.running()
        production = ProductionCaptureAdapter(store=self.fixture.store, managed_root=self.fixture.output,
                                              preflight=lambda _: self.fail('preflight must not run'))
        with patch.dict(os.environ, {'RFRIENDS_ENABLE_WRITES': '0', 'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '0'}):
            with self.assertRaises(CaptureNotReady):
                with production.capture_job(row['job_id']):
                    self.fail('production capture must not yield')

    def test_production_adapter_not_ready_and_bridge_unapproved(self):
        production = ProductionCaptureAdapter(store=self.fixture.store, managed_root=self.fixture.output,
                                              preflight=lambda _: None)
        self.assertFalse(production.ready)
        self.assertFalse(production.bridge_approved)
        with self.assertRaises(CaptureNotReady):
            with production.capture_job('a' * 32):
                pass


if __name__ == '__main__':
    unittest.main()
