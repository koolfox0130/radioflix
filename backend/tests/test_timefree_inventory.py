"""Filename inventory parsing must stay conservative and read-only."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from radioflix.schemas.reservations import JST
from radioflix.timefree.preflight import RecordingInventory, StartBlocked, _parse_recording_name


def broadcast(station='LFR', start='2026-10-10T01:30:00+09:00', end='2026-10-10T02:00:00+09:00'):
    return SimpleNamespace(station=station, starts_at=datetime.fromisoformat(start),
                           ends_at=datetime.fromisoformat(end))


class RecordingNameTests(unittest.TestCase):
    def test_existing_canonical_name(self):
        parsed = _parse_recording_name('LFR_Show_20261010_0102_0300.m4a')
        self.assertEqual(parsed, ('LFR', datetime(2026, 10, 10, 1, 2, tzinfo=JST),
                                  datetime(2026, 10, 10, 3, 0, tzinfo=JST)))

    def test_documented_short_marker_name(self):
        parsed = _parse_recording_name('[SHT]LFR_霜降り明星のオールナイトニッポン_20261010_0102_0300.m4a')
        self.assertEqual(parsed, ('LFR', datetime(2026, 10, 10, 1, 2, tzinfo=JST),
                                  datetime(2026, 10, 10, 3, 0, tzinfo=JST)))

    def test_title_delimiters_unicode_and_long_title(self):
        title = '長い_番組名[特別]_' + ('番組' * 100)
        parsed = _parse_recording_name(f'LFR_{title}_20261010_0102_0300.m4a')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], 'LFR')

    def test_malformed_date_and_unknown_marker_are_unresolved(self):
        for name in ('LFR_Show_20260230_0102_0300.m4a',
                     '[BAD]LFR_Show_20261010_0102_0300.m4a',
                     'unstructured.m4a', '../LFR_Show_20261010_0102_0300.m4a',
                     'LFR_../Show_20261010_0102_0300.m4a'):
            with self.subTest(name=name):
                self.assertIsNone(_parse_recording_name(name))

    def test_unexpected_extension_is_not_parsed(self):
        self.assertIsNone(_parse_recording_name('LFR_Show_20261010_0102_0300.flac'))


class RecordingInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inventory = RecordingInventory([self.root])

    def touch(self, name, data=b''):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_short_marker_recording_blocks_full_scheduled_window(self):
        self.touch('[SHT]LFR_霜降り明星のオールナイトニッポン_20261010_0102_0300.m4a', b'partial')
        with self.assertRaisesRegex(StartBlocked, 'recording_exists'):
            self.inventory.check(broadcast())

    def test_nonoverlapping_recording_does_not_block(self):
        self.touch('LFR_Other_20261010_0102_0300.m4a', b'partial')
        self.inventory.check(broadcast(start='2026-10-10T03:00:00+09:00',
                                        end='2026-10-10T03:30:00+09:00'))

    def test_different_station_does_not_block(self):
        self.touch('LFR_Other_20261010_0102_0300.m4a', b'partial')
        self.inventory.check(broadcast(station='TBS'))

    def test_zero_byte_audio_still_blocks_duplicate(self):
        self.touch('LFR_Show_20261010_0102_0300.m4a')
        with self.assertRaisesRegex(StartBlocked, 'recording_exists'):
            self.inventory.check(broadcast())

    def test_non_audio_payload_with_recording_name_still_blocks_duplicate(self):
        self.touch('LFR_Show_20261010_0102_0300.m4a', b'not an audio container')
        with self.assertRaisesRegex(StartBlocked, 'recording_exists'):
            self.inventory.check(broadcast())

    def test_malformed_audio_fails_closed(self):
        self.touch('unknown.m4a', b'not audio')
        with self.assertRaisesRegex(StartBlocked, 'recordings_unknown'):
            self.inventory.check(broadcast())

    def test_symlink_fails_closed(self):
        target = self.root / 'target.m4a'
        target.write_bytes(b'audio')
        (self.root / 'LFR_Show_20261010_0102_0300.m4a').symlink_to(target)
        with self.assertRaisesRegex(StartBlocked, 'recordings_unknown'):
            self.inventory.check(broadcast())

    def test_unexpected_audio_extension_is_not_silently_accepted_as_name(self):
        self.assertIsNone(_parse_recording_name('LFR_Show_20261010_0102_0300.flac'))

    def test_short_marker_does_not_change_other_names(self):
        names = ('TBS_JUNK-Show_20261010_0102_0300.m4a',
                 'QRR_Title_with_delimiter_20261010_0102_0300.mp3',
                 'FMJ_長い番組名_20261010_0102_0300.aac')
        for name in names:
            with self.subTest(name=name):
                self.assertIsNotNone(_parse_recording_name(name))


if __name__ == '__main__':
    unittest.main()
