# RadioFlix Development Status

## Last updated
2026-10-23 22:17:49 JST

## Current task
BLOCK 1: Safe Source API fixtureのレビュー、隔離回帰、独立checkpoint commit/push。

## Current phase
Phase 4 Safe Source API fixture（ProductionHttpTransportはNotReady）。

## Status
ready_to_commit

## Completed
- 実Git/ファイル状態を正とし、開始HEAD `4c1dd4bb5d65d1dbb6de39d05efb89d610a07564`、branch `main`、Safe Source API関連差分を確認した。
- Safe Source API fixtureの差分をreviewし、ProductionHttpTransportがNotReadyでsocket/DNS/HTTP clientへ到達しない境界を確認した。
- `ProductionHttpTransport.ready=false`でrequest時にNotReadyを返し、DNS/socket/HTTP clientを起動しないことをsource/testで確認。
- 前回作業の本番wire read-only調査では`radiko_auth_mode=0`を確認したが、`hls_type`・premium branch等は未確定。Block 2で継続調査する。

## In progress
- 明示allowlistでstageし、staged diffとsecret scanをreview後、Block 1を1 commit/pushする。

## Next actions
1. Block 1 allowlistを明示stageし、cached diff・secret scan・write gatesを確認する。
2. `Add fixture-safe RadioFlix source API`でcommit/pushし、HEAD・tracking ref・remote ref一致を確認する。
3. 自動的にBlock 2へ進み、rfriends3 source/configをread-only解析する。HTTP/DNS/録音/deploy/gate ONはしない。

## Blockers / Issues
- 現在のruntimeとvalidation docsに記録された未commit差分は、前回Safe Source API fixture作業から保持されている。破棄・reset/restoreしていない。
- 直近の既知wire未確定: effective `hls_type`、premium branch、全auth header/body/status、redirect/timeout/retry実効値、jobごとのplaylist base。

## Files changed
- 既存Safe Source API差分: `backend/radioflix/timefree/capture/adapter.py`、`backend/radioflix/timefree/capture/source/*.py`、`backend/tests/test_timefree_capture.py`、`backend/tests/test_timefree_sources.py`。
- schedule UI安定化: `frontend/tests/schedule-ui.mjs`（Next dev cold route compileを待つdiagnostic/120秒timeout。遷移要件維持）。
- docs: `docs/radioflix-timefree-source-api.md`、`docs/radioflix-timefree-runtime.md`、`docs/radioflix-timefree-phase4-validation.md`、このlatestと今回のhistory snapshot。
- `.codex/`、過去history、frontend Dockerfile backup等は無関係なuntrackedとして保持し、stage対象外。

## Git state
branch `main`、HEAD `4c1dd4bb5d65d1dbb6de39d05efb89d610a07564`。BLOCK 1は未commit。source API fixture差分とschedule test/doc差分を保持。`git reset` / `git restore` / `git add -A`不使用。

## Tests
- 前回記録（2026-10-21）: backend 257 PASS / 0 skipped、Source API 31 PASS、Capture Adapter 32 PASS、schedule 148 checks 3連続PASS、reservation 24、playback/navigation 21 PASS、typecheck/lint/build/PHP syntax/py_compile PASS。
- BLOCK 1再実行: Safe Source API + Capture Adapter 63 PASS。backend full discovery 257 PASS / 0 skipped（PHP CLI, driver fixture, offline worker source fixture mounted, network none）。Python syntax 62 files PASS、PHP syntax 3 files PASS。schedule 148 checksをserialで3回連続PASS。reservation UI 24 PASS、playback/navigation 21 PASS。tsc PASS、lint 0 error / 5 warnings、build PASS。git diff --check PASS。
- 初回isolated attemptsはnoexec tmpfsによるfixture executable failure、missing tmp bind、外部volumeなしのためのtest harness failures。test code変更なしでdedicated /tmp mountsに修正してPASS。並行schedule test timeoutは並列UI負荷中のみで、直列で3回連続PASS。
- 初回sandbox frontend buildはinternal port bindで失敗。権限付きlocal build再実行でPASS。
- 現在確認済み: `ProductionHttpTransport` request pathはNotReady fail-closed。実radiko通信0。

## Runtime / Safety
- commit前確認: backend `RFRIENDS_ENABLE_WRITES=0`、`RADIOFLIX_TIMEFREE_ENABLE_WRITES=<unset>`（OFF）。
- `ProductionBootstrap.ready=false`、`bridge_approved=false`。`ProductionCaptureAdapter.ready=false`、`bridge_approved=false`。`ProductionHttpTransport.ready=false`。
- 隔離testsはnetwork none、frontendはlocalhost mockのみ。ProductionHttpTransportはNotReady。実radiko認証/HTTP/HLS/録音0。本番worker deploy/restartなし。
- rfriends3/native rsv/dat/sh/at/通常録音領域は変更しない。

## Important decisions
- BLOCK 1だけを別commitにする。後続BLOCK 2 docs/analysisや将来のProduction Source実装を混ぜない。
- Explicit allowlist stagingのみ。無関係untracked history、`.codex/`、Dockerfile backupはstageしない。
- BLOCK 2で危険な未確定仕様が残る場合はProduction HTTPの前に停止する。

## Recovery instructions
次回はまず`git status --short`、`git diff`、HEADを確認。BLOCK 1のtest/stage/commit/push状態から続ける。実radiko通信、gate ON、本番deploy、実録音、rfriends3/native変更を行わない。

## at spool調査（2026-10-14、read-only）
- 10/12 before/after atjobs hash差は、17:25のrfriends3定時cronを挟んでおり、通常cronによるnative予約at job再生成が最有力。dat/sh aggregate hashと中身はbefore/after/currentで同一。
- RadioFlix隔離試験はproduction queue/mount非接続。at spool差分はRadioFlix操作由来ではないと判断。前後のjob ID別一覧がなく旧ID単位の削除/追加/変更は未確定。放送時刻自然消化よりcron再生成と整合。
- 過去の詳細atq情報は2026-10-14 read-only調査記録と既存history snapshotを参照。今回at/native queue操作なし。
