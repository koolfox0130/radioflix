import unittest
from datetime import datetime, timedelta, timezone

from radioflix.timefree.capture.area_policy import (
    NormalAreaCandidate, configured_area_mismatch, select_normal_area_candidates,
)
from radioflix.timefree.capture.source.errors import SourceFailure
from radioflix.timefree.capture.source.models import HttpRequest, HttpResponse
from radioflix.timefree.capture.source.station_area import StationAreaSource
from radioflix.timefree.capture.source.transport import FakeHttpTransport


UTC = timezone.utc
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


def candidate(station='LFR', seconds=180, *, areafree=0, end=NOW - timedelta(minutes=1), expiry=NOW + timedelta(days=1)):
    return NormalAreaCandidate(station, end - timedelta(seconds=seconds), end, expiry, areafree)


class NormalAreaPolicyTests(unittest.TestCase):
    def test_configured_area_equal_to_authenticated(self):
        self.assertFalse(configured_area_mismatch('JP13', 'JP13'))

    def test_configured_area_different_from_authenticated_is_diagnostic_only(self):
        self.assertTrue(configured_area_mismatch('JP13', 'JP27'))

    def test_station_in_authenticated_area_is_allowed(self):
        result = select_normal_area_candidates([candidate()], {'LFR': 'JP13'}, 'JP13', NOW)
        self.assertEqual(len(result), 1)

    def test_station_outside_authenticated_area_is_rejected(self):
        self.assertEqual(select_normal_area_candidates(
            [candidate()], {'LFR': 'JP13'}, 'JP27', NOW), ())

    def test_unknown_station_area_is_rejected(self):
        self.assertEqual(select_normal_area_candidates([candidate()], {}, 'JP13', NOW), ())

    def test_malformed_station_area_is_rejected(self):
        self.assertEqual(select_normal_area_candidates(
            [candidate()], {'LFR': 'Tokyo'}, 'JP13', NOW), ())

    def test_areafree_candidate_is_excluded(self):
        self.assertEqual(select_normal_area_candidates(
            [candidate(areafree=1)], {'LFR': 'JP13'}, 'JP13', NOW), ())
        self.assertEqual(select_normal_area_candidates(
            [candidate(areafree=True)], {'LFR': 'JP13'}, 'JP13', NOW), ())

    def test_shortest_local_safe_candidate_is_selected_first(self):
        items = [candidate('LFR', 600), candidate('TBS', 240), candidate('QRR', 180)]
        mapping = {'LFR': 'JP13', 'TBS': 'JP13', 'QRR': 'JP13'}
        selected = select_normal_area_candidates(items, mapping, 'JP13', NOW)
        self.assertEqual([item.station_id for item in selected], ['QRR', 'TBS', 'LFR'])

    def test_no_local_candidate_is_empty(self):
        self.assertEqual(select_normal_area_candidates(
            [candidate('CRK')], {'CRK': 'JP27'}, 'JP13', NOW), ())

    def test_candidate_requires_timefree_expiry_and_not_currently_airing(self):
        expired = candidate(expiry=NOW)
        current = candidate(end=NOW + timedelta(seconds=1))
        self.assertEqual(select_normal_area_candidates(
            [expired, current], {'LFR': 'JP13'}, 'JP13', NOW), ())

    def test_invalid_area_metadata_fails_closed(self):
        with self.assertRaises(ValueError):
            configured_area_mismatch('JP13', 'JP999')
        with self.assertRaises(ValueError):
            select_normal_area_candidates([], {}, 'JP13', datetime(2026, 1, 1))


class StationAreaSourceTests(unittest.TestCase):
    def test_official_station_region_xml_maps_station_to_area(self):
        transport = FakeHttpTransport([HttpResponse(200, body=(
            b'<region><stations><station><id>LFR</id><area_id>JP13</area_id></station>'
            b'<station><id>CRK</id><area_id>JP28</area_id></station></stations></region>'))])
        mapping = StationAreaSource(transport).load()
        self.assertEqual(mapping, {'LFR': 'JP13', 'CRK': 'JP28'})
        request = transport.requests[0]
        self.assertEqual((request.method, request.url),
                         ('GET', 'https://radiko.jp/v3/station/region/full.xml'))

    def test_malformed_or_ambiguous_station_is_unresolved(self):
        body = (
            b'<region><stations>'
            b'<station><id>LFR</id><area_id>Tokyo</area_id></station>'
            b'<station><id>CRK</id><area_id>JP28</area_id></station>'
            b'<station><id>QRR</id><area_id>JP13</area_id></station>'
            b'<station><id>QRR</id><area_id>JP13</area_id></station>'
            b'<station><id>!invalid</id><area_id>JP13</area_id></station>'
            b'</stations></region>'
        )
        catalog = StationAreaSource(FakeHttpTransport([HttpResponse(200, body=body)])).load_catalog()
        mapping = catalog.area_by_station
        self.assertEqual(mapping, {'CRK': 'JP28'})
        self.assertEqual(catalog.station_ids, frozenset({'LFR', 'CRK', 'QRR'}))
        self.assertEqual(select_normal_area_candidates(
            [candidate('LFR'), candidate('QRR'), candidate('CRK')], mapping, 'JP28', NOW),
            (candidate('CRK'),))

    def test_invalid_xml_document_and_doctype_are_rejected(self):
        for body in (b'<!DOCTYPE region [<!ENTITY x "bad">]><region>&x;</region>', b'<wrong/>'):
            with self.subTest(body_kind=len(body)):
                with self.assertRaises(SourceFailure):
                    StationAreaSource(FakeHttpTransport([HttpResponse(200, body=body)])).load()

    def test_only_malformed_station_rows_produce_no_mapping(self):
        body = b'<region><station><id>LFR</id><area_id>JP999</area_id></station></region>'
        with self.assertRaises(SourceFailure):
            StationAreaSource(FakeHttpTransport([HttpResponse(200, body=body)])).load()

    def test_http_failure_is_rejected(self):
        with self.assertRaises(SourceFailure):
            StationAreaSource(FakeHttpTransport([HttpResponse(503, body=b'')])).load()


if __name__ == '__main__':
    unittest.main()
