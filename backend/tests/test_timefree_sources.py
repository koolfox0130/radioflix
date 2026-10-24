"""Safe Source API tests. All HTTP responses are synthetic and socket-free."""

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import patch

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
from radioflix.timefree.capture.source.transport import FakeHttpTransport, ProductionHttpTransport, validate_url
from radioflix.timefree.service import deadline
from radioflix.timefree.store import TimefreeStore
from radioflix.timefree.worker import TimefreeWorker, completed_assets


DUMMY_TOKEN = 'TEST_ONLY_NOT_A_CREDENTIAL'
MASTER = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nmedia/index.m3u8\n'
MEDIA = b'#EXTM3U\n#EXTINF:1.0,fixture\nsegment-1.ts\n#EXT-X-ENDLIST\n'
AUTH = HttpResponse(200, body=json.dumps({'auth_token': DUMMY_TOKEN, 'area_id': 'fixture-area'}).encode())
TIMEFREE = HttpResponse(200, body=b'{"playlist_url":"https://cdn.radiko.jp/fixture/index.m3u8"}')
MASTER_RESPONSE = HttpResponse(200, body=MASTER)
MEDIA_RESPONSE = HttpResponse(200, body=MEDIA)
SEGMENT = HttpResponse(200, body=b'synthetic-segment-bytes')
METADATA = SimpleNamespace(
    station='JOAK',
    start_at=datetime(2025, 1, 1, 12, 0, tzinfo=JST),
    end_at=datetime(2025, 1, 1, 13, 0, tzinfo=JST),
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
        self.assertEqual(playlist.url, 'https://cdn.radiko.jp/fixture/index.m3u8')
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / 'media-input.ts'
            source = HlsMediaSource(transport, playlist_source, work_root=Path(root))
            self.assertEqual(source.download(playlist, auth, dest), dest)
            self.assertEqual(dest.read_bytes(), b'synthetic-segment-bytes')
            self.assertEqual(len(transport.requests), 5)
            self.assertIn('station_id=JOAK', transport.requests[1].url)
            self.assertIn('20250101120000', transport.requests[1].url)

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
                HttpResponse(200, body=b'{"playlist_url":"https://cdn.radiko.jp/fixture/index.m3u8"}'),
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

    def test_playlist_url_from_response_is_validated(self):
        response = HttpResponse(200, body=b'{"playlist_url":"https://attacker.invalid/x.m3u8"}')
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


if __name__ == '__main__':
    unittest.main()
