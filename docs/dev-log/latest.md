# RadioFlix Development Status

## Last updated
2026-11-03 07:15:54 JST

## Current task
Phase 4 checkpoint 1のみ：production capture/readiness/bridge guard修復・完成。one-job/acceptance CLIは対象外。

## Current phase
checkpoint 1全条件を検証済み。論理commit 1つとpushの直前checkpoint。

## Status
ready_to_commit

## Completed
- 既存差分を保全し、git status/diff --stat/diff --checkとHEADを実確認。main、開始HEAD fbdda3a06d8397dfe825550ee2bf5ec74810ba30。
- 実tracebackで循環経路を再現：recording_catalog→worker→admission→capture.errors/package __init__→production→admission.require_capture_start。
- contracts（stdlib dataclass/例外）、pure admission、runtime_policy、production実装に分離。TYPE_CHECKING/遅延importなし。既存例外import pathとclass identityを維持。catalog/API契約変更なし。
- ProductionAuthenticator→TimefreePlaylistSource→HlsMediaSource→既存FfmpegArgvTranscoder→validator→既存worker/Publisherを接続。owned filename間はno-replace link。
- refresh_readinessがsource/config/preflight/DB/schema/filesystem/staging/ffmpeg/ffprobeを通信なしで検査。readyはimmutable結果のsnapshotでguardからffmpeg/DBを実行しない。capture開始時に再検査。disabled factory/healthはlocal probeなし。
- bridge_approvedはlive外部captureの明示承認。readyと独立。実行RO storeと能力評価storeを分離。boot enabled AND Timefree gate AND ready AND bridge承認をpure policyで判定、RFRIENDS非依存。
- 前回16件を個別分類して全解消。A循環import1、B例外sanitize契約1、Cfixture ffmpeg symlink設定5、D隔離PHP PATH9。詳細はdocs/radioflix-timefree-checkpoint1.md。
- 安全制限維持：unknown host fail-closed、既存allowlist、bounded timeout/response、ENDLIST必須、合計2MiB、変換60秒、最大8wire request、path隔離/no-overwrite。ProductionMediaFetcher観測専用prefixは番組全体保証がないため既存HlsMediaSource使用。
- 本番操作0、Docker操作0、実Radiko/production endpoint通信0。fixtureはnetwork-none + Fake transport + 合成AAC/WAVのみ。

## In progress
コード・テスト完成。今回関連ファイルだけをstageし、ユーザーが条件付き承認したcheckpoint 1 commit/pushを行う。

## Next actions
1. stage対象一覧を確認して1つの論理commitを作成、origin/mainへpush。既存差分・監査一時資料を含めない。
2. commit/push後のGit実状態とdev-logを更新しhistory snapshot保存。
3. 次のユーザー指示でcheckpoint 2（指定1job acceptance）へ進める。今回は実装しない。
4. 本番image revision/root所有者/socket/ffmpeg設定は別途承認の再同期・監査で扱う。

## Blockers / Issues
checkpoint 1の新規regressionなし。skip1：旧hash固定rfriends PHP source未配置による互換テスト。今回のPython stackには不要、既存PHP driver/bootstrap testsはPASS。
本番B残課題は未変更：backend revision unknown、Timefree root1000:1000/0750、socket実permission/backend→worker疎通未確認。
NAS /usr/bin/ffmpegはsymlinkで既存allowlistにより拒否される。fixtureでは実体pathを既存preflight_allowlisted_pathで明示許可。本番側は別途設定確認が必要。任意長の番組は60秒等の制限外、今回拡大なし。

## Files changed
今回commit対象：
- backend/radioflix/timefree/contracts.py、admission.py、runtime_policy.py：pure契約・判定・runtime設定の一方向依存。
- backend/radioflix/timefree/capture/errors.py：既存例外pathの互換export。
- backend/radioflix/timefree/capture/production.py：既存source composition、local readiness snapshot、承認境界、transcoder接続。
- backend/radioflix/timefree/control.py、worker.py：factoryとlive実行guard。daemonの暗黙bridge承認なし。
- backend/tests/test_timefree_admission.py、test_timefree_production.py：guard/ready/bridge/source接続/disabled検証。
- backend/tests/test_timefree_sources.py、test_timefree_runtime.py：変更したready/live開始契約を明示。
- backend/tests/test_rfriends_driver.py：fake atに隔離PHP commandを引継ぐ（production PHP変更なし）。
- docs/radioflix-timefree-checkpoint1.md：責務・契約・16件分類・制限・検証。
- docs/dev-log/latest.md、今回ready snapshot：進捗。
既存backend/Dockerfile、docs/radioflix-timefree-source-api.md、未追跡.codex/history/backups/frontend資料は保持しstageしない。

## Git state
main、HEAD fbdda3a06d8397dfe825550ee2bf5ec74810ba30。upstream origin/main。今回commit/push前、index開始時空。reset/restoreなし。.codex/dxp-runtime-audit.txtはcommit禁止。

## Tests
今回実行（すべてテスト通信はnetwork-none）：
1. import smoke 15 modules PASS。collection 415時点errors0、最終fullでもcollection error0。
2. pure admission 4 tests PASS。
3. capture/guard/source/transcoder/bootstrap/inventory/area 164 tests PASS。
4. catalog/API/reservations/schedule/weekly 127 tests PASS。
5. Timefree/worker/recovery/gate/PHP driver 129 tests、128 PASS/skip1、fail/error0。
6. backend full discovery 420 tests / 17.238秒、419 PASS/skip1、fail0/error0。
- production adapter18 tests、pure guard4 testsを含む。前回16失敗は全解消。
- Python AST 80 files PASS、PHP worker.php/fixture-bindings.php syntax PASS、git diff --check PASS。
- frontend変更なし、UI/typecheck/lint/build未実施。
検証環境：/tmp/radioflix-phase4-venv（Python3.11）、/tmp/radioflix-phase4-tools/bin/php（PHP8.2）、NAS ffmpeg実体をfixtureへ明示許可。sandbox TestClient停止を避け、承認付きunshare -Urnでloだけのnetwork namespace内で実行。Dockerなし。本番Python3.14 imageは今回検証していない。
full command: unshare -Urn env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests PATH=/tmp/radioflix-phase4-tools/bin:/usr/bin:/bin /tmp/radioflix-phase4-venv/bin/python -m unittest discover -s backend/tests -q
前回405 tests fail6/error10/skip1は履歴であり現状ではない。

## Runtime / Safety
本番変更0、Docker実行0、gate/ready/bridge本番ONなし、本番job/publish/rfriends/native予約変更なし、実Radiko/production endpoint通信0。fixtureのみ/tmp DB/outputで合成変換・公開を検証。ネットワークを用いる予定操作は許可済みGit pushのみ。active weekly/reservation等本番状態は今回再監査しない。

## Important decisions
checkpoint 1完成条件を全て充足。新規regression0。旧PHP互換source欠如によるskip1は成功扱いせず限定事項として記録、checkpoint 1のPython adapter完成を阻害しない。one-job/CLIには進まず、次checkpoint用の基盤までで終了。

## Recovery instructions
AGENTS.md、本ログ、実git statusを読む。checkpoint 1完了後のcommit/push情報を確認。既存差分と今回変更を混同しない。ユーザー指示があればcheckpoint 2へ進めるが、本番変更・実通信は別途明示承認が必要。監査一時ファイルをcommitしない。
