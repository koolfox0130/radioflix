# RadioFlix Development Status

## Last updated
2026-10-07 05:37:27 JST

## Current task
Phase3本番weekly受入。番組表未来1件の毎週録音・正式Bearer API登録・解除・writes=0復帰。

## Current phase
毎週録音受入 PASS。最終結果記録。

## Status
completed

## Completed
- AGENTS.md/latest/Git差分・稼働状態確認。main / 20b379703bc36818e5d37616cec927b19ba973c9。
- 開始時4コンテナrunning、writes全7箇所0、active reservation/weekly 0/0。
- 新規DB backup integrity_check=ok。試験直前のnative snapshotを取得し今回状態との差分で判定。
- Phase2実機とnative互換修正は完了済み。単発本番受入は過去PASS。今回は週次のみ、タイムフリー対象外。

## In progress
なし。詳細は下記実測結果。

## Next actions
1. Phase3の単発・毎週正式API受入完了。Phase4の明示指示を待つ。
2. 次試験時は新しい事前snapshot・backup・候補を取得。
3. commit/pushせず停止。

## Blockers / Issues
なし。今回の毎週録音正式API受入PASS。単発受入も前回PASS。Phase3の依頼された受入範囲は完了。翌週への実時間経過・ブラウザ認証導線・タイムフリー実試験は今回対象外。

## Files changed
今回リポジトリはlatest.mdと終了history。 .envのRFRIENDS_ENABLE_WRITESだけ試験中0→1→0とし、他設定・秘密値は変更しない。コード/Compose変更なし。DBには試験weekly・次回1件と解除履歴を保持。既存未commit差分保持。

## Git state
main / 20b379703bc36818e5d37616cec927b19ba973c9。
開始時tracked8ファイル112追加/30削除、既存未追跡API/UI/tests/docs/.codex/Dockerfile等あり。stage/commit/push/reset/restoreなし。

## Tests
- 今回: 正式weekly登録/解除 HTTP200、reconcile 3回すべてHTTP200。GET履歴関連・番組表毎週録音中確認。最終backend/番組表GET HTTP200。
- git diff --check PASS、今回変更ログのsecret pattern scan PASS。既存ソース差分は変更なし。
- 準備補助処理ではhost python不存在をpython3へ変更、候補抽出のdate参照を修正。いずれも予約操作前・writes=0で解決。余分に作成した新規backup/snapshotも保持し上書きなし。
今回の実測は下記JSON。POSTは1回だけ、2回目POSTは行わず新規dat/sh/at各1件と正式refresh API経由のreconcile 3回で冪等性確認する。
過去backend130件120成功10skip（PHP CLI不在）は今回の実行ではない。今回コード無変更のためbuild/typecheck/lint/unit test再実行なし。

## Runtime / Safety
- 直前 dat7/sh7/at8 → 登録後8/8/9 → 解除後7/7/8。既存全filename/size/SHA-256とatジョブのハッシュ不変。
- 登録05:36:13、解除05:36:19、writes全7箇所0確認05:36:23 JST。開始06:56より約80分前に解除、実録音なし。
- frontend/rfriends3 ID・StartedAt・RestartCount不変。rfriends3 RestartCount=0。backend/gateway既存imageで設定反映のみ。
project radioflix、docker-compose.yml + docker-compose.rfriends.yml。
backend/gatewayのみ `up -d --no-deps --no-build rfriends-gateway backend` でフラグ反映。frontend/rfriends3はrecreate/restartなし。
秘密値はサーバー内ファイルからHTTP Bearerヘッダーにのみ使用し表示/ログ保存しない。nativeは正式API以外で変更しない。

## Important decisions
- 週次が生成するreservation.modeは実装上once、subscription_idでweekly所有を確認。refresh正式APIは週次reconcileも呼ぶため同APIを3回実行。subscription/current reservation双方のID不変を実証。
- 先週次回候補10/14水曜06:56も確認済みだが、翌週予約を追加作成する試験は行わない。
- 単発受入の詳細はhistory/2026-10-06_0757_once-acceptance-pass.mdを参照。
今回に限りユーザーが毎週1件、writes=1とbackend/gateway最小recreateを明示許可。試験用atは開始2分前に実行される実装のため、その時刻より十分前に解除する。
検証失敗時もfinallyで今回IDの正式解除を試み、その後必ずwrites=0へ復帰。解除失敗なら直接削除せず残存を報告。

## Recovery instructions
- 終了時active reservation=0/weekly=0、writes全7箇所0。解除済みIDは再登録・再解除せず履歴として保持する。
1. 進行中に切断した場合、下記reservation IDと開始時刻を確認。今回subscription IDの正式API解除を優先し、直接dat/sh/atを編集しない。
2. .env/effective Compose/backend/gateway Config.Env/PID1を0へ戻して全箇所確認。
3. 試験前runtimeとDB backupは下記参照。ログは別試験やタイムフリーの許可を与えない。

## Acceptance results
```json
{
  "preparation": {
    "backup": "/home/kool-fox/Share/Radio/backups/radioflix-reservations-pre-weekly-acceptance-20261007_053431.sqlite3",
    "integrity_check": "ok",
    "snapshot": "/home/kool-fox/Share/Radio/backups/radioflix-native-pre-weekly-20261007_053431.json",
    "active_reservations": 0,
    "active_weekly": 0,
    "candidate_options": 150,
    "candidate": {
      "id": "70088ea4f99e9e8c2bd81d1554031e2bba9c7c4661e55365ab0383dbc88672db",
      "station": "INT",
      "title": "Shinagawa Info - Tagalog",
      "starts_at": "2026-10-07T06:56:00+09:00",
      "ends_at": "2026-10-07T07:00:00+09:00",
      "date": "2026-10-07",
      "schedule_revision": "a8abec6f1853dd3989352bd932dbe29e4ede704ca45170af4d806f06544df510",
      "native_state": "checked",
      "reservation_state": "unreserved",
      "allowed_actions": [
        "once",
        "weekly"
      ]
    },
    "weekly_match": {
      "station": "INT",
      "title_key": "shinagawainfotagalog",
      "anchor_weekday": 2,
      "anchor_time": "06:56:00",
      "next_week_availability": "ok",
      "next_week_candidates": [
        {
          "id": "6a59b98543e69eb589c7db06fa98121955a0b2e2b0fd010a429132c203f2f8b4",
          "title": "Shinagawa Info - Tagalog",
          "starts_at": "2026-10-14T06:56:00+09:00",
          "ends_at": "2026-10-14T07:00:00+09:00"
        }
      ]
    }
  },
  "events": [
    {
      "time": "2026-10-07T05:36:06.329438+09:00",
      "event": "直前snapshot取得。writes=1への限定切替直前。"
    },
    {
      "time": "2026-10-07T05:36:12.615251+09:00",
      "event": "backend/gateway限定recreate成功。writes全7箇所1確認。正式POST直前。"
    },
    {
      "time": "2026-10-07T05:36:13.935695+09:00",
      "event": "weekly正式POSTを1回実行。登録応答受信、反映確認中。"
    },
    {
      "time": "2026-10-07T05:36:14.654906+09:00",
      "event": "weekly1/予約1、dat/sh/at各1件、所有権とnative不変確認。reconcile3回直前。"
    },
    {
      "time": "2026-10-07T05:36:16.509725+09:00",
      "event": "weekly reconcile 1回目: 二重予約なし、ID・dat/sh/at不変。"
    },
    {
      "time": "2026-10-07T05:36:17.452301+09:00",
      "event": "weekly reconcile 2回目: 二重予約なし、ID・dat/sh/at不変。"
    },
    {
      "time": "2026-10-07T05:36:18.422396+09:00",
      "event": "weekly reconcile 3回目: 二重予約なし、ID・dat/sh/at不変。"
    },
    {
      "time": "2026-10-07T05:36:18.495747+09:00",
      "event": "weekly関連履歴・番組表の毎週録音中表示確認。正式weekly解除直前。"
    },
    {
      "time": "2026-10-07T05:36:18.498817+09:00",
      "event": "今回subscription IDを正式weekly APIから解除する。"
    },
    {
      "time": "2026-10-07T05:36:19.127085+09:00",
      "event": "正式weekly解除応答確認: cancelled"
    },
    {
      "time": "2026-10-07T05:36:19.128235+09:00",
      "event": "成功/失敗にかかわらずwrites=0へ復帰する。"
    },
    {
      "time": "2026-10-07T05:36:23.432986+09:00",
      "event": "writes全7箇所0へ復帰確認。最終照合中。"
    },
    {
      "time": "2026-10-07T05:36:23.906153+09:00",
      "event": "毎週録音受入 PASS。最終結果記録。"
    }
  ],
  "post_attempts": 1,
  "delete_attempts": 1,
  "reservation_id": "b1a081d87b1942578ff61c2018f9b307",
  "pass": true,
  "subscription_id": "a2df75bc67574a56904cae353d09532d",
  "reconciles": [
    {
      "iteration": 1,
      "http": 200,
      "active_weekly": 1,
      "active_reservations": 1,
      "subscription_id_unchanged": true,
      "current_reservation_id_unchanged": true,
      "dat_sh_at_unchanged": true,
      "schedule_state": "scheduled"
    },
    {
      "iteration": 2,
      "http": 200,
      "active_weekly": 1,
      "active_reservations": 1,
      "subscription_id_unchanged": true,
      "current_reservation_id_unchanged": true,
      "dat_sh_at_unchanged": true,
      "schedule_state": "scheduled"
    },
    {
      "iteration": 3,
      "http": 200,
      "active_weekly": 1,
      "active_reservations": 1,
      "subscription_id_unchanged": true,
      "current_reservation_id_unchanged": true,
      "dat_sh_at_unchanged": true,
      "schedule_state": "scheduled"
    }
  ],
  "immediate_snapshot": "/home/kool-fox/Share/Radio/backups/radioflix-native-immediate-weekly-20261007_053606.json",
  "immediate_counts": {
    "dat": 7,
    "sh": 7,
    "at": 8
  },
  "writes_one_all_seven_confirmed": true,
  "create_http": 200,
  "create_state": "active",
  "create_error_code": null,
  "registered_subscription": {
    "id": "a2df75bc67574a56904cae353d09532d",
    "state": "active",
    "station": "INT",
    "title": "Shinagawa Info - Tagalog",
    "title_key": "shinagawainfotagalog",
    "anchor_weekday": 2,
    "anchor_time": "06:56:00",
    "current_reservation_id": "b1a081d87b1942578ff61c2018f9b307",
    "schedule_state": "scheduled"
  },
  "registered_db": {
    "active_reservations": 1,
    "active_weekly": 1
  },
  "external_ref": {
    "state": "scheduled",
    "name": "20261007_065600_070000_INT_radioflix_1dbd682508f84b6ab5fd7878d79aa420",
    "job_id": "1590"
  },
  "delta": {
    "dat": 1,
    "sh": 1,
    "at": 1,
    "native_unchanged": true,
    "new_files": [
      "20261007_065600_070000_INT_radioflix_1dbd682508f84b6ab5fd7878d79aa420.dat",
      "20261007_065600_070000_INT_radioflix_1dbd682508f84b6ab5fd7878d79aa420.sh"
    ],
    "new_at_job": "1590"
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
  "schedule_ui_state": {
    "reservation_state": "active",
    "reservation_label": "毎週録音中",
    "native_state": "checked"
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
  "finished": true,
  "final_snapshot": "/home/kool-fox/Share/Radio/backups/radioflix-native-final-weekly-20261007_053700.json",
  "api_history_link_retained": true,
  "final_backend_schedule_http": 200,
  "final_runtime": {
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
        "id": "295f0e2a9096a10ffce650e06a9f61876058ea35240abf615082d8b40b923a1c",
        "image": "sha256:b2eb892390e2f680cc0d02ee1e6ccb1c15a249a4569be74bb18ea9e774e0ba09",
        "status": "running",
        "started": "2026-10-06T20:36:22.367505122Z",
        "restarts": 0
      },
      "radioflix-rfriends-gateway-1": {
        "id": "33d43c8efecb7cf815b65f09d97fc934ddd528d7f389b10e57212710c710226c",
        "image": "sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68",
        "status": "running",
        "started": "2026-10-06T20:36:22.170690173Z",
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
}
```
