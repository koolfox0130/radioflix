"""Normal and completed-timefree catalogue/API integration using temporary roots."""
import hashlib
import json
import tempfile
import unittest
import wave
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radioflix.services.program_service import ProgramService
from radioflix.services.recording_catalog import RecordingCatalog
from radioflix.timefree.publisher import Publisher
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker
from radioflix.timefree.preflight import RecordingInventory, _parse_recording_name


class NoCapture:
    kind = 'production'

    def run(self, *_args, **_kwargs):
        raise AssertionError('catalog/recovery must not capture')


class RecordingCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.normal_root = self.root / 'normal'
        self.normal_root.mkdir()
        self.publish_root = self.root / 'timefree'
        self.publish_root.mkdir()
        self.db_path = self.root / 'catalog.sqlite3'
        self.store = TimefreeStore(self.db_path)
        self.job_id = 'a' * 32
        self.episode_id = 'b' * 64
        self.broadcast = {
            'id': self.episode_id, 'station': 'CRK', 'station_name': 'ラジオ関西',
            'title': '心に光を', 'starts_at': '2026-10-22T06:00:00+09:00',
            'ends_at': '2026-10-22T06:05:00+09:00', 'metadata': {},
        }
        self.row = {
            'job_id': self.job_id, 'broadcast_episode_id': self.episode_id,
            'station': 'CRK', 'title': self.broadcast['title'],
            'start_at': self.broadcast['starts_at'], 'end_at': self.broadcast['ends_at'],
            'state': 'running', 'created_at': '2026-10-29T00:00:00+09:00',
            'snapshot': self.broadcast, 'deadline': '2026-11-01T05:00:00+09:00',
            'execution_kind': 'production',
        }
        with self.store.transaction() as db:
            db.execute('''INSERT INTO timefree_jobs(job_id,broadcast_episode_id,station,title,start_at,end_at,
                state,created_at,snapshot,deadline,execution_kind) VALUES (?,?,?,?,?,?,'running',?,?,?,?)''',
                (self.job_id, self.episode_id, 'CRK', self.broadcast['title'], self.broadcast['starts_at'],
                 self.broadcast['ends_at'], self.row['created_at'], json.dumps(self.broadcast),
                 self.row['deadline'], self.row['execution_kind']))
        self.source_wav = self.root / 'source.wav'
        with wave.open(str(self.source_wav), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
            audio.writeframes(b'\0\0' * (8000 * 300))
        self.row['broadcast'] = self.broadcast
        self.manifest = Publisher(self.publish_root, self.store).publish(self.row, self.source_wav, 300)
        with self.store.transaction() as db:
            db.execute('''UPDATE timefree_jobs SET state='completed',completed_at=?,output_path=?,
                output_sha256=?,output_size=?,duration=? WHERE job_id=?''',
                ('2026-10-29T00:01:00+09:00', self.manifest['relative_path'], self.manifest['sha256'],
                 self.manifest['size'], self.manifest['duration'], self.job_id))
        self.programs = ProgramService(self.normal_root)
        self.catalog = RecordingCatalog(self.programs, self.store, self.publish_root)

    def api_client(self):
        import app as app_module
        test_app = FastAPI()
        test_app.add_api_route('/api/programs', app_module.programs)
        test_app.add_api_route('/api/programs/{program_id}', app_module.program_detail)
        test_app.add_api_route('/api/programs/{program_id}/episodes', app_module.program_episodes)
        test_app.add_api_route('/audio/{program_id}/{filename:path}', app_module.audio_file)
        test_app.add_api_route('/api/audio/{program_id}/{filename:path}', app_module.audio_file)
        patches = (patch.object(app_module, 'program_service', self.programs),
                   patch.object(app_module, 'recording_catalog', self.catalog),
                   patch.object(app_module, 'RADIKO_DIR', self.normal_root))
        for item in patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        return TestClient(test_app)

    def test_completed_asset_flows_program_episode_and_audio_with_range(self):
        client = self.api_client()
        programs = client.get('/api/programs').json()
        matches = [p for p in programs if p['source'] == 'timefree']
        self.assertEqual(len(matches), 1)
        program = matches[0]
        self.assertEqual((program['station'], program['title'], program['category']),
                         ('CRK', '心に光を', 'タイムフリー'))
        self.assertTrue(program['id'].startswith('tf~'))
        detail = client.get('/api/programs/' + program['id']).json()
        self.assertEqual((detail['id'], detail['station'], detail['title'], detail['source']),
                         (program['id'], 'CRK', '心に光を', 'timefree'))
        episodes = client.get(f"/api/programs/{program['id']}/episodes").json()
        self.assertEqual(len(episodes), 1)
        episode = episodes[0]
        self.assertEqual(episode['episode_id'], 'timefree-' + self.episode_id)
        self.assertEqual(episode['source'], 'timefree')
        self.assertEqual((episode['station'], episode['title']), ('CRK', '心に光を'))
        self.assertEqual((episode['start_at'], episode['end_at']),
                         (self.broadcast['starts_at'], self.broadcast['ends_at']))
        self.assertAlmostEqual(episode['duration'], 300)
        self.assertEqual(episode['filename'], '20261022_0600_0605_tf-' + self.episode_id + '.wav')
        self.assertEqual(episode['size'], self.manifest['size'])

        full = client.get(episode['audio_url'])
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.headers['content-type'], 'audio/wav')
        self.assertEqual(int(full.headers['content-length']), self.manifest['size'])
        self.assertEqual(full.content[:4], b'RIFF')
        ranged = client.get(episode['audio_url'], headers={'Range': 'bytes=0-43'})
        self.assertEqual(ranged.status_code, 206)
        self.assertEqual(ranged.headers['content-range'], f'bytes 0-43/{self.manifest["size"]}')
        self.assertEqual(len(ranged.content), 44)
        invalid = client.get(episode['audio_url'], headers={'Range': 'bytes=999999999-'})
        self.assertEqual(invalid.status_code, 416)
        self.assertEqual(client.get(f"/api/audio/{program['id']}/../../etc/passwd").status_code, 404)

    def test_stable_ids_and_reconcile_do_not_republish(self):
        first = self.catalog.get_recorded_programs()[-1]
        first_episode = self.catalog.episodes(first['id'])[0]
        with self.db_path.open('rb') as _:
            reopened_store = TimefreeStore(self.db_path)
        reopened = RecordingCatalog(self.programs, reopened_store, self.publish_root)
        second = reopened.get_recorded_programs()[-1]
        second_episode = reopened.episodes(second['id'])[0]
        self.assertEqual((first['id'], first_episode['episode_id'], first_episode['filename']),
                         (second['id'], second_episode['episode_id'], second_episode['filename']))
        before = hashlib.sha256((self.publish_root / self.manifest['relative_path']).read_bytes()).hexdigest()
        for _ in range(3):
            TimefreeWorker(reopened_store, self.publish_root, NoCapture()).reconcile()
        row = reopened_store.get(self.job_id)
        self.assertEqual(row['state'], 'completed')
        self.assertEqual(reopened.episodes(second['id']), [second_episode])
        self.assertEqual(hashlib.sha256((self.publish_root / self.manifest['relative_path']).read_bytes()).hexdigest(), before)

    def test_fixture_jobs_are_hidden_by_default_and_visible_only_in_test_catalog(self):
        with self.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET execution_kind='fixture' WHERE job_id=?", (self.job_id,))
        manifest_path = self.publish_root / self.job_id / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['execution_kind'] = 'fixture'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
        intent = self.store.publication(self.job_id)
        intent['execution_kind'] = 'fixture'
        with self.store.transaction() as db:
            db.execute('UPDATE timefree_publications SET manifest=? WHERE job_id=?',
                       (json.dumps(intent, ensure_ascii=False, sort_keys=True), self.job_id))
        self.assertEqual(self.catalog.get_recorded_programs(), [])
        test_catalog = RecordingCatalog(self.programs, self.store, self.publish_root, include_fixture=True)
        self.assertEqual(len(test_catalog.get_recorded_programs()), 1)

    def test_unfinished_missing_manifest_and_symlink_assets_are_hidden(self):
        with self.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET state='running' WHERE job_id=?", (self.job_id,))
        self.assertEqual(self.catalog.get_recorded_programs(), [])
        with self.store.transaction() as db:
            db.execute("UPDATE timefree_jobs SET state='completed' WHERE job_id=?", (self.job_id,))
        audio = self.publish_root / self.manifest['relative_path']
        saved = audio.with_suffix('.saved')
        audio.rename(saved)
        self.assertEqual(self.catalog.get_recorded_programs(), [])
        saved.rename(audio)
        physical_manifest = self.publish_root / self.job_id / 'manifest.json'
        contents = physical_manifest.read_text()
        physical_manifest.write_text('{}')
        self.assertEqual(self.catalog.get_recorded_programs(), [])
        physical_manifest.write_text(contents)
        outside = self.root / 'outside.wav'
        outside.write_bytes(b'not audio')
        audio.unlink(); audio.symlink_to(outside)
        self.assertEqual(self.catalog.get_recorded_programs(), [])

    def test_normal_recording_wins_duplicate_without_changing_normal_program(self):
        folder = self.normal_root / 'CRK_心に光を'
        folder.mkdir()
        normal_name = 'CRK_心に光を_20261022_0600_0605.m4a'
        (folder / normal_name).write_bytes(b'normal recording fixture')
        before = self.programs.get_recorded_programs()
        catalog = RecordingCatalog(self.programs, self.store, self.publish_root)
        after = catalog.get_recorded_programs()
        self.assertEqual([p['id'] for p in before], [p['id'] for p in after if p['source'] == 'normal'])
        self.assertFalse(any(p['source'] == 'timefree' for p in after))
        normal_program = before[0]
        episodes = catalog.episodes(normal_program['id'])
        self.assertIsNone(episodes)

    def test_unresolved_normal_audio_hides_timefree_asset_fail_closed(self):
        (self.normal_root / 'CRK_ambiguous-name.m4a').write_bytes(b'unknown normal recording')
        catalog = RecordingCatalog(self.programs, self.store, self.publish_root)
        self.assertEqual(catalog.get_recorded_programs(), [])

    def test_590_normal_recordings_keep_their_catalog_identity_and_inventory(self):
        folder = self.normal_root / 'CRK_Recorded Show'
        folder.mkdir()
        first_day = datetime(2024, 1, 1)
        filenames = set()
        for index in range(590):
            day = (first_day + timedelta(days=index)).strftime('%Y%m%d')
            name = f'CRK_Recorded_Show_{day}_0100_0200.m4a'
            (folder / name).write_bytes(b'')
            filenames.add(name)
        original_programs = self.programs.get_recorded_programs()
        original = original_programs[0]
        before_episodes = {p.name for p in folder.iterdir() if p.suffix == '.m4a'}
        broadcast = type('Broadcast', (), {
            'station': 'CRK', 'starts_at': datetime.fromisoformat(self.broadcast['starts_at']),
            'ends_at': datetime.fromisoformat(self.broadcast['ends_at']),
        })()
        RecordingInventory([self.normal_root]).check(broadcast)
        parsed = [_parse_recording_name(name) for name in before_episodes]
        self.assertEqual(sum(item is not None for item in parsed), 590)
        before_intervals = {(station, start, end) for station, start, end in parsed if station}
        self.assertEqual(len(before_intervals), 590)

        catalog = RecordingCatalog(self.programs, self.store, self.publish_root)
        combined = catalog.get_recorded_programs()
        normal = [item for item in combined if item.get('source') == 'normal']
        self.assertEqual([item['id'] for item in original_programs], [item['id'] for item in normal])
        self.assertEqual((normal[0]['title'], normal[0]['raw_name']),
                         (original['title'], original['raw_name']))
        self.assertEqual(before_episodes, filenames)
        self.assertEqual(len(before_episodes), 590)
        after_parsed = [_parse_recording_name(name) for name in before_episodes]
        after_intervals = {(station, start, end) for station, start, end in after_parsed if station}
        self.assertEqual(after_intervals, before_intervals)
        RecordingInventory([self.normal_root]).check(broadcast)
        client = self.api_client()
        response = client.get(f"/api/programs/{original['id']}/episodes")
        self.assertEqual(response.status_code, 200)
        visible = response.json()
        self.assertEqual(len(visible), 590)
        self.assertEqual({item['filename'] for item in visible}, filenames)
        self.assertTrue(all(item['source'] == 'normal' for item in visible))
        normal_audio = client.get(f"/audio/{original['id']}/{next(iter(filenames))}")
        self.assertEqual(normal_audio.status_code, 200)
        self.assertEqual(normal_audio.headers['content-type'], 'audio/mp4')


if __name__ == '__main__':
    unittest.main()
