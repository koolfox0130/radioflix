# Phase 4 タイムフリー隔離検証

## 今回の対象

Phase 1〜3 は正式リリース済み。Phase 4 の本変更は、一時DB・mock API・合成WAVとネットワークなしPHPコンテナで検証する範囲である。本番反映・実radiko認証・HLS取得・実録音は実施しない。

- `backend/radioflix/timefree/store.py`: 永続ジョブ、同一放送回の一意制約、状態遷移イベント。GETではDBを作成しない。
- `service.py` / `api/timefree.py`: 番組表の再取得・revision確認、期限・配信制限・native予約照合、認証付き受付、状態照会、待機中の取消。
- `worker.py`: 単一workerロック、fixture/liveの分離、開始直前の期限確認、WAV実データ長・番組時間・出力パス・ハッシュ検証、上書き拒否。中断・timeout・保存後のDB失敗はunknownとし、自動再録音しない。
- `worker.php` / `fixture-bindings.php`: ハッシュ固定したrfriends関数だけを取り込み、認証・HLS・外部コマンド・出力転送等をfixtureへ置換。共有initializer・本番CLIは呼ばない。
- 番組表: 録音待ち・録音中・完了・失敗・期限切れ・unknownの表示、連打防止、オフライン受付拒否、待機/実行中の5秒更新。
- `completed_assets()` は読取専用の将来統合境界。fixture成果物は既定で除外する。

## 中断復旧

2026-10-11 の再開時、WAV実データ検証・作業領域作成失敗対策・追加5テストは保存済みだった。途中で切れた編集はなし。`latest.md` のbuild実行中・依存取得中という記録は実態より古かった。Git/実ファイルを優先し補正した。開始HEADは `d46babe85db84b4ee08ff1ccf3d14fe97ed4fa0f`、branchはmain。既存差分を取り消していない。

## 隔離条件

PHP試験は `rfriends3-rfriends3:latest` の専用一時コンテナを使用する。

- `--network none --read-only --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges`
- 本番volume・Docker socket・秘密設定をマウントしない。
- 書込bindは `/tmp/radioflix-driver-tests` と `/tmp/radioflix-timefree-tests` だけ。
- workerソースと `/tmp/radioflix-phase4-source` はread-only。
- 両録音gateは0。テストのゲート分岐は関数mockで確認する。
- `source-manifest.json` のSHA-256と抽出した `rf_downloader.php` / `rf_timefree.php` の一致を実行前に確認する。不一致時はmanifestを自動更新しない。
- 合成音声生成のみ。実ffmpeg・実radiko認証・実HLSの互換性を保証するテストではない。

`docker-compose.timefree-test.yml` は独立したfixture用設定。本番Composeに重ねない。既存imageを使うためbuild対象はない。

## 再実行手順

一時依存は製品のpackage.json/lockfileを変更せず `/tmp` に準備した。`/tmp` は消えるため、存在を確認してから利用する。

Pythonの依存は `backend/requirements-test.txt` に従う。今回の環境ではvenvのensurepipがなく、次で導入した。

```sh
python3 -m pip install --target /tmp/radioflix-test-deps -r backend/requirements-test.txt
```

PHP試験コンテナを上記隔離条件で作成後、次で全backend試験を実行する。コマンド中のコンテナ名は専用fixtureコンテナのみを指す。

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/radioflix-test-deps:backend \
RFRIENDS_ENABLE_WRITES=0 RADIOFLIX_TIMEFREE_ENABLE_WRITES=0 \
RADIOFLIX_TEST_PHP_COMMAND='["docker","exec","-i","radioflix-phase4-offline-test","php"]' \
RADIOFLIX_TIMEFREE_TEST_PHP='["docker","exec","-i","radioflix-phase4-offline-test","php"]' \
RADIOFLIX_TIMEFREE_TEST_SOURCE=/tmp/radioflix-phase4-source \
python3 -m unittest discover -s backend/tests -q
```

UIは `/tmp/radioflix-ui-tools` にPlaywright、`/tmp/radioflix-browsers` にChromiumを取得し、frontendから次の3ファイルを実行する。各テストは隔離Nextアプリを作成し、API/音声をmockする。

```sh
NODE_PATH=/tmp/radioflix-ui-tools/node_modules \
PLAYWRIGHT_BROWSERS_PATH=/tmp/radioflix-browsers \
node tests/schedule-ui.mjs
# 同じ環境変数で tests/reservations-ui.mjs と tests/playback-navigation-ui.mjs
npm run build
npx tsc --noEmit
npm run lint
```

番組表は360/390/412/1280px、予約は360/1280px、再生遷移は360px。Android実機試験ではない。

## 2026-10-12 の追加実装

起動制御transport・開始/公開直前のnative/録音再照合・NAS原子的公開・再起動復旧を実装した。詳細と制約は `docs/radioflix-timefree-runtime.md` を参照。

- 専用Unix socket serviceを追加。backend/gatewayにDocker権限を追加せず、job_idだけを永続通知する。
- 正式snapshot、局一覧、native予約、既存音声、他jobを読み取り再照合する。
- 公開intent・manifest・実音声を一致検証し、RENAME_NOREPLACEとfsyncで公開する。
- worker/service再起動時にreconcileし、backend再起動後は通知を再開、読み取り時もcompletedを検証する。

本番向けComposeは**両gate OFFの反映試験候補**として作成済みだが、未deploy。本番パスの作成/permission確認とfilesystem受入は実施していない。

実radiko音声取得bootstrapは引き続き未接続で `capture_ready=false`。実タイムフリー1本試験へは進めない。実形式検証、radiko認証/HLSの隔離互換性確認、本番反映受入と個別承認が必要。一覧/再生APIへのasset統合はPhase 5の対象。

## 検証結果

最終結果・既知の未確認項目・安全状態は `docs/dev-log/latest.md` と対応するhistory snapshotに記録する。過去の成功を今回の結果として扱わない。

## 2026-10-24 bounded segment observation and offline regression

通常pc_html5認証で取得したareafree=0の5分番組について、HTTP/manifest観測の後に先頭segmentを1個だけ取得した。media manifestは3 entry、`ENDLIST`なし、key/mapなし。segmentはHTTP 200、`application/octet-stream`、31,707 bytes、約0.09秒でAAC ADTS framingを確認した。test workspace内のファイルは検証後に削除し、segmentの追加取得、ffmpeg、結合、publisher、本番録音は行っていない。

コードの隔離回帰では `ProductionHttpTransport` の通常構築はNotReadyのまま、`ProductionMediaFetcher` は最大3 segment（既定1）に制限される。FakeHttpTransportによるSource API 52 tests PASS。backend全体278 tests PASS / 0 skipped（network none、read-only root、non-root、cap-drop ALL、no-new-privileges、専用test volume）。PHP syntax 5 files PASS、Python compileall PASS。UI schedule 148 checks、reservation 24 scenarios、playback/navigation 21 checks PASS。`npx tsc --noEmit` PASS、lint error 0 / existing warnings 5、build PASS、`git diff --check` PASS。実行時の詳細と最終安全snapshotはdev-logを参照。

## 2026-10-16 bootstrap調査と隔離回帰

今回の作業開始時HEADはPhase 4 checkpoint `2ad058817b520e85f8f830ac160bf617afbf9f69`。稼働中rfriends3から `rf_timefree.php` / `rf_downloader.php` と直接依存候補4ファイルを読み取り専用で取得した。6 source hashesは `bootstrap-source-manifest.json` に記録し、fixture 2 sourceを含むfingerprint検証はPASS。

source reviewで `timefree_kwrec_ex()` のqueue削除/再書込/`exit`、`rfriends_downloader()` のshell文字列ffmpeg、通常録音rootへの出力、retry/transfer hooksを確認した。安全なlibrary API・source全体の副作用契約が確定していないため、実capture bridgeと本番用Composeは未完成。`ProductionBootstrap` はready false固定で、両gate OFFではPHPを起動せずfailする。実radiko認証・HTTP/HLS・ffmpegは一切実行しない。

検証実績:

- backend/PHP/worker: 194 tests PASS（Phase 1〜3回帰含む）。network none、container rootfs read-only、UID 1000、cap-drop ALL、両gate 0、専用`/tmp` test volumeのみwrite。初回の隔離環境はtest volume owner/tmp exec設定不足で失敗したため、隔離条件を直して全件再実行した。
- bootstrap unit: 6 tests PASS（allowlist fingerprint、missing/hash mismatch、manifest path traversal、symlink、gate OFF拒否）。
- PHP `-l`: RadioFlix worker/fixtureとmanifest対象6 source PASS。
- Python compile: bootstrap/test module PASS。
- UI: schedule 148 checks、reservation 24 scenarios、playback/navigation 21 checks PASS。全API/音声はmock。
- `npx tsc --noEmit` PASS。`npm run lint` error 0、warning 5（既存）。`npm run build` PASS。sandboxではTurbopack subprocessのport bind制限で失敗したため、許可付き再実行を行った。
- bootstrap source manifest: 稼働中rfriends3から得た6 fingerprintと一致。git diff/secret scanの最終結果はlatestへ記録する。

実録音・認証・radiko network: 0。production service deployなし。ComposeはPHP/source/secret/egressを備えないため、隔離worker反映試験・実タイムフリー1本試験へ進めない。

## 2026-10-19 Safe Capture Adapter fixture

`backend/radioflix/timefree/capture/` にjob_idから音声成果物までの共通orchestrator、typed stage contract、fixture ports、shell-free ffmpeg argv helper、production NotReady adapterを追加した。`worker.py` はcapture context結果を既存publisherへ渡し、jobから導出したworkspace内だけを受け入れる。production adapterはworkerへ未接続で、`ready=false` / `bridge_approved=false` を維持する。

capture専用テストは31件PASS。正常worker→publisher、invalid job/path/shell payload、metadata/expiry/duplicate/native unknown、fake auth/playlist/media failure、timeout、ffmpeg argv allowlist、truncated/zero-byte/wrong-format、collision、cleanup、interruption後のreconcile、gate OFF、production NotReadyを含む。実Subprocessは呼ばず、ffmpeg argvテストは `subprocess.run` mockでlist・`shell=False`・固定optionを確認する。失敗初回はtest dummy executableを`/tmp`上で実行可能と判定できなかったもので、`/tmp`をnoexecにした隔離条件に対応して専用test volume上のdummyに移し、31件を最終再実行してPASSした。

安全条件はnetwork none、read-only root、UID1000、cap-drop ALL、no-new-privileges、`/tmp` tmpfs noexec/nosuid、backend/deps read-only、空の専用test volumeだけwrite。native予約/dat/sh/at、通常録音root、Docker socketはいずれもmountしていない。fixtureではsocket/HTTPを開かず合成audioのみを生成する。host Python 3.11での初回起動はPython 3.12用pydantic_coreの不一致でimport前に停止したため、該当テスト結果には含めずPython 3.12隔離containerで実行した。

runtime docにrfriends3 sourceからの仕様抽出、各stage contract、将来productionに必要なauth/HTTP/HLS/ffmpeg/secret/egress/timeout/retry/error mappingを追記した。これらはinterface/design記録で、実radiko通信機能の実装ではない。完全な回帰結果はlatestに記録する。

## 2026-10-20 Safe Source API fixture

稼働中rfriends3から対象PHP source 9件をread-only取得し、container内SHA-256を照合した。すべて保存済み監査fingerprintと一致。2026-10-21はactive configの`radiko_auth_mode=0`だけを値出力し、source-defined auth1/auth2とplaylist endpoint、mode別処理を追加確認した。token/cookie/password等は読まず、HTTP requestも行っていない。station・開始終了時刻の`YmdHis` rectime、timefree margin、tf30 300秒区間、`wget -i`でのm3u8取得、`#EXT-X-ENDLIST` / `#EXT-X-PROGRAM-DATE-TIME`処理も確認した。effective `hls_type`/premium branch、全status/retry/redirect/timeoutの実効値は未確定。詳細は[`radioflix-timefree-source-api.md`](radioflix-timefree-source-api.md)。

`capture/source/`にtyped HTTP request/response/timeout/retry、socketを使わない`FakeHttpTransport`、常時NotReadyの`ProductionHttpTransport`、authentication/playlist/HLS media sourceとHLS parserを実装。fixtureはsynthetic token/audio bytesとメモリ内responseのみ。URL exact-host/scheme/userinfo/IP/path policy、header injection、redirect拒否、response上限、retry/error mapping、secret repr redaction、workspace-only no-overwrite file creationをtestで確認する。production endpoint/wire contractは未実装。

今回のテスト結果・安全状態は`docs/dev-log/latest.md`を参照。稼働rfriends3、native予約/dat/sh/at、通常録音rootは変更していない。production HTTPはNotReady、ready/bridge false、両gate OFF、実radiko通信0、実録音0を維持する。

## 2026-10-16 capture境界 read-only audit

現行rfriends3 sourceの関数単位依存を追跡し、dependency graphとA/B/C分類を `docs/radioflix-timefree-runtime.md` に追記した。`timefree_kwrec_ex()` はqueue file変更・process終了を含み、`rfriends_downloader()` は認証/HLSのshell string経路、ffmpeg shell string、通常録音rootへのmoveと通常後処理を束ねる。現行auth/HLS下位helperも `rf_wget()` → `external_program()` → `system()` に接続しており、RadioFlix専用pathとargvだけに閉じた取得境界は存在しないと判断した。

従ってproduction bridgeは実装せず、`ProductionBootstrap.ready=false` / `bridge_approved=false` を維持する。candidate source manifestはfingerprint allowlistであり、実行承認ではない。production用capture Composeも未完成のままで、今回起動・deployしていない。隔離fixtureはこれまでどおりfake auth/HLS/downloaderと合成音声のみであり、実radiko経路の互換性は主張しない。

本判断は実コードのread-only確認に基づく。rfriends3・native rsv/dat/sh/at・通常録音領域への変更はなく、秘密値も読み取っていない。実radiko認証・HTTP/HLS・録音は0。今回の最終再検証結果は `docs/dev-log/latest.md` に記録する。
## 2026-10-23 production wire read-only audit

Current source selectors establish radiko_auth_mode=0 and hls_type=0; the normal auth path and standard playlist request contract are now documented. The standard playlist command carries --post-data=flash=1 (POST), while the timefree-specific downloader branch hardcodes the tf30 300-second GET path; it does not select that path using the generic premium-age predicate. The effective auth mode remains unresolved because rf_premium_mode()/product status selects normal vs premium auth. Auth wget option names/numeric bounds were extracted without exposing proxy/config values; the direct tf30/PHP HLS calls do not use those bounds, and redirects have no host revalidation. Legacy auth disables TLS verification, and neither wget nor PHP stream-wrapper redirect behavior provides the required host revalidation. Thus BLOCK 3 was not started and ProductionHttpTransport stays NotReady. No helper execution or network request occurred. See radioflix-timefree-source-api.md.

A redacted option-only scan confirmed auth1/auth2 retry and timeout flags but showed they do not bound the direct playlist/tf30 or PHP stream-wrapper calls. Static source confirms timefree path hardcodes tf30=1. Numeric premium.ini selectors were read without any credential values; actual product status and auth mode were not executed. These facts refine, but do not remove, the production transport blocker.

## 2026-10-24 observation-only network phase

This phase used live DNS/TLS plus a bounded authentication observation: one playerCommon.js GET, two auth1 GETs, and one auth2 GET. The second auth1 call supplied transient values to the auth2 probe; its response metrics were not emitted. DNS/TLS passed for `radiko.jp` and the two source-defined tf30 playlist hosts. `playerCommon.js` GET and mode-0 auth1/auth2 were observed; auth1 returned 200, auth2 returned 401. The probe did not follow redirects, retry automatically, request playlist/HLS manifests, or request any audio segment. No audio file, ffmpeg process, publisher, deploy, gate change, or native write occurred. Header names and response metadata were recorded; all credential-bearing header values and response bodies were suppressed. The failed auth2 exchange blocks further HTTP observation and Production HTTP implementation pending safe resolution.

## 2026-10-24 production ffmpeg attempt

Offline real-ffmpeg fixture suite passed 8 tests (1/2/3 synthetic ADTS inputs, WAV properties/duration, invalid inputs, bounds, timeout/failure, collision, cleanup). Capture + ffmpeg regression passed 40 tests; full backend discovery passed 286 / 0 skipped. Frontend: schedule 148, reservation 24, playback/navigation 21 PASS; typecheck/build PASS; lint 0 errors / 5 existing warnings. The authorized live test then fetched no more than three segments from the known areafree=0 CRK item. Normal authentication succeeded and ffmpeg returned exit code 0, but internal WAV validation failed with `ffmpeg_output_invalid`. The exact output properties were not emitted before the test workspace was removed. No retry occurred; this is a stop condition, not a successful transcoder verification. Gates stayed OFF, no publisher/deploy/native mutation occurred. See latest dev-log.

## 2026-10-25 offline ffmpeg output diagnosis

No Radiko DNS, auth, HTTP/HLS, or segment request was made. The prior WAV artifact had already been deleted, so the reported live `ffmpeg_output_invalid` could not be attributed. The old validator's generic code covered filesystem/type/size failures, WAV parser failures, PCM format/sample-rate/channel/frame checks; only duration mismatch had a separate code. The WAV parser was instrumented with internal reason codes and replaced at this boundary with bounded RIFF chunk parsing that validates actual data bytes and block alignment while allowing metadata/unknown chunks. External error mapping remains unchanged. A bounded `ffprobe` diagnostic uses argv with `shell=False` and is test-only.

Isolated network-none tests: 13 PASS. Local ffmpeg generated AAC-LC mono/stereo fixtures at 44.1/48 kHz, 1/2/3 inputs, ID3-prefixed input, and WAV metadata/unknown chunks; ffprobe agreed with the synthetic WAV's container/codec/rate/channel properties. Truncated, zero-payload and invalid-alignment WAVs were rejected. Existing synthetic transcoding remained successful. None of these fixtures reproduced the live rejection, so A/B/C/D remain unresolved and no speculative argv/concat/duration change was made. Per the explicit stop condition, the remaining full regression suite and any live retest were not run.

## 2026-10-25 single live diagnostic attempt

Before the attempt, the synthetic ffmpeg suite passed 13 tests. Backend gate values were `RFRIENDS_ENABLE_WRITES=0` and Timefree gate unset/OFF. Reservations, weekly subscriptions, and recording jobs were all cancelled; no timefree job table existed. Production readiness/bridge flags remained false. Native `.dat`/`.sh` count and aggregate fingerprint were 14 / `cfe9050b9378fcea475a2386cc773aa4945859a4a9e5c67549ac7d2567e70f34`; `atq` count/hash were 6 / `cc05b8bea4729b20fde6950381900fbd9331a98e641b91fd68a5cff6bbc28e11` before and after. The four RadioFlix/rfriends3 containers remained Up.

The one authorized normal-auth attempt returned HTTP 200 for player JS, auth1, and auth2. The fixed standard timefree playlist POST returned HTTP 404 (`text/html`, 146 bytes, no redirect). No HLS manifest or audio segment was obtained. Segment count=0, WAV output=none, media ffmpeg conversion=0, ffprobe=0, validator=not reached. Only the local ffmpeg `-version` preflight ran. No retry or alternate endpoint was attempted. The diagnostic workspace contained no files and was removed; temporary driver files were deleted. The original WAV failure remains unclassified, so no code fix, full project regression, commit, or push was made.

## 2026-10-26 playlist route correction (pre-live validation)

`TimefreePlaylistSource` was changed from the stale generic Radiko playlist endpoint to GET station stream XML, exact `areafree=0,timefree=1` candidate selection, Safe Source API URL validation, and Smartstream timefree playlist GET construction. Authenticated GET request wiring into master/media HLS is covered by `FakeHttpTransport`; the test asserts the query structure and absence of POST. The worker integration fixture now uses a one-minute item because the current single-request source is bounded to one 300-second tf30 interval. The local isolated source/capture/ffmpeg suites passed 102 tests. Full backend discovery passed 296 with one PHP/source-environment skip; a retry using the documented PHP fixture environment is in progress. Frontend typecheck, lint and build passed (lint has five existing warnings); UI suite passed schedule 148 and is continuing reservation/playback. The initial build/UI attempts failed only because sandbox process/localhost restrictions; reruns were made with those permissions. No live request has yet been sent for this correction.

## 2026-10-26 final regression and bounded live result

The corrected source/capture/ffmpeg suite passed 102 tests in network-none isolation. Full backend discovery, including PHP/source fixture tests, passed 296 tests with 0 skipped in the network-none Python 3.12 container. `py_compile` passed for 34 Timefree/backend test files; PHP syntax passed for `worker.php` and `fixture-bindings.php`. Frontend: schedule UI 148 PASS, reservations UI PASS at 360/1280 widths, playback/navigation 21 PASS at 360px; `npx tsc --noEmit` PASS, lint 0 errors/5 warnings, production build PASS; `git diff --check` PASS.

The bounded live sequence completed ordinary auth (auth1/auth2 200), then stream XML GET 200 (application/xml, 1,317 bytes, no redirect). It found eight URL nodes, including two target `areafree=0,timefree=1` candidates, and the XML contained hosts outside the current allowlist. The provider rejected ambiguous selection with `PLAYLIST_INVALID`; no playlist GET, HLS manifest, segment, media ffmpeg, ffprobe, WAV, validator, or publisher step followed. This hit the explicit unknown-host stop condition. No allowlist change or speculative candidate selection was made. Full native dat/sh and atq fingerprints matched before/after; all gates remained OFF, readiness false, and production services remained Up.

## 2026-10-26 candidate policy update before live retry

After the prior XML stop, the candidate selector was changed to retain XML order and choose the first exact-allowlisted candidate among matching `areafree=0,timefree=1` entries. Unknown candidates are recorded only as sanitized metadata and skipped; no fallback to an unknown host exists. Fixture coverage includes ordering, duplicates, multiple approved candidates, malformed URL, HTTP, private/local, userinfo and path restrictions. Focused source/capture/ffmpeg suite: 105 PASS, network none. No live request has been made with the new policy; full pre-live regression is pending.

## 2026-10-26 approved candidate and ffmpeg diagnostic

The ordered candidate policy selected the first approved match, `tf-f-rpaa-radiko.smartstream.ne.jp`, without contacting any unapproved host. Stream XML was 200/1,317 bytes; selected playlist GET 200/195 bytes; master and media 200 (one variant; media 10,256 bytes). Two segment files only were fetched from the approved host: 31,707 and 30,930 bytes, application/octet-stream, AAC ADTS; EXTINF 5.035 seconds each and parsed frame duration 5.034667 seconds.

The bounded production transcoder completed with ffmpeg return code 0, 0.597 seconds, stderr 0 bytes; WAV size 1,933,390 bytes. ffprobe: WAV, pcm_s16le, s16, 48,000 Hz, 2 channels, 10.069333 seconds. Internal RIFF validator reason: `UNEXPECTED_SAMPLE_RATE` (external `ffmpeg_output_invalid`). The failure path did not retain input expected-rate or RIFF chunk metadata, so the precise origin of the mismatch cannot be classified. No validator/argv/concat change is justified from this incomplete record. Workspace cleanup was confirmed; no additional Radiko request was made.

All offline regression for candidate policy passed before this live check: backend 299/0 skipped; focused source/capture/ffmpeg 105; schedule 148; reservations UI PASS; playback/navigation 21; typecheck/build PASS; lint 0 errors/5 warnings; Python 34-file compile, PHP syntax, diff check, secret scan PASS. Both gates remained OFF and native dat/sh/at fingerprints were unchanged. No commit/push because ffmpeg root cause remains unresolved.


## 2026-10-28 sample-rate diagnosis and regression

A later saved-segment diagnostic passed locally without another Radiko request: ADTS core rate 24,000 Hz, bounded input ffprobe decoded rate 48,000 Hz, stereo; ffmpeg 7.1.1-Jellyfin exited 0 and output WAV/pcm_s16le/s16/48,000 Hz/stereo, 5.034667 s, 966,734 bytes. RIFF and validator checks passed at expected=actual=48,000 Hz. The older two-segment `UNEXPECTED_SAMPLE_RATE` run did not retain input, expected-rate provenance, or RIFF evidence. The later successful run does not prove the old run's cause. Its cause remains unconfirmed and was not reproduced.

Current code includes a local input ffprobe step using only an allowlisted executable, argv, `shell=False`, file-only protocol, bounded output/time and strict AAC/rate/channel checks. WAV validation remains strict. This implementation state is not evidence that it repaired the unconfirmed earlier failure. Synthetic AAC tests cover 44.1/48 kHz, mono/stereo, 1/2/3 segments and the 24→48 kHz core/decoded-rate case. Backend full discovery: 300 PASS / 0 skipped in a disposable network-none, read-only-root Python 3.12 + PHP container. `compileall` PASS; PHP syntax PASS for the three existing PHP files. Schedule UI 148 PASS, reservation UI 24 scenarios PASS at 360/1280px, playback/navigation 21 PASS. Typecheck PASS; lint 0 errors / 5 existing warnings; production build PASS. `git diff --check` and secret scan are recorded in the development log.

The initial diagnostic wrapper failed before invoking the original validator while attempting to probe a copied temporary output; the saved WAV was independently probed and parsed, then the corrected production transcoder was successfully rerun from the already saved segment. No second segment download occurred. Temporary diagnostic media are removed only after the final checks. Gates remain OFF, `ready=false`, `bridge_approved=false`; no publisher, recording, or deploy path was used.

## 2026-10-28 bounded HE-AAC rate confirmation

At the committed sample-rate fix (`83b204d`), a fresh one-segment observation revalidated the complete diagnostic path without repeating the full suite. Seven ordinary-auth/stream-XML/playlist/HLS/segment HTTPS requests returned 200 without redirects, all against `radiko.jp` or the already approved `tf-f-rpaa-radiko.smartstream.ne.jp`; one segment only was downloaded. It was 31,707 bytes, AAC ADTS, `application/octet-stream`, EXTINF 5.035 s. Input ffprobe reported HE-AAC, decoded rate 48,000 Hz, stereo; the ADTS parser reported core rate 24,000 Hz and 5.034667 s. These are distinct rates for the observed HE-AAC stream. Before ffmpeg, `EXPECTED_SAMPLE_RATE=48,000` was sourced from the bounded input decoder probe and matched `INPUT_SAMPLE_RATE=48,000`.

The shell-free production AudioTranscoder exited 0 (0.191 s). Output ffprobe reported WAV/pcm_s16le/s16, 48,000 Hz stereo, 5.034667 s, 966,734 bytes. RIFF chunks were `fmt `/`LIST`/`data`; block align 4, data offset 78, declared and actual payload 966,656 bytes, 241,664 frames. WAV header rate and validator actual were both 48,000 Hz; internal reason=None and validation PASS. The input segment and output WAV were deleted after diagnostics. No publisher or recording ran.

Targeted network-none `test_timefree_ffmpeg.py`: 14 PASS. The backend full suite (300 PASS/0 skipped), frontend UI tests, typecheck, lint, build, compileall and PHP syntax had already passed at this same code HEAD and were not redundantly rerun, as requested. Pre/post native fingerprints exactly matched (rsv 10, dat/sh 76, atjobs 7, atspool 2, atq 6); no native change occurred. Both write gates remained OFF, production capture `ready=false` / `bridge_approved=false`, active-like reservation/weekly/recording counts were zero and no Timefree job table existed. No worker deployment or program recording occurred.

## 2026-10-28 isolated whole-program E2E preflight stopped

The bounded JP13 guide scan returned HTTP 200 for seven radio dates (2026-10-21 through 2026-10-27) and identified 271 ended, timefree-eligible 180–300 second entries with the required metadata flags. None overlapped the five parsed native reservations. The source/recording conflict gate then stopped every candidate: the existing ordinary-recordings root has 590 audio files, of which one filename is outside the strict known recording format; the native-timefree root has 371 audio files, all parseable. Existing `RecordingInventory` correctly maps the ambiguous ordinary file to `recordings_unknown`, so no candidate was selected. Its basename was not recorded. The remaining uncertainty means a duplicate cannot be ruled out safely.

The final diagnostic attempt made seven public guide GETs only. Across four complete guide scans after harness startup fixes, 28 guide GETs returned 200 (seven per scan); no station stream XML, auth1/auth2, playlist, HLS, segment, or audio request followed the inventory block. No segment, WAV, test job DB row, publisher output, or recovery action was created. `ready=false`, `bridge_approved=false`; both production gates remained OFF. No production DB, normal recording root, publisher root, native reservation, dat/sh/at spool, container, or worker was written/restarted/deployed.

The isolated ffmpeg/ffprobe version probe passed in a network-none read-only non-root container. The full backend/frontend suite was not run because E2E did not pass its duplicate-inventory preflight; no repository code changed. The older multi-segment `UNEXPECTED_SAMPLE_RATE` remains cause-unconfirmed; the separate recent one-segment run passed but does not prove the older failure was fixed.

### 2026-10-28 ordinary recording inventory compatibility

The one unresolved filename was the rfriends `[SHT]` short-recording prefix on an otherwise canonical `LFR_title_YYYYMMDD_HHMM_HHMM.m4a` name. The parser now accepts only that exact marker in addition to the unchanged canonical pattern. It retains the full named schedule interval for duplicate protection, regardless of the short media duration. The file was confirmed read-only as MP4/M4A with HE-AAC 48 kHz stereo (29.781333 s) and an MJPEG cover-art stream; its temporary test copy was removed.

An isolated read-only scan found 590 audio files, 590 known, 0 unresolved/errors. The old 589 station/start/end parse results were unchanged; the single added parse was the `[SHT]` file. Inventory tests 14 PASS; inventory/runtime/timefree/bootstrap 78 PASS. Full backend discovery before the final inventory case: 313 tests, 311 PASS, 2 environment ffprobe timeouts, 0 skipped; after the final case, focused inventory/runtime/timefree/bootstrap tests: 78 PASS. Frontend: schedule 148, reservations 24 scenarios, playback/navigation 21 PASS; typecheck/build PASS; lint 0 errors / 5 warnings. No Radiko request, recording, DB change, or native write occurred. Candidate-level guide records were not locally cached, so candidate reselection was deferred without network.


## 2026-10-28 final `[SHT]` regression
Final backend full discovery against the latest inventory test state: 314 PASS / 0 skipped. The first rerun failed because the isolated tmpfs did not permit execution of fake `at` helper scripts; enabling `exec` on the test-only tmpfs fixed the environment. No source/test assertion was relaxed and no production code was changed for this issue. Prior synthetic ffprobe timeout errors did not recur using the pre-existing portable Jellyfin ffprobe wrapper. Frontend schedule 148, reservation 24 scenarios, playback/navigation 21, typecheck and build all passed; lint had 0 errors / 5 warnings. Inventory: 590 known of 590, 0 unresolved, prior 589 interpretations unchanged. This section records validation only; no Radiko guide/auth/media request was made.

## 2026-10-28 short-program E2E area-consistency stop

After the final 314/0 backend and frontend regressions, the inventory checkpoint was committed/pushed at `b31960307c3ee132e22b12f0b62489e86dbd9294`. The allowed seven-day JP13 guide read returned 200 for all seven days and produced 435 eligible 3–10 minute entries. Shortest candidate passing native and ordinary recording overlap checks and approved-source resolution: LFR, `看板娘ホッピー・ミーナのHOPPY HAPPY BAR`, 2026-10-27 21:57–22:00 JST.

The isolated normal-auth path reached the area consistency guard and stopped because the authenticated area differed from JP13. No playlist/HLS/segment request or subsequent media/publisher/test-DB/recovery step occurred. No region override was attempted. Production DB and source roots were read-only; only the dedicated test root was writable. Production gate/readiness settings remained OFF/false. Native rsv fingerprint and atq listing matched the pre-run snapshot. An unrelated native recording was already running and was left alone.

## 2026-10-29 authenticated-normal-area isolated E2E

The ordinary pc_html5 auth returned area `JP28` while configured area remained `JP13`; this was recorded as a mismatch and did not change configuration. The official station-region catalog contained 109 valid station IDs and 88 unambiguous valid area mappings. Malformed/ambiguous area rows remain unresolved for candidate selection, while valid official IDs are retained separately for native reservation parsing. No guessed area mapping was added.

The seven guide dates contained 371 otherwise eligible ended 3–10 minute entries; 130 mapped to the authenticated normal area. After native reservation, the 590-file ordinary/native recording inventory, active RadioFlix state, and approved source checks, the shortest safe choice was CRK / Radio Kansai, `心に光を`, 2026-10-22 06:00–06:05 JST (300 seconds). This is a normal-auth, `areafree=0` path; no Premium/session or area override was used.

The isolated capture fetched and checked 61 ordered AAC/ADTS segments, 1,853,606 bytes total. Every segment was AAC-LC, stereo, decoded 48 kHz (ADTS core 24 kHz); segment framing and format consistency passed. The exact EXTINF sum was checked against the 300-second program bound in the capture process but was not persisted after a harness exception; do not report an exact EXTINF total from this run. ADTS-decoded total was 299.989333 seconds.

Shell-free ffmpeg exited 0. ffprobe reported WAV/PCM16, 48 kHz stereo, 299.989333 seconds, 57,598,030 bytes. RIFF `fmt `/`LIST`/`data` chunks, 4-byte block alignment, 57,597,952 declared/actual payload bytes, and zero trailing bytes passed the strict WAV validator. Duration differed from the broadcast interval by 0.010667 seconds.

The existing Publisher wrote only to the dedicated `/tmp` test publish root using hidden staging and no-overwrite atomic publication. The test DB reached `completed`, the asset was recognized once, and a second reconcile was idempotent with no duplicate event/output; staging was empty. Test artifacts are retained under `/tmp/radioflix-timefree-e2e-20261029/run-0545` for review. Production DB and recording roots were read-only and unchanged.

Backend full discovery: 330 PASS / 0 skipped. Frontend: schedule 148, reservation 24 scenarios, playback/navigation 21 PASS (one initial seek-wait timeout passed on immediate rerun); typecheck/build PASS, lint 0 errors / 5 existing warnings. Python compile, `git diff --check`, and secret-pattern scan PASS. Production gates remained OFF, `ready=false`, `bridge_approved=false`; no production worker was deployed and native rsv/dat/sh/at fingerprints/atq were unchanged.

## 2026-10-29 isolated catalogue-to-audio integration

The retained completed CRK fixture was copied under `/tmp` and exercised through the ordinary API handlers with an explicitly fixture-enabled test catalog. `/api/programs` returned one timefree program; `/episodes` returned one episode with the same broadcast ID across reloads and reconciles; `/audio` returned the published WAV with `audio/wav`, expected `Content-Length`, and valid 206 byte-range responses. Invalid range returned 416; traversal returned 404; existing HEAD behavior is 405. The shared frontend player used the ordinary playback route and state key, preserving the persistent player through route changes and supporting rate/seek controls. Media Session metadata/state was checked where Chromium exposes it. Read/progress remains the existing localStorage mechanism; favorites remain the existing title-based list, with no separate timefree favorite behavior introduced.

The timefree listing fails closed when ordinary recording inventory cannot be fully parsed, so unresolved ordinary files cannot permit a duplicate. A known overlapping normal recording wins display priority. The catalog does not mutate normal recording IDs, order, filenames, or files. Synthetic regression kept all 590 ordinary fixture filenames and parsed station/start/end intervals unchanged and verified normal M4A serving remains `audio/mp4`.

The saved test DB/WAV copy survived three additional reconcile passes: one completed DB row, one publication, one WAV, unchanged manifest/file hash and metadata, capture calls 0, ffmpeg 0, Radiko requests 0. Final backend discovery: 337 PASS / 0 skipped, including PHP/bootstrap/worker tests. Frontend: schedule 148 checks, reservation UI 24 scenarios, playback/navigation 26 checks; typecheck PASS, lint 0 errors / 5 existing warnings, production build PASS (the first sandbox build attempt hit the known Turbopack child-process port-bind restriction; the same build passed with the command-only approval). Final API/recovery runs used only the copied `/tmp` asset, network-none containers, read-only source, and no production/native mounts.
