# RadioFlix Development Status

## Last updated
2026-11-05 05:36:29 JST

## Current task
Checkpoint 3 host PASS結果レビュー、論理変更限定commit/push（今回ユーザー明示承認済み）。本番操作禁止。

## Current phase
precommit

## Status
ready_to_commit

## Completed
- host resultとrun.UIkXmmCv/full.log確認。build/render/topology/5分E2E/boundaries/runner/backend full/catalog/API/cleanup全PASS、exit 0。
- backend 457件: pass 446、fail 0、error 0、skip 11。既存PHP CLI不足10件、隔離PHP/source未設定1件。docs/radioflix-timefree-checkpoint3.mdに全skip名を記録。
- sqlite ResourceWarning 1374件（直前runも1362件）。既存種別、新規リーク断定不可。deprecation warningあり。
- 全tracked diffと対象new filesをレビュー。git diff --check PASS。通常disabled/gates設計維持、300/302/62/73、capture attempt1/job retry0、normal60秒/8wire、second job不変確認。
- scope: acceptance profile/CLI/probe/shared admission、tests、専用Dockerfiles/Compose、2 runner scripts、関連docs、今回progress snapshot。
- 除外: .codex全体、backend/Dockerfile既存permission変更、source-api過去診断、frontend/backup/archive、以前のhistory等。既存差分保持。

## In progress
指定scopeのcommit/pushと同期確認。

## Next actions
1. commit/push後にHEAD/local origin/main/remote main一致を確認。
2. admission CLI→runner統合・approval引き渡しの未完了を解消/検証。本番job直insertやgate ONで補わない。
3. 次turnの承認範囲で最新revisionのbackend/acceptance image再同期、read-only preflight、runner dry-run。
4. 本番1番組acceptanceは別途明示承認後のみ。warningsは追跡する。

## Blockers / Issues
- host rehearsalはPASS。本番admission→runner統合未完了は本番実行前の課題。
- ResourceWarningの新規増分/漏洩元は未判定。明確な新規リークの証拠なし、今回commit blockerにしない。
- NAS Share非host UID bind制約はtest-only /tmp copyで回避。
- sandbox通常shellのremote DNS不可。承認済み昇格readでremote main=base HEADを確認。

## Files changed
今回commit対象の詳細はdocs/radioflix-timefree-checkpoint3.mdとcommit file listを参照。.codex/artifactは除外。post-commit最新ログ更新はNAS引き継ぎとして残す。

## Git state
- branch main; HEAD 4046b6f6020e983e9f84fcf81c2175027e5b22f0; local origin/main 4046b6f6020e983e9f84fcf81c2175027e5b22f0。
- phase precommit; commit/pushは今回明示承認済み、通常本番操作は未承認。
- historical dirty/untrackedは保持。reset/restore/cleanなし。

## Tests
- host full 457 / PASS446 / FAIL0 / ERROR0 / SKIP11。runner8件PASS、5分fixture E2E PASS。
- 今回git diff --check、syntax/staticレビューPASS。Docker再実行なし。
- 前回local FastAPI未導入による未実行はhost full PASSで補完。ただしadmission CLIとhost runnerの結合E2Eは未実装/未検証。

## Runtime / Safety
- production changes0、Radiko runtime通信0（host result確認）。今回Docker/production rebuild/recreate/job/gate/approval/capture/publish/rfriends3操作0。
- backend/worker/RFRIENDS gate0、worker disabled維持の設計。実稼働値/active weekly/reservationは今回再inspectせず未確認。
- acceptance program300s/audio302s/segments62/wire73/capture attempt1 retry0/job retry0。normal60s/8wire不変。

## Important decisions
- real Composeはhost、unitはfake境界。fixture runtimeはnetwork none、UID10001:20000、rootfs RO、caps drop、no-new-privileges、scripts RO。
- 本turnはcommit/pushまで。本番反映は次turn、別承認。

## Recovery instructions
AGENTS.md/当ログ/Git状態を照合。historyやartifactを無差別にstageしない。対象commit以外のdirtyは保持。host PASSと未完了の本番統合を混同しない。
