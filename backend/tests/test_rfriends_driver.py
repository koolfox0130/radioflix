"""Standalone PHP driver with fake at/atq/atrm and empty recorder scripts.

Set RADIOFLIX_TEST_PHP_COMMAND to a JSON command prefix if PHP is containerized.
The tests never access Docker's API or the real rfriends3 filesystem themselves.
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from radioflix.schemas.reservations import JST


PHP = json.loads(os.environ.get('RADIOFLIX_TEST_PHP_COMMAND', 'null'))
if PHP is None and shutil.which('php'):
    PHP = [shutil.which('php')]

FAKE_AT = '''<?php
$root = __DIR__;
$statefile = $root.'/queue.json';
$jobs = file_exists($statefile) ? json_decode(file_get_contents($statefile), true) : [];
$operation = $argv[1];
if ($operation === 'atq') {
    foreach ($jobs as $id => $body) echo "$id\\tThu Jan 01 12:00:00 2030 a user\\n";
} elseif ($operation === 'atrm') {
    if (file_exists($root.'/fail-cancel')) exit(1);
    unset($jobs[$argv[2]]);
    file_put_contents($statefile, json_encode($jobs));
} elseif ($argv[2] === '-c') {
    if (!isset($jobs[$argv[3]])) exit(1);
    echo $jobs[$argv[3]];
} else {
    if (file_exists($root.'/fail-create')) exit(1);
    $id = count($jobs) ? max(array_keys($jobs)) + 1 : 100;
    $jobs[$id] = stream_get_contents(STDIN);
    file_put_contents($statefile, json_encode($jobs));
}
'''


@unittest.skipUnless(PHP, 'PHP CLI unavailable; use the documented isolated container command')
class DriverTests(unittest.TestCase):
    def setUp(self):
        root = Path('/tmp/radioflix-driver-tests')
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'rfriends'
        self.rsv = self.base / 'rsv'
        self.rsv.mkdir(parents=True)
        scripts = self.base / 'script'
        scripts.mkdir()
        for name in ['rfriends_rec.php', 'rfriends_rec_fin.php', 'rf_inc.php']:
            (scripts / name).write_text('<?php throw new Exception("must not execute during reservation operations");')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.bin / 'fake_at.php').write_text(FAKE_AT)
        for name in ['at', 'atq', 'atrm']:
            executable = self.bin / name
            executable.write_text(f'#!/bin/sh\nexec php "{self.bin}/fake_at.php" {name} "$@"\n')
            executable.chmod(0o755)
        start = datetime.now(JST).replace(microsecond=0) + timedelta(days=1)
        self.job = {'id': 'a' * 32, 'station': 'TBS', 'region': 'JP13', 'title': 'Test Program',
                    'starts_at': start.isoformat(), 'ends_at': (start + timedelta(hours=2)).isoformat()}
        self.config = {'base': str(self.base), 'tmp': str(self.root), 'queue': 'a'}
        self.source = (Path(__file__).parents[1] / 'radioflix/adapters/rfriends_driver.php').read_text().removeprefix('<?php\n')

    def run_driver(self, operation):
        # PATH contains only test at commands plus the interpreter/system tools.
        prefix = 'putenv(' + json.dumps(f'PATH={self.bin}:/usr/local/bin:/usr/bin:/bin') + ');\n'
        payload = base64.b64encode(json.dumps({'operation': operation, 'job': self.job, 'config': self.config}).encode()).decode()
        result = subprocess.run(PHP + ['-r', prefix + self.source, payload], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, 'Standalone test PHP failed')
        self.assertFalse(result.stderr, 'Standalone test PHP emitted diagnostics')
        return json.loads(result.stdout)

    def queue(self):
        path = self.bin / 'queue.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def test_create_inspect_cancel_and_idempotency(self):
        first = self.run_driver('create')
        self.assertEqual(first['state'], 'scheduled')
        self.assertEqual(self.run_driver('create')['job_id'], first['job_id'])
        self.assertEqual(len(self.queue()), 1)
        self.assertEqual(self.run_driver('inspect')['state'], 'scheduled')
        data = (self.rsv / (first['name'] + '.dat')).read_text().split()
        self.assertEqual(len(data), 19)
        self.assertEqual(data[6], 'TBS')
        self.assertEqual(data[14], 'JP13')
        self.assertEqual(self.run_driver('cancel')['state'], 'cancelled')
        self.assertFalse(self.queue())
        self.assertFalse(list(self.rsv.glob('*.dat')))
        self.assertEqual(self.run_driver('cancel')['state'], 'cancelled')
        self.assertEqual(self.run_driver('inspect')['state'], 'cancelled')

    def test_existing_native_reservation_is_untouched(self):
        start = datetime.fromisoformat(self.job['starts_at']).strftime('%Y%m%d%H%M%S')
        end = datetime.fromisoformat(self.job['ends_at']).strftime('%Y%m%d%H%M%S')
        original = f'{start} {end} 07200 0 0 0 TBS Native ; ; ; ; ; ; JP13 ; ; ; ;\n'
        native = self.rsv / 'native.dat'
        native.write_text(original)
        self.assertEqual(self.run_driver('create')['error'], 'conflict')
        self.assertEqual(native.read_text(), original)
        self.assertFalse(self.queue())
        self.assertEqual(self.run_driver('cancel')['state'], 'absent')
        self.assertEqual(native.read_text(), original)

    def test_changed_owned_file_cannot_be_cancelled(self):
        first = self.run_driver('create')
        path = self.rsv / (first['name'] + '.dat')
        path.write_text('external modification')
        self.assertEqual(self.run_driver('cancel')['error'], 'ownership')
        self.assertEqual(path.read_text(), 'external modification')
        self.assertEqual(len(self.queue()), 1)

    def test_partial_registration_can_be_retried_without_duplication(self):
        failure = self.bin / 'fail-create'
        failure.touch()
        self.assertEqual(self.run_driver('create')['error'], 'unknown')
        self.assertEqual(self.run_driver('inspect')['state'], 'absent')
        failure.unlink()
        self.assertEqual(self.run_driver('create')['state'], 'scheduled')
        self.assertEqual(len(self.queue()), 1)

    def test_failed_cancel_keeps_job_and_data(self):
        self.run_driver('create')
        (self.bin / 'fail-cancel').touch()
        self.assertEqual(self.run_driver('cancel')['error'], 'unknown')
        self.assertEqual(self.run_driver('inspect')['state'], 'scheduled')
        self.assertEqual(len(list(self.rsv.glob('*.dat'))), 1)

    def test_lost_submission_receipt_recovers_by_job_ownership(self):
        self.run_driver('create')
        journal = self.rsv / '.radioflix' / (self.job['id'] + '.json.submitted')
        journal.unlink()
        self.assertEqual(self.run_driver('inspect')['state'], 'scheduled')
        self.assertTrue(journal.exists())
        self.assertEqual(len(self.queue()), 1)

    def test_lost_journal_does_not_claim_absence_or_remove_job(self):
        self.run_driver('create')
        (self.rsv / '.radioflix' / (self.job['id'] + '.json')).unlink()
        self.assertEqual(self.run_driver('inspect')['error'], 'ownership')
        self.assertEqual(self.run_driver('cancel')['error'], 'ownership')
        self.assertEqual(len(self.queue()), 1)

    def test_started_job_cannot_be_cancelled(self):
        self.run_driver('create')
        (self.bin / 'queue.json').write_text('{}')
        (self.rsv / '.radioflix' / (self.job['id'] + '.json.started')).write_text('started')
        self.assertEqual(self.run_driver('inspect')['state'], 'running')
        self.assertEqual(self.run_driver('cancel')['error'], 'too_late')

    def test_invalid_identifier_and_region_do_not_create_files(self):
        self.job['id'] = '../escape'
        self.assertEqual(self.run_driver('create')['error'], 'incompatible')
        self.assertFalse(list(self.rsv.iterdir()))
        self.job['id'] = 'a' * 32
        self.job['region'] = 'JP999'
        self.assertEqual(self.run_driver('create')['error'], 'incompatible')

    def test_too_late_never_schedules(self):
        self.job['starts_at'] = (datetime.now(JST) + timedelta(seconds=100)).isoformat()
        self.job['ends_at'] = (datetime.now(JST) + timedelta(hours=1)).isoformat()
        self.assertEqual(self.run_driver('create')['error'], 'too_late')
        self.assertFalse(self.queue())


if __name__ == '__main__':
    unittest.main()
