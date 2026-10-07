# RadioFlix Development Status

## Last updated
2026-10-06 07:57:44 JST

## Current task
Phase3本番once受入。番組表未来1件の正式Bearer API登録・解除・writes=0復帰。

## Current phase
単発受入 PASS。最終結果記録。

## Status
completed

## Completed
- AGENTS.md/latest/Git差分・稼働状態確認。main / 20b379703bc36818e5d37616cec927b19ba973c9。
- 開始時4コンテナrunning、writes全7箇所0、active reservation/weekly 0/0。
- 新規DB backup integrity_check=ok。試験直前のnative snapshotを取得し今回状態との差分で判定。
- Phase2実機とnative互換修正は完了済み。今回週次/タイムフリーは対象外。

## In progress
なし。詳細は下記実測結果。

## Next actions
1. 次の毎週録音受入試験の明示指示を待つ。
2. 次試験時は新しい事前snapshot・backup・候補を取得。
3. commit/pushせず停止。

## Blockers / Issues
なし。単発本番受入PASS。毎週/タイムフリー本番受入は今回未実施。ブラウザ用Origin/認証プロキシは今回対象外。

## Files changed
今回リポジトリはlatest.mdと終了history。 .envのRFRIENDS_ENABLE_WRITESだけ試験中0→1→0とし、他設定・秘密値は変更しない。コード/Compose変更なし。DBには試験onceと解除履歴を保持。既存未commit差分保持。

## Git state
main / 20b379703bc36818e5d37616cec927b19ba973c9。
開始時tracked8ファイル112追加/30削除、既存未追跡API/UI/tests/docs/.codex/Dockerfile等あり。stage/commit/push/reset/restoreなし。

## Tests
- git diff --check PASS。今回変更ログのsecret pattern scan PASS（一致内容表示なし）。
- 終了時独立確認でもwrites全7箇所0、今回dat/sh/at消滅・所有履歴保持・録音未開始を確認。
今回の実測は下記JSON。POSTは1回だけ、2回目POSTは行わず新規dat/sh/at各1件と既存冪等性自動テスト結果で確認する。
過去backend130件120成功10skip（PHP CLI不在）は今回の実行ではない。今回コード無変更のためbuild/typecheck/lint/unit test再実行なし。

## Runtime / Safety
project radioflix、docker-compose.yml + docker-compose.rfriends.yml。
backend/gatewayのみ `up -d --no-deps --no-build rfriends-gateway backend` でフラグ反映。frontend/rfriends3はrecreate/restartなし。
秘密値はサーバー内ファイルからHTTP Bearerヘッダーにのみ使用し表示/ログ保存しない。nativeは正式API以外で変更しない。

## Important decisions
今回に限りユーザーが単発1件、writes=1とbackend/gateway最小recreateを明示許可。試験用atは開始2分前に実行される実装のため、その時刻より十分前に解除する。
検証失敗時もfinallyで今回IDの正式解除を試み、その後必ずwrites=0へ復帰。解除失敗なら直接削除せず残存を報告。

## Recovery instructions
1. 進行中に切断した場合、下記reservation IDと開始時刻を確認。今回IDの正式API解除を優先し、直接dat/sh/atを編集しない。
2. .env/effective Compose/backend/gateway Config.Env/PID1を0へ戻して全箇所確認。
3. 試験前runtimeとDB backupは下記参照。ログは別試験や週次の許可を与えない。

## Acceptance results
```json
{
  "preparation": {
    "snapshot": "/home/kool-fox/Share/Radio/backups/radioflix-native-pre-once-acceptance-20261006_075330.json",
    "backup": "/home/kool-fox/Share/Radio/backups/radioflix-reservations-pre-once-acceptance-20261006_075330.sqlite3",
    "backup_bytes": 36864,
    "integrity_check": "ok",
    "baseline_counts": {
      "dat": 11,
      "sh": 11,
      "at": 12
    },
    "active_reservations": 0,
    "active_weekly": 0,
    "candidate": {
      "id": "65fb95620b1358b9c55817312ad7393edee155f87754b2c80e22c6797761f10c",
      "station": "IBS",
      "title": "THE POWER OF WORDS ～Stories That Move Us～",
      "starts_at": "2026-10-06T08:55:00+09:00",
      "ends_at": "2026-10-06T09:00:00+09:00",
      "schedule_revision": "026aa8c1e9987e1ea05abb89fe07c0450adb4a746488dfd82145c2bd92ea1791",
      "native_state": "checked",
      "reservation_state": "unreserved",
      "date": "2026-10-06"
    },
    "matching_recording_title_found": false,
    "runtime_image_tags_match": true
  },
  "events": [
    {
      "time": "2026-10-06T07:56:28.028437+09:00",
      "event": "直前snapshot取得。writes=1への限定切替直前。"
    },
    {
      "time": "2026-10-06T07:56:33.803167+09:00",
      "event": "backend/gateway限定recreate成功。writes全7箇所1確認。正式POST直前。"
    },
    {
      "time": "2026-10-06T07:56:34.893865+09:00",
      "event": "正式POSTを1回実行。登録応答受信、反映確認中。"
    },
    {
      "time": "2026-10-06T07:56:35.367087+09:00",
      "event": "単発active1/weekly0、dat/sh/at各1件のみ増加、内容・所有権・native不変を確認。正式解除直前。"
    },
    {
      "time": "2026-10-06T07:56:35.414091+09:00",
      "event": "今回作成reservation IDを正式APIから解除する。"
    },
    {
      "time": "2026-10-06T07:56:36.103794+09:00",
      "event": "正式解除応答確認: cancelled"
    },
    {
      "time": "2026-10-06T07:56:36.106451+09:00",
      "event": "成功/失敗にかかわらずwrites=0へ復帰する。"
    },
    {
      "time": "2026-10-06T07:56:40.167110+09:00",
      "event": "writes全7箇所0へ復帰確認。最終照合中。"
    },
    {
      "time": "2026-10-06T07:56:40.732854+09:00",
      "event": "単発受入 PASS。最終結果記録。"
    }
  ],
  "post_attempts": 1,
  "delete_attempts": 1,
  "reservation_id": "e563c6f24cec4292b18ed6543b89a4e4",
  "pass": true,
  "immediate_snapshot": "/home/kool-fox/Share/Radio/backups/radioflix-native-immediate-once-20261006_075628.json",
  "immediate_counts": {
    "dat": 11,
    "sh": 11,
    "at": 12
  },
  "writes_one_all_seven_confirmed": true,
  "create_http": 200,
  "create_state": "active",
  "create_error_code": null,
  "registered_db": {
    "active_reservations": 1,
    "active_weekly": 0
  },
  "external_ref": {
    "state": "scheduled",
    "name": "20261006_085500_090000_IBS_radioflix_f17a4b5ab45e4aa2b87149b5c69fcfaf",
    "job_id": "1571"
  },
  "delta": {
    "dat": 1,
    "sh": 1,
    "at": 1,
    "native_unchanged": true,
    "new_files": [
      "20261006_085500_090000_IBS_radioflix_f17a4b5ab45e4aa2b87149b5c69fcfaf.dat",
      "20261006_085500_090000_IBS_radioflix_f17a4b5ab45e4aa2b87149b5c69fcfaf.sh"
    ],
    "new_at_job": "1571"
  },
  "ownership_checks": {
    "station": true,
    "title": true,
    "start": true,
    "end": true,
    "owned": true,
    "at_owner": true,
    "not_started": true
  },
  "registration_verified": true,
  "cancel_http": 200,
  "cancel_state": "cancelled",
  "cancel_confirmed": true,
  "writes_zero_all_seven_confirmed": true,
  "dotenv_restored_exactly": true,
  "final_native_unchanged": true,
  "final_db": {
    "active_reservations": 0,
    "active_weekly": 0
  },
  "history_retained": true,
  "unchanged_frontend_rfriends3": true,
  "gateway_backend_running": true,
  "finished": true
}
```

## Final runtime
```json
{
  "safety": {
    ".env": "0",
    "compose/backend": "0",
    "compose/rfriends-gateway": "0",
    "radioflix-backend/config": "0",
    "radioflix-backend/PID1": "0",
    "radioflix-rfriends-gateway-1/config": "0",
    "radioflix-rfriends-gateway-1/PID1": "0"
  },
  "containers": {
    "radioflix-frontend": {
      "id": "5480a0de5bfb8b5f73688aac722d52b22983db4d68b6d291dfc7d0d82ce8ea5f",
      "image": "sha256:d864eaa2df57da00e6bba8eaecf249688576e294943221c53e2f349f83f56a6d",
      "status": "running",
      "started": "2026-10-05T14:03:42.394490342Z",
      "restarts": 0
    },
    "radioflix-backend": {
      "id": "868829241a481cbd29689ed0ebfb8f33c67632978a7c0692aabc9c23bb93459d",
      "image": "sha256:b2eb892390e2f680cc0d02ee1e6ccb1c15a249a4569be74bb18ea9e774e0ba09",
      "status": "running",
      "started": "2026-10-05T22:56:39.082210935Z",
      "restarts": 0
    },
    "radioflix-rfriends-gateway-1": {
      "id": "0e1cf65fd1839d0a00cc3b4cd170214aa0d3109ba38464893ac56e9bf68bf1bb",
      "image": "sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68",
      "status": "running",
      "started": "2026-10-05T22:56:38.644553838Z",
      "restarts": 0
    },
    "rfriends3": {
      "id": "e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968",
      "image": "sha256:da10070ca91ba4838e96a2205aa2993456dbcc2149c61bad26efd3058cc32c80",
      "status": "running",
      "started": "2026-10-03T15:17:49.325801073Z",
      "restarts": 0
    }
  }
}
```

## Independent cleanup check
```json
{
  "dat_absent": true,
  "sh_absent": true,
  "at_absent": true,
  "ownership_history_retained": true,
  "recording_not_started": true
}
```

## Acceptance conclusion
今回だけ録音: PASS。正式Bearer APIでPOST1回/DELETE1回。登録時dat/sh/at各1増加、解除後開始直前snapshotへ一致。active reservation/weekly 0/0。毎週録音受入の準備状態YES（次の明示指示と新しいpreflight/backup/候補選定が必要）。
