import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radioflix.timefree.bootstrap import BootstrapBlocked, ProductionBootstrap, read_manifest, verify_sources


class BootstrapManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_root = self.root / 'sources'
        (self.source_root / 'script').mkdir(parents=True)
        self.source = self.source_root / 'script' / 'rf_timefree.php'
        self.source.write_text('<?php function safe_source() {}', encoding='utf-8')
        self.manifest = self.root / 'manifest.json'
        self.write_manifest(hashlib.sha256(self.source.read_bytes()).hexdigest())

    def write_manifest(self, digest):
        self.manifest.write_text(json.dumps({
            'schema_version': 1,
            'sources': [{'relative_path': 'script/rf_timefree.php', 'purpose': 'test',
                         'sha256': digest, 'required': True, 'functions': ['safe_source']}],
        }), encoding='utf-8')

    def test_allowlisted_source_fingerprint(self):
        verify_sources(self.source_root, self.manifest)
        self.assertEqual(read_manifest(self.manifest)[0].relative_path, 'script/rf_timefree.php')

    def test_missing_source_fails(self):
        self.source.unlink()
        with self.assertRaises(BootstrapBlocked) as error:
            verify_sources(self.source_root, self.manifest)
        self.assertEqual(error.exception.code, 'source_missing')

    def test_hash_mismatch_fails(self):
        self.source.write_text('<?php function changed() {}', encoding='utf-8')
        with self.assertRaises(BootstrapBlocked) as error:
            verify_sources(self.source_root, self.manifest)
        self.assertEqual(error.exception.code, 'source_fingerprint')

    def test_path_traversal_manifest_rejected(self):
        data = json.loads(self.manifest.read_text())
        data['sources'][0]['relative_path'] = '../rf_timefree.php'
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(BootstrapBlocked) as error:
            read_manifest(self.manifest)
        self.assertEqual(error.exception.code, 'source_manifest_invalid')

    def test_symlink_source_rejected(self):
        outside = self.root / 'outside.php'
        outside.write_text(self.source.read_text())
        self.source.unlink()
        self.source.symlink_to(outside)
        with self.assertRaises(BootstrapBlocked):
            verify_sources(self.source_root, self.manifest)


class BootstrapGateTests(unittest.TestCase):
    def test_timefree_gate_is_independent_of_reservation_gate(self):
        bootstrap = ProductionBootstrap(source_root=Path('/unavailable'), manifest=Path('/unavailable'))
        row = {'job_id': 'a' * 32, 'execution_kind': 'live', 'state': 'running'}
        with patch.dict(os.environ, {'RFRIENDS_ENABLE_WRITES': '0', 'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '0'}):
            with self.assertRaises(BootstrapBlocked) as error:
                bootstrap.run(row, Path('/tmp'))
        self.assertEqual(error.exception.code, 'writes_disabled')
        self.assertFalse(bootstrap.ready)
        with patch.dict(os.environ, {'RFRIENDS_ENABLE_WRITES': '0', 'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '1'}):
            self.assertTrue(bootstrap._gates_enabled())
            with self.assertRaises(BootstrapBlocked) as error:
                bootstrap.run(row, Path('/tmp'))
            self.assertNotEqual(error.exception.code, 'writes_disabled')
            self.assertEqual(error.exception.code, 'metadata_invalid')
        with patch.dict(os.environ, {'RFRIENDS_ENABLE_WRITES': '1', 'RADIOFLIX_TIMEFREE_ENABLE_WRITES': '0'}):
            self.assertFalse(bootstrap._gates_enabled())

if __name__ == '__main__':
    unittest.main()
