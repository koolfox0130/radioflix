"""Control transport, start guard, atomic publication and recovery; test roots only."""
import hashlib
import json
import os
import socket
import stat
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from radioflix.timefree.control import (Controller, Dispatch, create_app, prepare_socket_directory,
                                        prepare_socket_path, production_app,
                                        secure_socket_permissions)
from radioflix.timefree.preflight import Preflight
from radioflix.timefree.publisher import Publisher, rename_noreplace
from radioflix.timefree.service import TimefreeService
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.transport import WorkerClient
from radioflix.timefree.worker import TimefreeWorker, completed_assets
from radioflix.schemas.reservations import RecordingError
import test_timefree


class ReadyAudio(test_timefree.FakeAudio):
    ready = True


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.t = test_timefree.TimefreeTests()
        self.t.setUp()
        self.addCleanup(self.t.doCleanups)
        if os.getenv('RADIOFLIX_TIMEFREE_TEST_OUTPUT'):
            volume = tempfile.TemporaryDirectory(dir=os.environ['RADIOFLIX_TIMEFREE_TEST_OUTPUT'])
            self.addCleanup(volume.cleanup)
            self.t.output = Path(volume.name) / 'published'
        self.legacy = self.t.root / 'legacy'
        self.legacy.mkdir()
        self.t.output.mkdir()
        self.guard = Preflight(self.t.store, self.t.guide.native_dir, [self.legacy], self.t.output)
        self.worker = TimefreeWorker(self.t.store, self.t.output, ReadyAudio(),
                                    clock=lambda: self.t.now, preflight=self.guard)
        self.controller = Controller(self.worker, gate=lambda: True)  # constructor-only fixture gate
        self.app = create_app(self.controller)
        self.client = TestClient(self.app)

    def queue(self):
        return self.t.post().json()

    def state(self, row):
        return self.t.store.get(row['job_id'])['state']

    def test_transport_dispatch_and_authoritative_metadata(self):
        row = self.queue()
        response = self.client.post('/dispatch', json={'job_id': row['job_id']})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {'job_id': row['job_id'], 'accepted': True})
        self.assertEqual(self.controller.tick(), row['job_id'])
        self.assertEqual(self.state(row), 'completed')

    def test_dispatch_survives_control_restart_and_duplicate_request(self):
        row = self.queue()
        self.assertIsNone(self.controller.tick())  # registration alone cannot launch
        for _ in range(2): self.controller.dispatch(row['job_id'])
        self.assertEqual(self.t.store.pending_dispatches(), [row['job_id']])
        restarted = Controller(self.worker, gate=lambda: True)
        self.assertEqual(restarted.tick(), row['job_id'])
        self.assertEqual(self.state(row), 'completed')
        self.assertIsNone(restarted.tick())

    def test_completed_db_output_mismatch_is_not_trusted(self):
        row = self.queue()
        self.worker.run_once(row['job_id'])
        with self.t.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET output_path='../outside'")
        reader = TimefreeService(self.t.store, self.t.guide.service, output_root=self.t.output)
        self.assertEqual(reader.get(row['job_id'])['state'], 'unknown')
        self.worker.reconcile()
        self.assertEqual(self.state(row), 'unknown')
        self.worker.reconcile()  # actual file + original intent can repair the DB
        self.assertEqual(self.state(row), 'completed')
        self.assertEqual(self.t.store.get(row['job_id'])['output_path'], row['job_id'] + '/audio.wav')

    def test_injection_invalid_id_and_metadata_rejected(self):
        for value in ['../../x', 'a'*32+';id', '$(id)', 'a'*32+'\n', 'A'*32, '']:
            self.assertEqual(self.client.post('/dispatch', json={'job_id': value}).status_code, 422)
            with patch('radioflix.timefree.transport.UnixConnection') as connect:
                with self.assertRaises(ValueError): WorkerClient('/unused').dispatch(value)
                connect.assert_not_called()
        row = self.queue()
        for key in ['command', 'broadcast', 'output_path', 'execution_kind']:
            self.assertEqual(self.client.post('/dispatch', json={'job_id': row['job_id'], key: 'bad'}).status_code, 422)
        self.assertEqual(self.state(row), 'queued')

    def test_native_unknown_never_starts(self):
        row = self.queue()
        (self.t.guide.native_dir / 'bad.dat').write_text('malformed')
        with patch.object(self.worker.transport, 'run') as run:
            self.worker.run_once(row['job_id'])
            run.assert_not_called()
        self.assertEqual(self.state(row), 'failed')
        self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'native_unknown')

    def test_native_conflict_added_after_registration(self):
        row = self.queue()
        path = self.t.guide.native_dir / 'late.dat'
        path.write_text('20300107120000 20300107130000 3600 0 0 0 JORF native')
        before = path.read_bytes()
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'failed')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'native_conflict')

    def test_unknown_native_station_and_legacy_missing_catalog_block(self):
        row = self.queue()
        path = self.t.guide.native_dir / 'unknown.dat'
        path.write_text('20300107120000 20300107130000 3600 0 0 0 NOTRADIKO native')
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'native_unknown')
        path.unlink()
        row = self.queue()
        with self.t.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET station_ids='[]' WHERE job_id=?", (row['job_id'],))
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'native_unknown')

    def test_existing_recording_rechecked_read_only(self):
        row = self.queue()
        path = self.legacy / 'JORF_Show_20300107_1200_1300.m4a'
        path.write_bytes(b'existing-even-if-incomplete')
        before = path.read_bytes()
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'failed')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'recording_exists')

    def test_uncertain_recording_inventory_blocks(self):
        row = self.queue()
        (self.legacy / 'unknown.wav').write_bytes(b'?')
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'failed')

    def test_duplicate_timefree_rechecked(self):
        row = self.queue()
        with self.t.store.transaction() as db:
            old = dict(db.execute('SELECT * FROM timefree_jobs').fetchone())
            old['job_id'] = 'f'*32
            old['broadcast_episode_id'] = 'e'*64
            keys = ','.join(old)
            db.execute(f'INSERT INTO timefree_jobs ({keys}) VALUES ({",".join("?" for _ in old)})', tuple(old.values()))
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'duplicate_job')

    def test_metadata_identity_rechecked(self):
        for field, value in [('station', 'TBS'), ('start_at', '2030-01-07T11:00:00+09:00'), ('broadcast_episode_id', 'e'*64)]:
            with self.subTest(field=field):
                row = self.queue()
                with self.t.store.transaction() as db:
                    db.execute(f'UPDATE timefree_jobs SET {field}=? WHERE job_id=?', (value, row['job_id']))
                self.worker.run_once(row['job_id'])
                self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'metadata_mismatch')

    def test_atomic_publish_hides_staging(self):
        row = self.queue()
        def observe(source, target):
            self.assertFalse(target.exists())
            self.assertTrue((source / 'audio.wav').is_file())
            self.assertTrue((source / 'manifest.json').is_file())
            self.assertEqual(completed_assets(self.t.store, self.t.output, include_fixture=True), [])
            rename_noreplace(source, target)
        with patch('radioflix.timefree.publisher.rename_noreplace', side_effect=observe):
            self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'completed')
        self.assertEqual(len(completed_assets(self.t.store, self.t.output, include_fixture=True)), 1)

    def test_atomic_empty_directory_collision_no_overwrite(self):
        row = self.queue()
        def collide(source, target):
            target.mkdir()
            rename_noreplace(source, target)
        with patch('radioflix.timefree.publisher.rename_noreplace', side_effect=collide):
            self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'unknown')
        self.assertEqual(list((self.t.output / row['job_id']).iterdir()), [])
        self.worker.reconcile()
        self.assertEqual(self.state(row), 'unknown')

    def test_stop_before_atomic_rename_retains_hidden_temp(self):
        row = self.queue()
        with patch('radioflix.timefree.publisher.rename_noreplace', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'running')
        self.worker.reconcile()
        self.assertEqual(self.state(row), 'unknown')
        self.assertFalse((self.t.output / row['job_id']).exists())
        self.assertTrue(list((self.t.output / '.staging').iterdir()))
        self.assertEqual(completed_assets(self.t.store, self.t.output, include_fixture=True), [])

    def test_stop_after_publish_recovers_without_recording(self):
        row = self.queue()
        with patch.object(self.worker, 'completed', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'running')
        restarted = TimefreeWorker(TimefreeStore(self.t.store.path), self.t.output, ReadyAudio(lambda _: self.fail('recording')))
        restarted.reconcile()
        self.assertEqual(self.state(row), 'completed')
        self.assertIsNone(restarted.run_once())

    def test_running_without_process_is_unknown(self):
        row = self.queue()
        with self.t.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET state='running'")
        self.worker.reconcile()
        self.assertEqual(self.state(row), 'unknown')
        self.assertIsNone(self.controller.tick())

    def test_real_process_kill_and_restart(self):
        import multiprocessing
        context = multiprocessing.get_context('fork')
        for after_publish in (False, True):
            with self.subTest(after_publish=after_publish):
                # Each crash uses a separate fixture database/output root.
                fixture = test_timefree.TimefreeTests()
                fixture.setUp()
                try:
                    row = fixture.post().json()
                    reached = context.Event()
                    def stop_here(*args):
                        reached.set()
                        time.sleep(30)
                    def child():
                        worker = fixture.worker(ReadyAudio(None if after_publish else stop_here))
                        if after_publish:
                            worker.completed = stop_here
                        worker.run_once(row['job_id'])
                    process = context.Process(target=child)
                    process.start()
                    try:
                        self.assertTrue(reached.wait(10))
                        self.assertEqual(fixture.store.get(row['job_id'])['state'], 'running')
                    finally:
                        process.kill()
                        process.join(5)
                    self.assertFalse(process.is_alive())
                    fixture.worker(ReadyAudio(lambda _: self.fail('redownload'))).reconcile()
                    self.assertEqual(fixture.store.get(row['job_id'])['state'],
                                     'completed' if after_publish else 'unknown')
                finally:
                    fixture.doCleanups()

    def test_output_without_ownership_proof_not_adopted(self):
        row = self.queue()
        self.worker.run_once(row['job_id'])
        with self.t.store.transaction() as db:
            db.execute('DELETE FROM timefree_publications')
            db.execute("UPDATE timefree_jobs SET state='running'")
        self.worker.reconcile()
        self.assertEqual(self.state(row), 'unknown')

    def test_completed_missing_or_corrupt_output_is_unknown(self):
        for damage in ('missing', 'truncated', 'manifest'):
            with self.subTest(damage=damage):
                # Reuse the same completed job; restore the original file each time.
                if damage == 'missing':
                    row = self.queue()
                    self.worker.run_once(row['job_id'])
                    output = self.t.output / row['job_id'] / 'audio.wav'
                    original = output.read_bytes()
                    output.unlink()
                elif damage == 'truncated':
                    output.write_bytes(b'bad')
                else:
                    output.write_bytes(original)
                    (output.parent / 'manifest.json').write_text('{}')
                with self.t.store.transaction() as db: db.execute("UPDATE timefree_jobs SET state='completed'")
                self.worker.reconcile()
                self.assertEqual(self.state(row), 'unknown')
                self.assertEqual(completed_assets(self.t.store, self.t.output, include_fixture=True), [])

    def test_orphan_temp_never_promoted(self):
        self.worker.publisher.prepare_root()
        orphan = self.t.output / '.staging' / 'abandoned'
        orphan.mkdir(); (orphan / 'audio.wav').write_bytes(b'partial')
        self.queue()
        self.worker.reconcile()
        self.assertEqual((orphan / 'audio.wav').read_bytes(), b'partial')
        self.assertEqual(completed_assets(self.t.store, self.t.output, include_fixture=True), [])

    def test_backend_restart_dispatches_only_persisted_id(self):
        row = self.queue()
        with self.t.store.transaction() as db: db.execute("UPDATE timefree_jobs SET execution_kind='live'")
        from unittest.mock import Mock
        dispatcher = Mock()
        service = TimefreeService(TimefreeStore(self.t.store.path), self.t.guide.service, dispatcher=dispatcher)
        with patch('radioflix.timefree.service.timefree_gate', return_value=True):
            service.dispatch_pending()
        dispatcher.dispatch.assert_called_once_with(row['job_id'])
        self.assertEqual(self.state(row), 'queued')
        self.worker.transport.kind = 'live'
        with patch('radioflix.timefree.worker.timefree_gate', return_value=True):
            self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'completed')

    def test_gate_zero_no_dispatch_or_capture(self):
        row = self.queue()
        controller = Controller(self.worker)  # actual double gate; environment stays OFF
        client = TestClient(create_app(controller))
        with patch.object(self.worker, 'run_once') as run:
            self.assertEqual(client.post('/dispatch', json={'job_id': row['job_id']}).status_code, 409)
            self.assertIsNone(controller.tick())
            run.assert_not_called()
        with patch('radioflix.timefree.transport.UnixConnection') as connection:
            self.assertFalse(WorkerClient('/unused').dispatch(row['job_id']))
            connection.assert_not_called()

    def test_read_only_boot_skips_schema_migration_reconcile_and_filesystem_writes(self):
        ident = 'a' * 32
        item = self.t.item
        with self.t.store.transaction() as db:
            db.execute('''INSERT INTO timefree_jobs(job_id,broadcast_episode_id,station,title,start_at,end_at,
                state,created_at,snapshot,deadline,execution_kind) VALUES (?,?,?,?,?,?,'queued',?,?,?,'live')''',
                (ident, item['id'], item['station'], item['title'], item['starts_at'], item['ends_at'],
                 self.t.now.isoformat(), json.dumps(item), '2099-01-01T00:00:00+09:00'))
        before_db = hashlib.sha256(self.t.store.path.read_bytes()).hexdigest()
        before_root = {p.relative_to(self.t.output).as_posix():
                       (p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns,
                        hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
                       for p in self.t.output.rglob('*')}
        read_only_store = TimefreeStore(self.t.store.path, read_only=True)
        read_only_worker = TimefreeWorker(read_only_store, self.t.output, ReadyAudio(),
                                          preflight=lambda _: self.fail('preflight in disabled mode'))
        controller = Controller(read_only_worker, gate=lambda: True)
        app = create_app(controller)
        endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, 'path')}
        self.assertEqual(endpoints['/health'](), {
            'capture_ready': True, 'writes_enabled': False,
            'boot_mode': 'disabled_read_only', 'reason': 'boot_mode_disabled'})
        self.assertEqual(endpoints['/status']()['job_count'], 1)
        with self.assertRaises(HTTPException) as error:
            endpoints['/dispatch'](Dispatch(job_id=ident))
        self.assertEqual(error.exception.detail, {'code': 'boot_mode_disabled'})
        self.assertIsNone(controller.tick())
        self.assertFalse(read_only_worker.reconcile())
        self.assertIsNone(read_only_worker.run_once(ident))
        self.assertEqual(hashlib.sha256(self.t.store.path.read_bytes()).hexdigest(), before_db)
        self.assertEqual(before_root, {p.relative_to(self.t.output).as_posix():
                                      (p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns,
                                       hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
                                      for p in self.t.output.rglob('*')})
        self.assertFalse(Path(str(self.t.store.path) + '.timefree.lock').exists())

    def test_read_only_store_never_creates_database_or_schema(self):
        path = self.t.root / 'absent' / 'jobs.sqlite3'
        store = TimefreeStore(path, read_only=True)
        self.assertEqual(store.list(), [])
        with self.assertRaisesRegex(RuntimeError, 'writes_disabled'):
            with store.transaction():
                self.fail('read-only transaction entered')
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())

    def test_cancel_is_rejected_before_read_only_store_access_when_gates_off(self):
        path = self.t.root / 'cancel-readonly' / 'jobs.sqlite3'
        service = TimefreeService(TimefreeStore(path, read_only=True), self.t.guide.service)
        with patch('radioflix.timefree.service.timefree_gate', return_value=False):
            with self.assertRaises(RecordingError) as error:
                service.cancel('a' * 32)
        self.assertEqual(error.exception.code, 'writes_disabled')
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())

    def test_production_app_stays_read_only_without_capture_approval(self):
        db_path = self.t.root / 'production-mode-check' / 'radioflix.sqlite3'
        output = self.t.root / 'production-mode-check' / 'publish'
        environment = {
            'RADIOFLIX_DB_PATH': str(db_path),
            'RADIOFLIX_TIMEFREE_ROOT': str(output),
            'RADIOFLIX_TIMEFREE_BOOT_MODE': 'enabled',
            'RFRIENDS_ENABLE_WRITES': '0',
            'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '1',
        }
        with patch.dict(os.environ, environment, clear=False):
            app = production_app()
            self.assertTrue(app.state.controller.worker.read_only)
            self.assertTrue(app.state.controller.worker.store.read_only)
            endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, 'path')}
            self.assertEqual(endpoints['/health']()['boot_mode'], 'disabled_read_only')
            self.assertEqual(endpoints['/status']()['job_count'], 0)
        self.assertFalse(db_path.exists())
        self.assertFalse(output.exists())

    def test_disabled_startup_and_tick_never_reconcile(self):
        readonly = TimefreeWorker(TimefreeStore(self.t.store.path, read_only=True),
                                  self.t.output, ReadyAudio())
        controller = Controller(readonly, gate=lambda: True)
        with patch.object(readonly, 'reconcile') as reconcile:
            self.assertIsNone(controller.tick())
            reconcile.assert_not_called()

    def test_socket_directory_permissions_and_stale_socket_cleanup(self):
        directory = self.t.root / 'socket-dir'
        directory.mkdir(mode=0o770)
        directory.chmod(0o770)
        info = prepare_socket_directory(directory)
        self.assertEqual(info.stat().st_mode & 0o777, 0o770)
        stale_path = directory / 'control.sock'
        owned_socket = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=os.geteuid(),
                                       st_ino=101, st_dev=202)
        with patch.object(Path, 'lstat', return_value=owned_socket), \
             patch('radioflix.timefree.control.socket.socket') as connect, \
             patch.object(Path, 'unlink') as unlink:
            connect.return_value.connect.side_effect = OSError(111, 'connection refused')
            prepare_socket_path(stale_path)
            unlink.assert_called_once_with()
            connect.return_value.close.assert_called_once()
        with patch.object(Path, 'lstat', return_value=owned_socket), \
             patch('radioflix.timefree.control.socket.socket') as connect, \
             patch.object(Path, 'unlink') as unlink:
            with self.assertRaisesRegex(RuntimeError, 'socket_already_active'):
                prepare_socket_path(stale_path)
            unlink.assert_not_called()
        live_socket = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o666, st_uid=os.geteuid(),
                                      st_gid=os.getegid())
        secured_socket = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=os.geteuid(),
                                         st_gid=os.getegid())
        with patch.object(Path, 'lstat', side_effect=[live_socket, secured_socket]), \
             patch('radioflix.timefree.control.os.chmod') as chmod:
            secure_socket_permissions(stale_path)
            chmod.assert_called_once_with(stale_path, 0o660, follow_symlinks=False)
        invalid = directory / 'not-a-socket'
        invalid.write_text('keep')
        with self.assertRaisesRegex(RuntimeError, 'socket_path_invalid'):
            prepare_socket_path(invalid)
        self.assertEqual(invalid.read_text(), 'keep')

    def test_backend_restart_checks_completed_files_before_worker_reconcile(self):
        row = self.queue()
        self.worker.run_once(row['job_id'])
        (self.t.output / row['job_id'] / 'audio.wav').unlink()
        restarted = TimefreeService(TimefreeStore(self.t.store.path), self.t.guide.service,
                                    output_root=self.t.output)
        self.assertEqual(restarted.get(row['job_id'])['state'], 'unknown')
        self.assertEqual(self.state(row), 'completed')  # read-only API, worker owns journal repair
        Controller(self.worker).tick()  # gate OFF now skips recovery mutation entirely
        self.assertEqual(self.state(row), 'completed')

    def test_existing_radioflix_reservation_job_blocks_capture(self):
        row = self.queue()
        with self.t.store.transaction() as db:
            db.execute('CREATE TABLE recording_jobs (payload TEXT, state TEXT)')
            db.execute('INSERT INTO recording_jobs VALUES (?,?)', (json.dumps(row['broadcast']), 'running'))
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.t.store.get(row['job_id'])['error_code'], 'radioflix_recording_conflict')

    def test_unrelated_native_and_normal_recording_files_remain_unchanged(self):
        row = self.queue()
        native = self.t.guide.native_dir / 'other.dat'
        native.write_text('20300107120000 20300107130000 3600 0 0 0 TBS native')
        recording = self.legacy / 'TBS_Show_20300107_1200_1300.m4a'
        recording.write_bytes(b'normal audio')
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (native, recording)}
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'completed')
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (native, recording)})

    def test_native_conflict_before_publish_is_not_exposed(self):
        row = self.queue()
        def native_arrives(_):
            (self.t.guide.native_dir / 'new.dat').write_text('20300107120000 20300107130000 3600 0 0 0 JORF native')
        self.worker.transport = ReadyAudio(native_arrives)
        self.worker.run_once(row['job_id'])
        self.assertEqual(self.state(row), 'failed')
        self.assertFalse((self.t.output / row['job_id']).exists())

    def test_symlink_managed_root_refused(self):
        link = self.t.root / 'link'
        link.symlink_to(self.legacy, target_is_directory=True)
        with self.assertRaises(ValueError): Publisher(link, self.t.store).prepare_root()
        self.assertEqual(list(self.legacy.iterdir()), [])

    def test_socket_transport_end_to_end(self):
        # A real Unix-domain HTTP connection, without any TCP network.
        import uvicorn
        row = self.queue()
        uds = str(self.t.root / 'control.sock')
        server = uvicorn.Server(uvicorn.Config(self.app, uds=uds, log_level='critical', access_log=False))
        thread = threading.Thread(target=server.run)
        thread.start()
        try:
            for _ in range(100):
                if server.started: break
                time.sleep(.02)
            self.assertTrue(server.started)
            client = WorkerClient(uds)
            self.assertTrue(client.ready())
            with patch('radioflix.timefree.transport.timefree_gate', return_value=True):
                self.assertTrue(client.dispatch(row['job_id']))
            for _ in range(150):
                if self.state(row) == 'completed': break
                time.sleep(.02)
        finally:
            server.should_exit = True
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.state(row), 'completed')


if __name__ == '__main__':
    unittest.main()
