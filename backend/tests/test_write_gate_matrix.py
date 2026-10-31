"""The reservation and Timefree gates must stay independent and offline."""
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from radioflix.api.timefree import TimefreeRequest
from radioflix.services.reservation_service import reservation_writes_enabled
from radioflix.timefree.service import TimefreeService
from radioflix.timefree.store import TimefreeStore
from test_schedule import GuideTests


class FixtureDispatcher:
    """Records admission only; it never starts a worker or network request."""
    def __init__(self):
        self.jobs = []

    def ready(self):
        return True

    def dispatch(self, job_id):
        self.jobs.append(job_id)


class WriteGateMatrixTests(unittest.TestCase):
    def test_four_gate_combinations_are_independent(self):
        cases = (
            ('both_off', '0', '0', False, False),
            ('timefree_only', '0', '1', False, True),
            ('reservations_only', '1', '0', True, False),
            ('both_on_fixture', '1', '1', True, True),
        )
        for name, rfriends, timefree, reservation_allowed, timefree_allowed in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as root, \
                 patch.dict(os.environ, {
                     'RFRIENDS_ENABLE_WRITES': rfriends,
                     'RADIOFLIX_TIMEFREE_ENABLE_WRITES': timefree,
                 }, clear=False):
                guide = GuideTests()
                guide.setUp()
                try:
                    # Existing reservation service is fixture-backed; only its
                    # native-gateway permission follows RFRIENDS_ENABLE_WRITES.
                    guide.res.writes_enabled = reservation_writes_enabled()
                    reservation = guide.res.create(
                        {'id': 'matrix-program', 'title': guide.broadcast.title},
                        guide.broadcast, 'once')
                    self.assertEqual(reservation['state'], 'active' if reservation_allowed else 'waiting_write')
                    self.assertEqual(bool(guide.gateway.creates), reservation_allowed)

                    now = guide.res.clock()
                    item = guide.service.adapter.day((now - timedelta(days=1)).date())['broadcasts'][0]
                    item['metadata'].update(failed_record='0', ts_in_ng='0', ts_out_ng='0')
                    guide.service.adapter.day = lambda *args, **kwargs: {
                        'availability': 'ok', 'broadcasts': [item]}
                    dispatcher = FixtureDispatcher()
                    store = TimefreeStore(os.path.join(root, 'timefree.sqlite3'))
                    service = TimefreeService(store, guide.service, clock=lambda: now,
                                              dispatcher=dispatcher, fixture=False)
                    request = TimefreeRequest(
                        broadcast_episode_id=item['id'], schedule_revision=item['schedule_revision'],
                        date=item['starts_at'][:10])

                    if timefree_allowed:
                        row = service.create(request)
                        self.assertEqual(row['state'], 'queued')
                        self.assertEqual(dispatcher.jobs, [row['job_id']])
                    else:
                        from radioflix.schemas.reservations import RecordingError
                        with self.assertRaises(RecordingError) as error:
                            service.create(request)
                        self.assertEqual(error.exception.code, 'writes_disabled')
                        self.assertEqual(dispatcher.jobs, [])
                        self.assertFalse(store.path.exists())
                finally:
                    guide.doCleanups()


if __name__ == '__main__':
    unittest.main()
