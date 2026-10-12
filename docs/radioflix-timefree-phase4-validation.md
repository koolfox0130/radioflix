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
