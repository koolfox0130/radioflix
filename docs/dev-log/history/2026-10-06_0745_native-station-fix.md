# RadioFlix Development Status

## Last updated
2026-10-06 07:45:53 JST

## Current task
rfriends3 native station=r1の互換修正と未知局の安全な扱い。writes=0でbackendのみ反映。

## Current phase
native互換修正・backend限定反映・read-only確認完了。次の受入試験指示待ち。

## Status
completed

## Completed
- AGENTS.md/latest/Git既存差分・runtime確認。Phase2 Android実機完了は維持。
- 開始時writes全7箇所0、4コンテナrunning。
- 実際の開始時native件数はdat11/sh11/at12。前日の記録12/12/13とは異なるが今回の変更前からの状態。今回snapshotを正として比較。
- rfriends3実コードの予約dat生成・局変換定義・番組表API局一覧を照合。r1=東京のNHKラジオ第1系、canonical JOAK（現番組表局名NHK AM（東京））。

## In progress
なし。実予約POST/DELETEは今回未実施。

## Next actions
1. 次の明示的なPhase3 once受入指示を待つ。再度preflight/DBバックアップ/未来番組選定から開始。
2. writes=0を維持。実予約・実録音・週次/タイムフリー、native変更なし。
3. commit/pushせず停止。

## Blockers / Issues
- 記録件数12/12/13は前日値。今回実数11/11/12を前後比較する。自然稼働の変化と今回操作を混同しない。
- PHP CLI非搭載による既存driverテストskipは区別して報告。
- 今回のnative互換ブロッカーは解消。Phase3は管理下の正式API受入を再開できる準備状態（実登録解除の成功を意味しない）。ブラウザ用認証プロキシ/Origin整備は今回対象外で未確認。

## Files changed
- backend/radioflix/services/schedule_service.py: nativeのみ局別名変換、未知局時刻保持、同時間帯の拒否、部分照合。
- backend/tests/test_schedule.py: 既存fixture内へ互換/未知局/不変の回帰試験追加。
- docs/dev-log/latest.mdと終了history。
既存差分保持。Broadcast公開schema・Compose・frontend・gateway・rfriends3・.env・secretは変更しない。

## Git state
main / 20b379703bc36818e5d37616cec927b19ba973c9。
開始時tracked8ファイル112追加/30削除。native parser/testは既存未追跡ファイル。stage/commit/push/reset/restoreなし。

## Tests
今回の結果は下記checkpointへ記録。過去119件109成功10skipは今回の成功と区別。

## Runtime / Safety
project radioflix、docker-compose.yml + docker-compose.rfriends.yml。
backendのみbuild/up --no-deps。frontend/gateway/rfriends3はrestart/recreateしない。writes全7箇所0維持、実APIはGETのみ。
native baseline: /home/kool-fox/Share/Radio/backups/radioflix-native-pre-station-fix-20261006_073831.json。
前回secret/native接続とrollback参照: history/2026-10-05_2324_backend-config-connect.md。

## Important decisions
- 稼働rfriends3 /home/user/rfriends3/script/config_sys_10.php のradiru_callsign_r1はtokyo:JOAK, sendai:JOHK, nagoya:JOCK, osaka:JOBK, sapporo:JOIK, hiroshima:JOFK, matsuyama:JOZK, fukuoka:JOLK。r2=JOAB、r3は地域callsignに-FM。
- rf_radiru.php radiru_rsv_ex_s_fmt1/fmt2はch_area形式でdatを作るが、tokyoまたはr2は接尾辞省略。radiru_hls_urlはr1hls/r2hls/fmhlsへ分岐。get_radiru_callsignは上記対応を使用。現在の非秘密地域設定radiru_area_1=tokyoを確認。
- get_radiru_callsign_newも存在しfm→r3と外部radiru_callsign_dbを参照するが、今回取得コード内でdb定義を確認できないため未検証のfm別名などは採用しない。
- 原因: NativeReservations.snapshotがnativeを直接Broadcastへ渡し、station大文字パターン違反のValidationError（ValueError派生）を一覧全体のexceptが捕捉、Noneを返す。
- native専用モデルに未知局のraw ID/時刻を保持。既知別名またはAPI既知局のみ照合。未知局の時間重複はnative_unknownで拒否、非重複候補はpartialとして既知局照合を継続。未知局の件数のみwarningに残しraw入力をログ出力しない。時刻/ファイル不正など全体不明は従来の安全停止を維持。

## Recovery instructions
1. AGENTS.md/latest/Git状態を照合し既存差分保持。
2. 次の実予約受入は別途指示後、現在のnative baselineと書込み安全値を再取得。
3. 記録はwrites=1や実録音の許可ではない。未知予約を除外して安全と扱わない。

## Preflight runtime
- radioflix-frontend: ID 5480a0de5bfb8b5f73688aac722d52b22983db4d68b6d291dfc7d0d82ce8ea5f、image sha256:d864eaa2df57da00e6bba8eaecf249688576e294943221c53e2f349f83f56a6d、StartedAt 2026-10-05T14:03:42.394490342Z、RestartCount 0。
- radioflix-backend: ID 15bbb7c2a388e2f373a34f2cd31eb6eb0b30cc702954af4083bc25fb227fa866、image sha256:ecd52b9d8aef7cbd467655d7528c93cd78ed6ffe128daae42b61312ab542bfdd、StartedAt 2026-10-05T14:20:33.697644155Z、RestartCount 0。
- radioflix-rfriends-gateway-1: ID 8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6、image sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68、StartedAt 2026-10-03T15:17:49.37234528Z、RestartCount 0。
- rfriends3: ID e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968、image sha256:da10070ca91ba4838e96a2205aa2993456dbcc2149c61bad26efd3058cc32c80、StartedAt 2026-10-03T15:17:49.325801073Z、RestartCount 0。

## radioflix-station-tests
backend unittest discover: 130件、120成功/10skip。既存109件成功を維持し新規11件成功。skipはPHP CLI不在の既存driverテスト。テスト依存Starlette/httpx非推奨警告あり。
py_compile: Python31ファイルPASS（生成物/tmp）。git diff --check PASS。今回変更ファイルのsecret pattern scan PASS。
使用コマンド: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/radioflix-config-test-deps:backend python3 -m unittest discover -s backend/tests -q（sandbox外、一時DB/fake Gatewayのみ）。
backend限定Compose build PASS。backend image sha256:b2eb892390e2f680cc0d02ee1e6ccb1c15a249a4569be74bb18ea9e774e0ba09。冒頭gateway名表示はあったが実際のexport/tagはbackendのみ。
backend限定up --no-deps --no-build PASS。GET /api/schedule HTTP200/availability ok、983番組checked、native11予約の競合11件（JOAK4件）一致。dat11/sh11/at12のfile名/size/hash/job情報は開始時snapshotと完全一致。active reservation/weekly=0/0、writes全7箇所0、非対象3コンテナ不変。


## radioflix-station-verification
{
  "writes_all_seven_zero": true,
  "unchanged_frontend_gateway_rfriends3": true,
  "backend": {
    "id": "4f9664cccfaedaf18373ff8682319ec143c51929e85a593a1de23c090854cbaa",
    "image": "sha256:b2eb892390e2f680cc0d02ee1e6ccb1c15a249a4569be74bb18ea9e774e0ba09",
    "status": "running",
    "started": "2026-10-05T22:44:39.876040961Z",
    "restarts": 0
  },
  "native_parsed": 11,
  "native_r1_to_joak": 4,
  "native_mount_readonly": true,
  "active_reservations": 0,
  "active_weekly": 0,
  "schedule_api": {
    "http": 200,
    "availability": "ok",
    "native_states": [
      "checked"
    ],
    "broadcasts": 983,
    "verified_conflicts": 11,
    "joak_conflicts": 4,
    "native_reservations_matched": 11,
    "safe_future_candidates": 899
  },
  "native_snapshot_unchanged": true,
  "native_counts": {
    "dat": 11,
    "sh": 11,
    "at": 12
  }
}
