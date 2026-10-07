# RadioFlix Development Status

## Last updated
2026-10-05 23:12:27 JST

## Current task
Phase 3本番受入: 番組表由来・録音履歴なしの未来番組1件を正式APIからonce登録・解除するための事前確認。

## Current phase
安全preflightで正式認証・native予約読取設定の未整備を確認。writes=0のまま停止。スナップショット/DBバックアップ完了。

## Status
blocked

## Completed
- AGENTS.md、frontend/AGENTS.md、latest、Git差分・runtimeを確認。
- ユーザーよりPhase 2 Android実機確認完了報告。番組表UI、曜日表示、画面遷移、再生継続すべて正常。
- branch main、HEAD 20b379703bc36818e5d37616cec927b19ba973c9。既存tracked差分7ファイル108追加/28削除。
- backend/frontend/gateway/rfriends3はrunning。
- .env、effective Compose backend/gateway、backend/gateway Config.Env/PID1のRFRIENDS_ENABLE_WRITESは全7箇所0。
- RadioFlix DB: active reservation=0、active weekly subscription=0。取消済み予約7件、取消済みweekly5件。
- backend Config.EnvでRADIOFLIX_WRITE_TOKEN_FILE、RADIOFLIX_WRITE_ORIGIN、RADIOFLIX_NATIVE_RESERVATIONS_DIRが未設定。

## In progress
なし。安全条件不足により本番登録・解除試験は未実施。

## Next actions
1. 正式な予約認証経路とnative予約read-only sourceの整備範囲を決める。
2. 整備後に再度preflight・DBバックアップ・候補選定から実施する。今回の候補を流用しない。
3. 条件が満たされるまでwrites=0を維持。週次/タイムフリー、直接dat/sh/at変更、commit/pushはしない。

## Blockers / Issues
- 正式予約APIはwrites有効時、RADIOFLIX_WRITE_TOKEN_FILE未設定なら403 authenticationを返す実装。
- 番組表由来予約はwrites有効時、native snapshotがunknownならnative_unknownで拒否する実装。RADIOFLIX_NATIVE_RESERVATIONS_DIR未設定。
- 認証回避・設定新設は今回の限定受入試験として実行しない。

## Files changed
今回リポジトリ内はdocs/dev-log/latest.mdと終了historyのみ。機能コード、Compose、.env変更なし。バックアップ/スナップショットは別途記載。

## Git state
main / 20b379703bc36818e5d37616cec927b19ba973c9。既存差分保持。tracked7ファイル108追加/28削除、番組表API/UI/ナビ/tests/docs/.codex/Dockerfile類の未追跡あり。stage/commit/push/reset/restoreなし。

## Tests
今回: runtime/safety/DB読取確認。正式API登録・解除・本番冪等性試験は未実施（上記前提不足）。build/typecheck/lint/UIテストはコード変更なしのため再実行なし。
過去結果: 曜日UI104、再生ナビ21、予約UI24成功、typecheck/build成功、lint既存警告5。今回の実行結果ではない。

## Runtime / Safety
project radioflix、docker-compose.yml + docker-compose.rfriends.yml。
writesは全箇所0を維持。1へ切替なし、recreate/restartなし、frontend/rfriends3変更なし、実予約/実録音なし。
active reservation/weekly 0/0。native dat/sh/atの直接変更なし。
前回frontend deploy/rollback情報: history/2026-10-05_2304_weekday-frontend-deploy.md。

## Important decisions
ユーザーは安全条件を満たす場合に限り今回once1件の登録解除と必要最小限backend/gateway recreateを許可。既存認証・native読取前提を満たさないため有効化前に停止する。以前の一般禁止から今回の条件付き許可へ更新されたが、未整備の安全機構を回避する許可ではない。

## Recovery instructions
1. AGENTS.md・latest・Git状態から再開。Phase 2実機は完了、Phase 3本番once受入は未完了。
2. 認証とnative読取設定を整備する作業の指示を受けてから再開。
3. 再試験時は新しい日時で候補を選び直す。成功/失敗を問わずwrites=0へ戻し、正式API以外で予約を変更しない。

## Preflight container IDs
- radioflix-frontend: 5480a0de5bfb8b5f73688aac722d52b22983db4d68b6d291dfc7d0d82ce8ea5f、image sha256:d864eaa2df57da00e6bba8eaecf249688576e294943221c53e2f349f83f56a6d、StartedAt 2026-10-05T14:03:42.394490342Z、RestartCount 0。
- radioflix-backend: 48a8c7223440610221f053c5bd1ade57b8b28d15a068c632c2da5f2908ae0b62、image sha256:ecd52b9d8aef7cbd467655d7528c93cd78ed6ffe128daae42b61312ab542bfdd、StartedAt 2026-10-03T15:17:49.372430449Z、RestartCount 0。
- radioflix-rfriends-gateway-1: 8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6、image sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68、StartedAt 2026-10-03T15:17:49.37234528Z、RestartCount 0。
- rfriends3: e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968、image sha256:da10070ca91ba4838e96a2205aa2993456dbcc2149c61bad26efd3058cc32c80、StartedAt 2026-10-03T15:17:49.325801073Z、RestartCount 0。

## radioflix-once-artifacts
```json
{
  "snapshot": "/home/kool-fox/Share/Radio/backups/radioflix-native-pre-once-acceptance-20261005_231117.json",
  "dat_count": 12,
  "sh_count": 12,
  "at_count": 13,
  "backup": "/home/kool-fox/Share/Radio/backups/radioflix-reservations-pre-once-acceptance-20261005_231117.sqlite3",
  "backup_bytes": 36864,
  "integrity_check": "ok"
}
```

## radioflix-once-final
```json
{
  "pid1_configured": {
    "RADIOFLIX_WRITE_TOKEN_FILE": false,
    "RADIOFLIX_WRITE_ORIGIN": false,
    "RADIOFLIX_NATIVE_RESERVATIONS_DIR": false
  },
  "deployed_code_matches_local": true,
  "schedule": {
    "http": 200,
    "availability": "ok",
    "writes_enabled": false,
    "native_states": [
      "unknown"
    ]
  },
  "native_snapshot_unchanged": true,
  "db": {
    "active_reservations": 0,
    "active_weekly": 0
  },
  "all_seven_write_flags_zero": true,
  "all_four_containers_unchanged": true,
  "candidate_selected": false,
  "reservation_post_count": 0,
  "reason_no_candidate": "正式認証とnative予約照合の前提不足により選定・登録段階へ進まず停止"
}
```
