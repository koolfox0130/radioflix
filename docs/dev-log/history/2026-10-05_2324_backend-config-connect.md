# RadioFlix Development Status

## Last updated
2026-10-05 23:24:06 JST

## Current task
RADIOFLIX_WRITE_TOKEN_FILEとRADIOFLIX_NATIVE_RESERVATIONS_DIRだけを本番Composeに接続し、writes=0で認証準備・native読取を確認。

## Current phase
2設定のbackend接続完了。native局ID r1と既存schemaの不整合でunknownが残存。writes=0で安全停止。

## Status
blocked

## Completed
- AGENTS.md/latest/Git差分・実環境を確認。Phase 2 Android実機はユーザー報告により完了。
- 開始時4サービスrunning、writes全7箇所0、active reservation/weekly 0/0。
- native dat12/sh12/at13をスナップショット保存。実ホストrsvとrfriends3コンテナ側のfile名/size/SHA-256一致。
- 既存secrets/rfriends_tokenは通常ファイル、owner kool-fox/group admin、permission 600、non-empty。内容は表示/ログ保存なし。

## In progress
なし。今回実予約POST/DELETEは未実施。Phase3本番受入はnative読取互換性問題により再開不可。

## Next actions
1. native局ID r1を含む予約の安全な照合について、実装修正の指示を待つ。黙って除外・大文字変換しない。
2. writes=0を維持。今回実予約/解除/毎週/タイムフリーは行わない。
3. commit/pushせず停止。

## Blockers / Issues
2設定未接続は解消したが、native dat4件のstation=r1がBroadcast.stationの大文字パターンに不一致。snapshot全体がNoneとなりnative_state=unknownのまま。読取失敗を隠すフィルタ等は追加しない。今回は設定のみの依頼のためコード修正せず停止。ブラウザ認証プロキシ/Origin整備も今回対象外。

## Files changed
- docker-compose.rfriends.yml: backendに2つのパス環境変数とnative予約read-only mount。既存secretのbackend側接続を同じパスの明示:ro bindへ変更。gatewayは既存secret定義のまま。
- docs/dev-log/latest.mdと終了history。
機能コード・frontend・.env・secretファイル・native予約は変更しない。既存差分保持。

## Git state
main / 20b379703bc36818e5d37616cec927b19ba973c9。
開始時tracked7ファイル108追加/28削除。既存API/UI/tests/docs/.codex/Dockerfile類に未追跡あり。今回Compose差分を追加。stage/commit/push/reset/restoreなし。

## Tests
結果は下記checkpointに記録。今回HTTPはGETのみ、認証・重複試験は一時DB/mockのみ。
過去: UI104/再生21/予約24、typecheck/build/lint成功。今回の結果とは区別。

## Runtime / Safety
project radioflix、docker-compose.yml + docker-compose.rfriends.yml。
backendのみ `up -d --no-deps --no-build backend`。build不要（既存imageのコード一致確認済み）。frontend/gateway/rfriends3はrestart/recreateしない。
RFRIENDS_ENABLE_WRITESは.env/effective backend/gateway/両Config.Env/PID1全7箇所0を維持。実予約/録音/POST/DELETEなし。
変更前snapshot: /home/kool-fox/Share/Radio/backups/radioflix-native-pre-config-connect-20261005_231723.json。
前回DB backup: /home/kool-fox/Share/Radio/backups/radioflix-reservations-pre-once-acceptance-20261005_231117.sqlite3（前タスク、integrity ok）。

## Important decisions
- RADIOFLIX_WRITE_TOKEN_FILEはbackend API dependencyが読む。stripした文字列32文字以上のBearer認証ファイル。未設定かつwrites=0なら従来待機モード、設定後はwrites=0でもmutation認証必須。GETは認証対象外。writes=1かつ未設定/読取不能/不一致は403。
- 同一管理範囲の既存backend/gateway用Bearer secretは形式互換、サーバー側のみで再利用。新規token生成・ブラウザ配布なし。RADIOFLIX_WRITE_ORIGINは今回変更せず、Origin付き操作は既存実装により拒否。
- RADIOFLIX_NATIVE_RESERVATIONS_DIRはbackend appがScheduleService/NativeReservationsへ渡す。直下.datを空白区切りで読み、先頭2列YYYYMMDDHHMMSS JST、7列目station。64KiB超/symlink/形式不明/読取不能/未設定はunknown。正常読取はchecked、同局時間重複はreservation_state=native_conflict、操作不可。
- 実体はinspectのbind sourceと実ファイルのハッシュ一致で確定: /home/kool-fox/Share/Radio/rfriends3/data/rsv。backend側は /native-reservations。予約ディレクトリだけ:ro、rfriends全体・録音領域の追加mountなし。

## Recovery instructions
1. AGENTS.md/latest/Git状態を照合。Phase2完了、Phase3登録解除はまだ未実施。
2. Phase3本番受入を再開する前にnative局IDの互換性問題を解決し、checkedとnative_conflict保護を再検証する。設定復旧が必要なら今回追加したbackendの2環境変数/native mountとsecret接続方式だけを見直す。rfriends3/native予約には触らない。
3. 本ログはwrites=1/実予約の許可ではない。次の指示に従う。

## radioflix-connect-test-results
py_compile PASS: 31 Python files（生成物は/tmp）。
docker compose config PASS（2 envパスと両mount read_only、writes=0）。
venv作成はensurepip不足で失敗、pip --target /tmpへ切替。backend tests実行済み。
backend unittest discover: 119件、109成功/10skip（PHP CLI不在による既存driverテスト）。認証・native unknown/競合・予約回帰はPASS。テスト依存からStarlette/httpx非推奨警告あり。
反映後検証でNativeReservations.snapshotの期待件数assert失敗。writes全箇所0は再確認済み。原因確定: native dat4件のstation=r1がBroadcast.stationパターン不一致。設定だけではunknownは解消せず。関連fixtureテストにはこの実データケースがない。
終了確認: GET backend /・frontend /schedule・番組表APIすべてHTTP200、availability ok。native_state unknownは未解消。
secret pattern scan PASS（今回変更ファイルのみ、秘密値ファイルを読まず既知credential形式を検査。完全な漏洩不存在の保証ではない）。git diff --check PASS。


## radioflix-connect-verification
{
  "token_path": "/run/secrets/rfriends_token",
  "token_nonempty": true,
  "token_permission": "0o600",
  "native_path": "/native-reservations",
  "native_files_readable": true,
  "native_snapshot": "unknown",
  "invalid_native_stations": [
    {
      "file": "20261007_001000_010000_r1.dat",
      "station": "r1"
    },
    {
      "file": "20261005_230500_000000_r1.dat",
      "station": "r1"
    },
    {
      "file": "20261006_001000_010000_r1.dat",
      "station": "r1"
    },
    {
      "file": "20261006_230500_000000_r1.dat",
      "station": "r1"
    }
  ],
  "both_mounts_kernel_readonly": true,
  "active_reservations": 0,
  "active_weekly": 0,
  "mounts": [
    {
      "source": "/home/kool-fox/Share/Radio/radioflix/secrets/rfriends_token",
      "destination": "/run/secrets/rfriends_token",
      "read_only": true
    },
    {
      "source": "/home/kool-fox/Share/Radio/rfriends3/data/rsv",
      "destination": "/native-reservations",
      "read_only": true
    }
  ],
  "unchanged_frontend_gateway_rfriends3": true,
  "backend": {
    "id": "15bbb7c2a388e2f373a34f2cd31eb6eb0b30cc702954af4083bc25fb227fa866",
    "image": "sha256:ecd52b9d8aef7cbd467655d7528c93cd78ed6ffe128daae42b61312ab542bfdd",
    "status": "running",
    "started": "2026-10-05T14:20:33.697644155Z",
    "restarts": 0
  },
  "writes_all_seven_zero": true,
  "http": {
    "backend_root": 200,
    "frontend_schedule": 200,
    "schedule_api": 200,
    "date": "2026-10-06",
    "availability": "ok",
    "native_states": [
      "unknown"
    ],
    "broadcasts": 490,
    "safe_native_conflict_check_verified": false
  },
  "native_snapshot_unchanged": true,
  "native_counts": {
    "dat": 12,
    "sh": 12,
    "at": 13
  }
}

## Preflight runtime
- radioflix-frontend: ID 5480a0de5bfb8b5f73688aac722d52b22983db4d68b6d291dfc7d0d82ce8ea5f、image sha256:d864eaa2df57da00e6bba8eaecf249688576e294943221c53e2f349f83f56a6d、StartedAt 2026-10-05T14:03:42.394490342Z、RestartCount 0。
- radioflix-backend: ID 48a8c7223440610221f053c5bd1ade57b8b28d15a068c632c2da5f2908ae0b62、image sha256:ecd52b9d8aef7cbd467655d7528c93cd78ed6ffe128daae42b61312ab542bfdd、StartedAt 2026-10-03T15:17:49.372430449Z、RestartCount 0。
- radioflix-rfriends-gateway-1: ID 8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6、image sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68、StartedAt 2026-10-03T15:17:49.37234528Z、RestartCount 0。
- rfriends3: ID e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968、image sha256:da10070ca91ba4838e96a2205aa2993456dbcc2149c61bad26efd3058cc32c80、StartedAt 2026-10-03T15:17:49.325801073Z、RestartCount 0。
