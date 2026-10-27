"""Safe Source API tests. All HTTP responses are synthetic and socket-free."""

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from radioflix.schemas.reservations import Broadcast, JST
from radioflix.timefree.capture.models import AuthContext, PlaylistReference
from radioflix.timefree.capture.adapter import CaptureAdapter
from radioflix.timefree.capture.fixture import SyntheticAudioTranscoder
from radioflix.timefree.capture.production import ProductionCaptureAdapter
from radioflix.timefree.capture.source.auth import RadikoAuthenticationSource
from radioflix.timefree.capture.source.errors import SourceCode, SourceFailure, SourceNotReady
from radioflix.timefree.capture.source.full_key import extract_pc_html5_full_key
from radioflix.timefree.capture.source.media import HlsMediaSource
from radioflix.timefree.capture.source.models import (HttpRequest, HttpResponse, RequestTimeout,
                                                       RetryPolicy, Secret)
from radioflix.timefree.capture.source.playlist import TimefreePlaylistSource
from radioflix.timefree.capture.source.production_auth import ProductionAuthenticator
from radioflix.timefree.capture.source.production_media import (MAX_PRODUCTION_SEGMENTS,
    ProductionMediaFetcher)
from radioflix.timefree.capture.source.transport import FakeHttpTransport, ProductionHttpTransport, validate_url
from radioflix.timefree.service import deadline
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker, completed_assets


DUMMY_TOKEN = 'TEST_ONLY_NOT_A_CREDENTIAL'
MASTER = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nmedia/index.m3u8\n'
MEDIA = b'#EXTM3U\n#EXTINF:1.0,fixture\nsegment-1.ts\n#EXT-X-ENDLIST\n'
AUTH = HttpResponse(200, body=json.dumps({'auth_token': DUMMY_TOKEN, 'area_id': 'fixture-area'}).encode())
TIMEFREE = HttpResponse(200, headers={'Content-Type': 'application/xml'}, body=(
    b'<urls><url areafree="0" timefree="1">'
    b'<playlist_create_url>https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/fixture/playlist.m3u8'
    b'</playlist_create_url></url></urls>'))
MASTER_RESPONSE = HttpResponse(200, body=MASTER)
MEDIA_RESPONSE = HttpResponse(200, body=MEDIA)
SEGMENT = HttpResponse(200, body=b'synthetic-segment-bytes')
METADATA = SimpleNamespace(
    station='JOAK',
    start_at=datetime(2025, 1, 1, 12, 0, tzinfo=JST),
    end_at=datetime(2025, 1, 1, 12, 5, tzinfo=JST),
)


class SafeSourceApiTests(unittest.TestCase):
    def auth_source(self, transport):
        return RadikoAuthenticationSource(transport, credential=Secret('FIXTURE_CREDENTIAL_ONLY'))

    def test_fake_authentication_success_keeps_secret_redacted(self):
        transport = FakeHttpTransport([AUTH])
        auth = self.auth_source(transport).authenticate(METADATA)
        self.assertEqual(auth.area_id, 'fixture-area')
        self.assertEqual(repr(auth.credential), 'Secret(<redacted>)')
        self.assertNotIn(DUMMY_TOKEN, repr(transport.requests[0]))
        self.assertNotIn(DUMMY_TOKEN, repr(auth))

    def test_auth_failure_is_structured_and_sanitized(self):
        with self.assertRaises(SourceFailure) as error:
            self.auth_source(FakeHttpTransport([HttpResponse(401)])).authenticate(METADATA)
        self.assertEqual(error.exception.code, SourceCode.AUTH_FAILED)
        self.assertNotIn(DUMMY_TOKEN, str(error.exception))

    def test_auth_malformed_response(self):
        with self.assertRaises(SourceFailure) as error:
            self.auth_source(FakeHttpTransport([HttpResponse(200, body=b'not json')])).authenticate(METADATA)
        self.assertEqual(error.exception.code, SourceCode.AUTH_FAILED)

    def test_current_pc_html5_full_key_extracts_before_applying_offsets(self):
        fixture_key = b'0123456789abcdef0123456789abcdef01234567'
        js = b'prefix RadikoJSPlayer(foo, "pc_html5", "' + fixture_key + b'", {options:true}) suffix'
        full_key = extract_pc_html5_full_key(js)
        self.assertEqual(len(full_key), 40)
        self.assertEqual(hashlib.sha256(full_key).hexdigest(), hashlib.sha256(fixture_key).hexdigest())

    def test_current_upstream_fallback_is_bounded_and_fingerprinted(self):
        full_key = extract_pc_html5_full_key(b'no supported player key')
        self.assertEqual(len(full_key), 40)
        self.assertEqual(hashlib.sha256(full_key).hexdigest(),
                         '7fda9e960ca6cc426db6df81066a1d2f98790bc7ede1678cf7d5fa345c934769')

    def test_production_authenticator_uses_current_normal_auth_contract(self):
        fixture_key = b'0123456789abcdef0123456789abcdef01234567'
        js = b'RadikoJSPlayer(x, "pc_html5", "' + fixture_key + b'", {x:1})'
        token = 'SYNTHETIC_AUTH1_TOKEN'
        transport = FakeHttpTransport([
            HttpResponse(200, headers={'Content-Type': 'application/javascript'}, body=js),
            HttpResponse(200, headers={
                'X-Radiko-AuthToken': token,
                'X-Radiko-KeyOffset': '3',
                'X-Radiko-KeyLength': '16',
            }),
            HttpResponse(200, body=b'JP13,\xe6\x9d\xb1\xe4\xba\xac'),
        ])
        auth = ProductionAuthenticator(transport).authenticate(METADATA)
        self.assertEqual(auth.area_id, 'JP13')
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual([r.method for r in transport.requests], ['GET', 'GET', 'GET'])
        self.assertEqual([r.url for r in transport.requests], [
            'https://radiko.jp/apps/js/playerCommon.js',
            'https://radiko.jp/v2/api/auth1',
            'https://radiko.jp/v2/api/auth2',
        ])
        self.assertEqual(set(transport.requests[1].headers), {
            'X-Radiko-App', 'X-Radiko-App-Version', 'X-Radiko-Device', 'X-Radiko-User',
        })
        self.assertEqual(set(transport.requests[2].headers), {
            'X-Radiko-Device', 'X-Radiko-User', 'X-Radiko-AuthToken', 'X-Radiko-PartialKey',
        })
        self.assertIsInstance(transport.requests[2].headers['X-Radiko-AuthToken'], Secret)
        self.assertIsInstance(transport.requests[2].headers['X-Radiko-PartialKey'], Secret)
        self.assertNotIn(token, repr(transport.requests[2]))
        self.assertNotIn(token, repr(auth))
        self.assertEqual(len(transport.requests[2].headers['X-Radiko-PartialKey'].reveal_for_transport()), 24)

    def test_production_authenticator_rejects_out_of_range_partial_key_before_auth2(self):
        js = b'RadikoJSPlayer(x, "pc_html5", "0123456789abcdef0123456789abcdef01234567", {x:1})'
        transport = FakeHttpTransport([
            HttpResponse(200, body=js),
            HttpResponse(200, headers={
                'X-Radiko-AuthToken': 'SYNTHETIC_AUTH1_TOKEN',
                'X-Radiko-KeyOffset': '39',
                'X-Radiko-KeyLength': '2',
            }),
        ])
        with self.assertRaises(SourceFailure) as error:
            ProductionAuthenticator(transport).authenticate(METADATA)
        self.assertEqual(error.exception.code, SourceCode.AUTH_FAILED)
        self.assertEqual(len(transport.requests), 2)

    def test_production_authenticator_preserves_not_ready_gate(self):
        with self.assertRaises(SourceNotReady):
            ProductionAuthenticator(ProductionHttpTransport()).authenticate(METADATA)

    def test_production_authenticator_never_uses_metadata_for_urls_or_premium(self):
        transport = FakeHttpTransport([
            HttpResponse(200, body=b'fallback'),
            HttpResponse(200, headers={
                'X-Radiko-AuthToken': 'SYNTHETIC_AUTH1_TOKEN',
                'X-Radiko-KeyOffset': '0', 'X-Radiko-KeyLength': '8',
            }),
            HttpResponse(200, body=b'JP13,synthetic'),
        ])
        malicious = SimpleNamespace(station='../../attacker', start_at='ignore', end_at='ignore', session='secret')
        ProductionAuthenticator(transport).authenticate(malicious)
        self.assertTrue(all(r.url.startswith('https://radiko.jp/') for r in transport.requests))
        self.assertTrue(all('session' not in r.url and 'cookie' not in r.url for r in transport.requests))

    def test_fake_playlist_and_hls_media_complete_through_same_sources(self):
        transport = FakeHttpTransport([AUTH, TIMEFREE, MASTER_RESPONSE, MEDIA_RESPONSE, SEGMENT])
        auth = self.auth_source(transport).authenticate(METADATA)
        playlist_source = TimefreePlaylistSource(transport)
        playlist = playlist_source.resolve(METADATA, auth)
        self.assertTrue(playlist.url.startswith(
            'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/fixture/playlist.m3u8?'))
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / 'media-input.ts'
            source = HlsMediaSource(transport, playlist_source, work_root=Path(root))
            self.assertEqual(source.download(playlist, auth, dest), dest)
            self.assertEqual(dest.read_bytes(), b'synthetic-segment-bytes')
            self.assertEqual(len(transport.requests), 5)
            self.assertEqual(transport.requests[1].method, 'GET')
            self.assertEqual(transport.requests[1].url,
                'https://radiko.jp/v3/station/stream/pc_html5/JOAK.xml')
            playlist_request = transport.requests[2]
            self.assertEqual(playlist_request.method, 'GET')
            query = parse_qs(urlsplit(playlist_request.url).query)
            self.assertEqual(query['station_id'], ['JOAK'])
            self.assertEqual(query['start_at'], ['20250101120000'])
            self.assertEqual(query['ft'], ['20250101120000'])
            self.assertEqual(query['end_at'], ['20250101120500'])
            self.assertEqual(query['to'], ['20250101120500'])
            self.assertEqual(query['preroll'], ['0'])
            self.assertEqual(query['seek'], ['20250101120000'])
            self.assertEqual(query['l'], ['300'])
            self.assertRegex(query['lsid'][0], r'^[a-f0-9]{32}$')
            self.assertEqual(query['type'], ['b'])
            self.assertEqual(playlist_request.headers['X-Radiko-AuthToken'], auth.credential)
            self.assertEqual(playlist_request.headers['X-Radiko-AreaId'], auth.area_id)
            self.assertTrue(all(request.method == 'GET' for request in transport.requests[1:]))

    def test_fake_source_api_flows_through_capture_worker_and_publisher(self):
        now = datetime.now(JST).replace(microsecond=0)
        start, end = now - timedelta(minutes=8), now - timedelta(minutes=7)
        episode = hashlib.sha256(f'JOAK:{start.isoformat()}:{end.isoformat()}'.encode()).hexdigest()
        broadcast = {
            'id': episode, 'station': 'JOAK', 'region': 'JP13', 'title': 'fixture only',
            'starts_at': start.isoformat(), 'ends_at': end.isoformat(),
            'metadata': {'failed_record': '0', 'ts_in_ng': '0', 'ts_out_ng': '0'},
        }
        job = 'a' * 32
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'managed'
            root.mkdir()
            store = TimefreeStore(Path(temporary) / 'db' / 'jobs.sqlite')
            with store.transaction() as db:
                db.execute('''INSERT INTO timefree_jobs(job_id,broadcast_episode_id,station,title,start_at,end_at,
                    state,created_at,snapshot,deadline,execution_kind,station_ids)
                    VALUES (?,?,?,?,?,?,'queued',?,?,?,?,?)''',
                    (job, episode, 'JOAK', 'fixture only', start.isoformat(), end.isoformat(), now.isoformat(),
                     json.dumps(broadcast), deadline(Broadcast.model_validate(broadcast)).isoformat(),
                     'fixture', '["JOAK"]'))
                store.event(db, job, 'queued', now.isoformat())
            transport = FakeHttpTransport([
                HttpResponse(200, body=b'{"auth_token":"SOURCE_FIXTURE_ONLY","area_id":"fixture"}'),
                TIMEFREE,
                HttpResponse(200, body=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nmedia.m3u8\n'),
                HttpResponse(200, body=b'#EXTM3U\n#EXTINF:1,fixture\nsegment.ts\n#EXT-X-ENDLIST\n'),
                HttpResponse(200, body=b'synthetic-media-segment'),
            ])
            auth = RadikoAuthenticationSource(transport, credential=Secret('SOURCE_FIXTURE_CREDENTIAL'))
            playlist = TimefreePlaylistSource(transport)
            work_root = root / '.staging' / 'capture-work'
            adapter = CaptureAdapter(store=store, managed_root=root, authenticator=auth,
                playlist_provider=playlist, media_fetcher=HlsMediaSource(transport, playlist, work_root=work_root),
                transcoder=SyntheticAudioTranscoder(60), preflight=lambda _row: None, clock=lambda: now)
            worker = TimefreeWorker(store, root, adapter, clock=lambda: now)
            self.assertEqual(worker.run_once(job), job)
            self.assertEqual(store.get(job)['state'], 'completed', store.get(job))
            self.assertEqual(len(transport.requests), 5)
            self.assertEqual(len(completed_assets(store, root, include_fixture=True)), 1)
            self.assertEqual(list(adapter.work_root.iterdir()), [])

    def test_playlist_rejects_invalid_station_without_request(self):
        transport = FakeHttpTransport([TIMEFREE])
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        with self.assertRaises(SourceFailure) as error:
            TimefreePlaylistSource(transport).resolve(SimpleNamespace(station='JOAK;bad', start_at=METADATA.start_at,
                end_at=METADATA.end_at), auth)
        self.assertEqual(error.exception.code, SourceCode.PLAYLIST_INVALID)
        self.assertEqual(transport.requests, [])

    def test_stream_xml_selection_requires_exact_timefree_and_areafree(self):
        body = (b'<urls><url areafree="0" timefree="0"><playlist_create_url>'
                b'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/live.m3u8</playlist_create_url></url>'
                b'<url areafree="1" timefree="1"><playlist_create_url>'
                b'https://tf-c-rpaa-radiko.smartstream.ne.jp/tf/tf.m3u8</playlist_create_url></url>'
                b'<url areafree="0" timefree="1"><playlist_create_url>'
                b'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/tf.m3u8</playlist_create_url>'
                b'</url></urls>')
        transport = FakeHttpTransport([HttpResponse(200, body=body)])
        result = TimefreePlaylistSource(transport).resolve(METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))
        self.assertTrue(result.url.startswith(
            'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/tf.m3u8?'))

    @staticmethod
    def stream_xml_candidates(*rows):
        parts = [b'<urls>']
        for areafree, timefree, url in rows:
            parts.append(f'<url areafree="{areafree}" timefree="{timefree}">'.encode())
            parts.append(b'<playlist_create_url>' + url.encode() + b'</playlist_create_url></url>')
        parts.append(b'</urls>')
        return b''.join(parts)

    def test_first_approved_candidate_wins_in_xml_order(self):
        safe = 'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/first.m3u8'
        unknown = 'https://unlisted.example.invalid/tf/other.m3u8'
        cases = (
            ([(0, 1, safe)], safe),
            ([(0, 1, safe), (0, 1, unknown)], safe),
            ([(0, 1, unknown), (0, 1, safe)], safe),
            ([(0, 1, safe), (0, 1, 'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/second.m3u8')], safe),
            ([(0, 1, safe), (0, 1, safe)], safe),
        )
        for rows, expected in cases:
            with self.subTest(rows=len(rows)):
                parser = TimefreePlaylistSource(FakeHttpTransport([
                    HttpResponse(200, body=self.stream_xml_candidates(*rows))]))
                result = parser.resolve(METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))
                self.assertEqual(urlsplit(result.url).hostname, urlsplit(expected).hostname)
                self.assertEqual(urlsplit(result.url).path, urlsplit(expected).path)
                self.assertEqual([row['index'] for row in parser.candidate_diagnostics],
                                 list(range(1, len(rows) + 1)))
                self.assertEqual([row['approved'] for row in parser.candidate_diagnostics],
                                 [urlsplit(url).hostname == 'tf-f-rpaa-radiko.smartstream.ne.jp'
                                  for _, _, url in rows])
                self.assertTrue(all('url' not in row for row in parser.candidate_diagnostics))

    def test_unapproved_matching_candidates_fail_closed(self):
        rows = (
            'http://tf-f-rpaa-radiko.smartstream.ne.jp/tf/http.m3u8',
            'https://127.0.0.1/tf/private.m3u8',
            'https://user:pass@tf-f-rpaa-radiko.smartstream.ne.jp/tf/userinfo.m3u8',
            'https://tf-f-rpaa-radiko.smartstream.ne.jp/other/path.m3u8',
            'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/%2e%2e/outside.m3u8',
            'not a valid url',
            'https://unlisted.example.invalid/tf/unknown.m3u8',
        )
        parser = TimefreePlaylistSource(FakeHttpTransport([HttpResponse(200, body=
            self.stream_xml_candidates(*[(0, 1, url) for url in rows]))]))
        with self.assertRaises(SourceFailure):
            parser.resolve(METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))
        self.assertEqual(len(parser.candidate_diagnostics), len(rows))
        self.assertFalse(any(row['approved'] for row in parser.candidate_diagnostics))

    def test_duplicate_approved_host_is_deterministic(self):
        first = 'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/one.m3u8'
        second = 'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/two.m3u8'
        parser = TimefreePlaylistSource(FakeHttpTransport([HttpResponse(200, body=
            self.stream_xml_candidates((0, 1, first), (0, 1, second)))]))
        result = parser.resolve(METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))
        self.assertEqual(urlsplit(result.url).path, '/tf/one.m3u8')
        self.assertEqual([row['hostname'] for row in parser.candidate_diagnostics],
                         ['tf-f-rpaa-radiko.smartstream.ne.jp'] * 2)

    def test_stream_xml_malformed_station_mismatch_no_timefree_or_areafree_mismatch(self):
        invalid_xml = (
            b'<urls>',
            b'<urls station_id="JOKE"><url areafree="0" timefree="1"><playlist_create_url>'
            b'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/a.m3u8</playlist_create_url></url></urls>',
            b'<urls><url areafree="0" timefree="0"><playlist_create_url>'
            b'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/a.m3u8</playlist_create_url></url></urls>',
            b'<urls><url areafree="1" timefree="1"><playlist_create_url>'
            b'https://tf-c-rpaa-radiko.smartstream.ne.jp/tf/a.m3u8</playlist_create_url></url></urls>',
        )
        for body in invalid_xml:
            with self.subTest(body=body[:24]), self.assertRaises(SourceFailure):
                TimefreePlaylistSource(FakeHttpTransport([HttpResponse(200, body=body)])).resolve(
                    METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))

    def test_stream_xml_missing_or_malformed_candidate_rejected(self):
        prefix = b'<urls><url areafree="0" timefree="1">'
        suffix = b'</url></urls>'
        bodies = (
            prefix + b'<other>none</other>' + suffix,
            prefix + b'<playlist_create_url>https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/a.m3u8'
            b'</playlist_create_url><playlist_create_url>https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/b.m3u8'
            b'</playlist_create_url>' + suffix,
        )
        for body in bodies:
            with self.subTest(body=body[:32]), self.assertRaises(SourceFailure):
                TimefreePlaylistSource(FakeHttpTransport([HttpResponse(200, body=body)])).resolve(
                    METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))

    def test_playlist_stream_xml_http_errors_timeout_and_get_only(self):
        for status in (403, 404):
            transport = FakeHttpTransport([HttpResponse(status)])
            with self.subTest(status=status), self.assertRaises(SourceFailure):
                TimefreePlaylistSource(transport).resolve(METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))
            self.assertEqual(transport.requests[0].method, 'GET')
        transport = FakeHttpTransport([TimeoutError()], policy=RetryPolicy(max_attempts=1))
        with self.assertRaises(SourceFailure) as error:
            TimefreePlaylistSource(transport).resolve(METADATA, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))
        self.assertEqual(error.exception.code, SourceCode.HTTP_TIMEOUT)
        self.assertEqual(transport.requests[0].method, 'GET')

    def test_areafree_premium_mode_is_not_accepted_by_normal_auth_source(self):
        metadata = SimpleNamespace(station='JOAK', start_at=METADATA.start_at,
                                   end_at=METADATA.end_at, areafree=1)
        transport = FakeHttpTransport([TIMEFREE])
        with self.assertRaises(SourceFailure):
            TimefreePlaylistSource(transport).resolve(metadata, AuthContext(Secret(DUMMY_TOKEN), 'JP13'))
        self.assertEqual(transport.requests, [])

    def test_empty_playlist_rejected(self):
        with self.assertRaises(SourceFailure):
            TimefreePlaylistSource(FakeHttpTransport([])).parse_hls(b'#EXTM3U\n#EXT-X-ENDLIST\n',
                'https://cdn.radiko.jp/fixture/index.m3u8')

    def test_malformed_playlist_rejected(self):
        parser = TimefreePlaylistSource(FakeHttpTransport([]))
        for value in (b'', b'not hls', b'\xff\xfe', b'#EXTM3U\nsegment.ts\n'):
            with self.subTest(value=value[:10]), self.assertRaises(SourceFailure):
                parser.parse_hls(value, 'https://cdn.radiko.jp/fixture/index.m3u8')

    def test_duplicate_segment_rejected(self):
        body = b'#EXTM3U\n#EXTINF:1,\nseg.ts\n#EXTINF:1,\nseg.ts\n'
        with self.assertRaises(SourceFailure):
            TimefreePlaylistSource(FakeHttpTransport([])).parse_hls(body, 'https://cdn.radiko.jp/fixture/i.m3u8')

    def test_oversized_playlist_rejected(self):
        with self.assertRaises(SourceFailure):
            TimefreePlaylistSource(FakeHttpTransport([])).parse_hls(b'#EXTM3U\n' + b'a' * 300000,
                'https://cdn.radiko.jp/fixture/i.m3u8')

    def test_playlist_url_from_stream_xml_is_validated(self):
        response = HttpResponse(200, body=(b'<urls><url areafree="0" timefree="1">'
            b'<playlist_create_url>https://attacker.invalid/tf/x.m3u8</playlist_create_url>'
            b'</url></urls>'))
        with self.assertRaises(SourceFailure):
            TimefreePlaylistSource(FakeHttpTransport([response])).resolve(
                METADATA, AuthContext(Secret(DUMMY_TOKEN), 'fixture-area'))

    def test_segment_url_from_playlist_is_validated(self):
        parser = TimefreePlaylistSource(FakeHttpTransport([]))
        body = b'#EXTM3U\n#EXTINF:1,\nhttps://evil.invalid/seg.ts\n'
        with self.assertRaises(SourceFailure):
            parser.parse_hls(body, 'https://cdn.radiko.jp/fixture/i.m3u8')

    def test_timeout_is_bounded_and_retryable(self):
        transport = FakeHttpTransport([TimeoutError(), AUTH], policy=RetryPolicy(max_attempts=2))
        self.assertEqual(self.auth_source(transport).authenticate(METADATA).area_id, 'fixture-area')
        self.assertEqual(len(transport.requests), 1)
        self.assertLessEqual(transport.requests[0].timeout.connect_seconds, 15)

    def test_retry_exhaustion_maps_timeout(self):
        transport = FakeHttpTransport([TimeoutError(), TimeoutError()], policy=RetryPolicy(max_attempts=2))
        with self.assertRaises(SourceFailure) as error:
            self.auth_source(transport).authenticate(METADATA)
        self.assertEqual(error.exception.code, SourceCode.HTTP_TIMEOUT)

    def test_server_error_retries_then_succeeds(self):
        transport = FakeHttpTransport([HttpResponse(503), AUTH], policy=RetryPolicy(max_attempts=2))
        self.assertEqual(self.auth_source(transport).authenticate(METADATA).area_id, 'fixture-area')

    def test_server_error_retry_limit(self):
        transport = FakeHttpTransport([HttpResponse(503), HttpResponse(503)], policy=RetryPolicy(max_attempts=2))
        with self.assertRaises(SourceFailure) as error:
            transport.request(HttpRequest('GET', 'https://api.radiko.jp/test'))
        self.assertEqual(error.exception.code, SourceCode.HTTP_REJECTED)

    def test_client_error_does_not_retry(self):
        transport = FakeHttpTransport([HttpResponse(403), AUTH])
        with self.assertRaises(SourceFailure):
            self.auth_source(transport).authenticate(METADATA)
        self.assertEqual(len(transport.requests), 1)

    def test_unexpected_transport_error_is_sanitized(self):
        transport = FakeHttpTransport([RuntimeError('secret-bearing detail')])
        with self.assertRaises(SourceFailure) as error:
            self.auth_source(transport).authenticate(METADATA)
        self.assertNotIn('secret-bearing', str(error.exception))

    def test_unsafe_urls_rejected(self):
        for url in ('http://radiko.jp/x', 'file:///etc/passwd', 'ftp://radiko.jp/x',
                    'https://localhost/x', 'https://127.0.0.1/x', 'https://10.1.2.3/x',
                    'https://attacker.invalid/x', 'https://user:pass@radiko.jp/x',
                    'https://radiko.jp/a/%2e%2e/secret', 'https://[::1]/x'):
            with self.subTest(url=url), self.assertRaises(SourceFailure):
                validate_url(url)

    def test_header_injection_rejected(self):
        transport = FakeHttpTransport([AUTH])
        with self.assertRaises(SourceFailure):
            transport.request(HttpRequest('GET', 'https://api.radiko.jp/x', headers={'X-Test': 'ok\r\nInjected: yes'}))
        self.assertEqual(transport.requests, [])

    def test_method_and_header_name_injection_rejected(self):
        transport = FakeHttpTransport([AUTH])
        for request in (HttpRequest('GET\r\nPOST', 'https://api.radiko.jp/x'),
                        HttpRequest('GET', 'https://api.radiko.jp/x', headers={'Bad Header': 'x'})):
            with self.subTest(request=request.method), self.assertRaises(SourceFailure):
                transport.request(request)

    def test_redirect_to_unauthorized_host_rejected(self):
        transport = FakeHttpTransport([HttpResponse(302, headers={'Location': 'https://attacker.invalid/x'})])
        with self.assertRaises(SourceFailure):
            transport.request(HttpRequest('GET', 'https://api.radiko.jp/x'))

    def test_redirect_to_allowed_host_is_not_followed(self):
        transport = FakeHttpTransport([HttpResponse(302, headers={'Location': 'https://radiko.jp/x'})])
        with self.assertRaises(SourceFailure):
            transport.request(HttpRequest('GET', 'https://api.radiko.jp/x'))
        self.assertEqual(len(transport.requests), 1)

    def test_oversized_response_rejected(self):
        transport = FakeHttpTransport([HttpResponse(200, body=b'x' * (2 * 1024 * 1024 + 1))])
        with self.assertRaises(SourceFailure):
            transport.request(HttpRequest('GET', 'https://api.radiko.jp/x'))

    def test_invalid_timeout_rejected(self):
        with self.assertRaises(ValueError):
            RequestTimeout(connect_seconds=0)

    def test_hls_output_path_confined_to_workspace(self):
        parser = TimefreePlaylistSource(FakeHttpTransport([]))
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            source = HlsMediaSource(FakeHttpTransport([]), parser, work_root=Path(root))
            with self.assertRaises(SourceFailure):
                source.download(PlaylistReference('https://cdn.radiko.jp/i.m3u8'),
                    AuthContext(Secret(DUMMY_TOKEN), 'fixture-area'), Path(other) / 'media-input.ts')

    def test_hls_output_traversal_and_collision_rejected(self):
        parser = TimefreePlaylistSource(FakeHttpTransport([]))
        with tempfile.TemporaryDirectory() as root:
            source = HlsMediaSource(FakeHttpTransport([]), parser, work_root=Path(root))
            auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
            with self.assertRaises(SourceFailure):
                source.download(PlaylistReference('https://cdn.radiko.jp/i.m3u8'), auth,
                                Path(root) / '..' / 'media-input.ts')
            dest = Path(root) / 'media-input.ts'
            dest.write_bytes(b'keep')
            with self.assertRaises(SourceFailure):
                source.download(PlaylistReference('https://cdn.radiko.jp/i.m3u8'), auth, dest)
            self.assertEqual(dest.read_bytes(), b'keep')

    def test_media_overall_timeout_expires_before_next_request(self):
        transport = FakeHttpTransport([MASTER_RESPONSE, MEDIA_RESPONSE, SEGMENT])
        parser = TimefreePlaylistSource(transport)
        with tempfile.TemporaryDirectory() as root:
            source = HlsMediaSource(transport, parser, work_root=Path(root))
            auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
            with patch('radioflix.timefree.capture.source.media.time.monotonic', side_effect=[0.0, 2.0]):
                with self.assertRaises(SourceFailure) as error:
                    source.download(PlaylistReference('https://cdn.radiko.jp/fixture/index.m3u8'), auth,
                                   Path(root) / 'media-input.ts', timeout_seconds=1)
            self.assertEqual(error.exception.code, SourceCode.HTTP_TIMEOUT)
            self.assertEqual(transport.requests, [])

    def test_incomplete_hls_media_playlist_rejected(self):
        responses = [HttpResponse(200, body=b'#EXTM3U\n#EXTINF:1,fixture\nseg.ts\n')]
        transport = FakeHttpTransport(responses)
        parser = TimefreePlaylistSource(transport)
        with tempfile.TemporaryDirectory() as root:
            source = HlsMediaSource(transport, parser, work_root=Path(root))
            auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
            with self.assertRaises(SourceFailure) as error:
                source.download(PlaylistReference('https://cdn.radiko.jp/fixture/index.m3u8'), auth,
                                Path(root) / 'media-input.ts')
            self.assertEqual(error.exception.code, SourceCode.MEDIA_FETCH_FAILED)
            self.assertFalse((Path(root) / 'media-input.ts').exists())

    def test_production_transport_and_adapter_are_not_ready_and_never_open_network(self):
        transport = ProductionHttpTransport()
        with patch('socket.socket', side_effect=AssertionError('socket must not be opened')):
            with self.assertRaises(SourceNotReady):
                transport.request(HttpRequest('GET', 'https://api.radiko.jp/x'))
        self.assertFalse(transport.ready)
        self.assertFalse(ProductionCaptureAdapter.ready)
        self.assertFalse(ProductionCaptureAdapter.bridge_approved)

    def test_secret_and_http_objects_redact_repr(self):
        secret = Secret(DUMMY_TOKEN)
        request = HttpRequest('GET', 'https://api.radiko.jp/x', headers={'X-Auth': secret})
        response = HttpResponse(200, headers={'Set-Cookie': DUMMY_TOKEN}, body=DUMMY_TOKEN.encode())
        for value in (secret, request, response):
            self.assertNotIn(DUMMY_TOKEN, repr(value))

    def test_observation_transport_is_off_by_default(self):
        transport = ProductionHttpTransport()
        with patch('socket.socket', side_effect=AssertionError('socket must not be opened')):
            with self.assertRaises(SourceNotReady):
                transport.request(HttpRequest('GET', 'https://radiko.jp/x'))
        self.assertFalse(transport.ready)

    def test_observation_transport_rejects_dns_failure_before_connect(self):
        transport = ProductionHttpTransport(observation_mode=True, max_wire_requests=1)
        with patch.object(transport, '_public_addresses', side_effect=SourceFailure(SourceCode.HTTP_REJECTED)):
            with patch.object(transport, '_open_once', side_effect=AssertionError('must not connect')):
                with self.assertRaises(SourceFailure):
                    transport.request(HttpRequest('GET', 'https://radiko.jp/x'))
        self.assertEqual(transport.wire_requests, 0)

    def test_observation_transport_rejects_private_dns_addresses(self):
        answer = [(2, 1, 6, '', ('127.0.0.1', 443))]
        with patch('socket.getaddrinfo', return_value=answer):
            with self.assertRaises(SourceFailure) as error:
                ProductionHttpTransport._public_addresses('radiko.jp')
        self.assertEqual(error.exception.code, SourceCode.HTTP_REJECTED)

    def test_observation_transport_manual_redirect_revalidates_same_host(self):
        transport = ProductionHttpTransport(observation_mode=True, max_wire_requests=2,
                                             policy=RetryPolicy(max_attempts=1))
        first = HttpResponse(302, headers={'Location': 'https://radiko.jp/safe/next'})
        second = HttpResponse(200, headers={'Content-Type': 'text/plain'}, body=b'ok')
        with patch.object(transport, '_public_addresses', return_value=('8.8.8.8',)):
            with patch.object(transport, '_open_once', side_effect=[first, second]) as opened:
                response = transport.request(HttpRequest('GET', 'https://radiko.jp/start'))
        self.assertEqual(response.body, b'ok')
        self.assertEqual(response.redirect_count, 1)
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(transport.wire_requests, 2)

    def test_observation_transport_rejects_cross_host_redirect(self):
        transport = ProductionHttpTransport(observation_mode=True, max_wire_requests=2, policy=RetryPolicy(max_attempts=1))
        with patch.object(transport, '_public_addresses', return_value=('8.8.8.8',)):
            with patch.object(transport, '_open_once', return_value=HttpResponse(
                    302, headers={'Location': 'https://api.radiko.jp/next'})):
                with self.assertRaises(SourceFailure):
                    transport.request(HttpRequest('GET', 'https://radiko.jp/start'))

    def test_observation_transport_retries_server_error_bounded(self):
        transport = ProductionHttpTransport(observation_mode=True, max_wire_requests=2, policy=RetryPolicy(max_attempts=2))
        with patch.object(transport, '_public_addresses', return_value=('8.8.8.8',)):
            with patch.object(transport, '_open_once', side_effect=[HttpResponse(503), HttpResponse(200, body=b'ok')]):
                self.assertEqual(transport.request(HttpRequest('GET', 'https://radiko.jp/x')).body, b'ok')
        self.assertEqual(transport.wire_requests, 2)

    def test_observation_transport_has_hard_wire_request_budget(self):
        transport = ProductionHttpTransport(observation_mode=True, max_wire_requests=1, policy=RetryPolicy(max_attempts=1))
        with patch.object(transport, '_public_addresses', return_value=('8.8.8.8',)):
            with patch.object(transport, '_open_once', return_value=HttpResponse(200, body=b'ok')):
                transport.request(HttpRequest('GET', 'https://radiko.jp/x'))
                with self.assertRaises(SourceNotReady):
                    transport.request(HttpRequest('GET', 'https://radiko.jp/x'))

    @staticmethod
    def _media_fixture(segment_count=3):
        lines = ['#EXTM3U', '#EXT-X-TARGETDURATION:10', '#EXT-X-MEDIA-SEQUENCE:1']
        for index in range(segment_count):
            lines.extend(['#EXTINF:10,', f'segment-{index + 1}.ts'])
        lines.append('#EXT-X-ENDLIST')
        return ('\n'.join(lines) + '\n').encode()

    @staticmethod
    def _ts_fixture(size=376):
        data = bytearray(b'\x00' * size)
        for offset in range(0, size, 188):
            data[offset] = 0x47
        return bytes(data)

    def _production_media(self, transport, root):
        return ProductionMediaFetcher(transport, TimefreePlaylistSource(transport), work_root=Path(root))

    def test_production_media_fetcher_downloads_only_requested_first_segment(self):
        transport = FakeHttpTransport([
            HttpResponse(200, headers={'Content-Type': 'application/x-mpegURL'},
                        body=self._media_fixture(5).replace(b'#EXT-X-ENDLIST\n', b'')),
            HttpResponse(200, headers={'Content-Type': 'video/mp2t'}, body=self._ts_fixture()),
        ])
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / 'job'; workspace.mkdir()
            files = self._production_media(transport, root).fetch_segments(
                'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/test/media.m3u8', auth, workspace, max_segments=1)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].path.read_bytes(), self._ts_fixture())
            self.assertEqual(files[0].path.name, 'segment-001.bin')
            self.assertEqual(files[0].status, 200)
            self.assertEqual(files[0].content_type, 'video/mp2t')
            self.assertEqual(files[0].media_format, 'mpeg-ts')
            self.assertEqual(len(transport.requests), 2)
            self.assertEqual(transport.requests[1].headers['X-Radiko-AreaId'], 'fixture-area')
            self.assertFalse(ProductionMediaFetcher.ready)

    def test_production_media_fetcher_caps_at_three_and_rejects_four(self):
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        url = 'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/test/media.m3u8'
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / 'job'; workspace.mkdir()
            transport = FakeHttpTransport([])
            fetcher = self._production_media(transport, root)
            for invalid in (0, 4, True):
                with self.assertRaises(SourceFailure):
                    fetcher.fetch_segments(url, auth, workspace, max_segments=invalid)
            self.assertEqual(transport.requests, [])
            transport = FakeHttpTransport([HttpResponse(200,
                headers={'Content-Type': 'application/vnd.apple.mpegurl'}, body=self._media_fixture(5)),
                *[HttpResponse(200, headers={'Content-Type': 'video/mp2t'}, body=self._ts_fixture())
                  for _ in range(MAX_PRODUCTION_SEGMENTS)]])
            files = self._production_media(transport, root).fetch_segments(
                url, auth, workspace, max_segments=MAX_PRODUCTION_SEGMENTS)
            self.assertEqual(len(files), MAX_PRODUCTION_SEGMENTS)
            self.assertEqual(len(transport.requests), MAX_PRODUCTION_SEGMENTS + 1)

    def test_production_media_fetcher_rejects_unsafe_manifest_paths(self):
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / 'job'; workspace.mkdir()
            fetcher = self._production_media(FakeHttpTransport([]), root)
            urls = (
                'https://attacker.invalid/tf/media.m3u8',
                'https://tf-f-rpaa-radiko.smartstream.ne.jp/other/media.m3u8',
                'https://user@tf-f-rpaa-radiko.smartstream.ne.jp/tf/media.m3u8',
                'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/%2e%2e/media.m3u8',
            )
            for url in urls:
                with self.subTest(url=url), self.assertRaises(SourceFailure):
                    fetcher.fetch_segments(url, auth, workspace)

    def test_production_media_fetcher_rejects_segment_outside_manifest_path(self):
        body = b'#EXTM3U\n#EXTINF:10,\nhttps://tf-f-rpaa-radiko.smartstream.ne.jp/elsewhere/x.ts\n#EXT-X-ENDLIST\n'
        transport = FakeHttpTransport([HttpResponse(200, headers={'Content-Type': 'application/x-mpegURL'}, body=body)])
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / 'job'; workspace.mkdir()
            with self.assertRaises(SourceFailure):
                self._production_media(transport, root).fetch_segments(
                    'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/test/media.m3u8', auth, workspace)
            self.assertEqual(len(transport.requests), 1)

    def test_production_media_fetcher_rejects_http_errors_timeout_and_redirect(self):
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        manifest_url = 'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/test/media.m3u8'
        cases = (
            (404, [HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)), HttpResponse(404)]),
            (403, [HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)), HttpResponse(403)]),
            (429, [HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)), HttpResponse(429)]),
            (206, [HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)), HttpResponse(206, headers={'Content-Type':'video/mp2t'}, body=self._ts_fixture())]),
            (503, [HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)), HttpResponse(503), HttpResponse(503), HttpResponse(503)]),
            ('timeout', [HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)), TimeoutError(), TimeoutError(), TimeoutError()]),
            ('redirect', [HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)), HttpResponse(302, headers={'Location':'https://attacker.invalid/steal'})]),
        )
        for label, responses in cases:
            with self.subTest(status=label), tempfile.TemporaryDirectory() as root:
                workspace = Path(root) / 'job'; workspace.mkdir()
                transport = FakeHttpTransport(responses)
                with self.assertRaises(SourceFailure):
                    self._production_media(transport, root).fetch_segments(manifest_url, auth, workspace)
                self.assertEqual(list(workspace.iterdir()), [])

    def test_production_media_fetcher_rejects_empty_wrong_type_and_truncated(self):
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        manifest_url = 'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/test/media.m3u8'
        segments = (
            HttpResponse(200, headers={'Content-Type':'video/mp2t'}, body=b''),
            HttpResponse(200, headers={'Content-Type':'text/html'}, body=b'<html>error</html>'),
            HttpResponse(200, headers={'Content-Type':'video/mp2t'}, body=self._ts_fixture(187)),
            HttpResponse(200, headers={'Content-Type':'audio/aac'}, body=b'\xff\xf1\x50\x80\xff\xff\xfc'),
        )
        for segment in segments:
            with self.subTest(size=len(segment.body), content_type=segment.headers.get('Content-Type')):
                with tempfile.TemporaryDirectory() as root:
                    workspace = Path(root) / 'job'; workspace.mkdir()
                    transport = FakeHttpTransport([
                        HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)),
                        segment,
                    ])
                    with self.assertRaises(SourceFailure):
                        self._production_media(transport, root).fetch_segments(manifest_url, auth, workspace)
                    self.assertEqual(list(workspace.iterdir()), [])

    def test_production_media_fetcher_rejects_oversized_segment(self):
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        oversized = self._ts_fixture() + b'\x00' * (16 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / 'job'; workspace.mkdir()
            transport = FakeHttpTransport([
                HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)),
                HttpResponse(200, headers={'Content-Type':'video/mp2t'}, body=oversized),
            ])
            with self.assertRaises(SourceFailure):
                self._production_media(transport, root).fetch_segments(
                    'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/test/media.m3u8', auth, workspace)
            self.assertEqual(list(workspace.iterdir()), [])

    def test_production_media_fetcher_does_not_overwrite_existing_segment(self):
        auth = AuthContext(Secret(DUMMY_TOKEN), 'fixture-area')
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / 'job'; workspace.mkdir()
            existing = workspace / 'segment-001.bin'; existing.write_bytes(b'preserve')
            transport = FakeHttpTransport([
                HttpResponse(200, headers={'Content-Type':'application/x-mpegURL'}, body=self._media_fixture(1)),
                HttpResponse(200, headers={'Content-Type':'video/mp2t'}, body=self._ts_fixture()),
            ])
            with self.assertRaises(SourceFailure):
                self._production_media(transport, root).fetch_segments(
                    'https://tf-f-rpaa-radiko.smartstream.ne.jp/tf/test/media.m3u8', auth, workspace)
            self.assertEqual(existing.read_bytes(), b'preserve')
            self.assertEqual(list(workspace.iterdir()), [existing])


if __name__ == '__main__':
    unittest.main()
