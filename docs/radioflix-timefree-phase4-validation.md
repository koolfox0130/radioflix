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
