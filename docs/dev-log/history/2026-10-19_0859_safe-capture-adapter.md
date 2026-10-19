# RadioFlix Development Status

## Last updated
2026-10-19 08:59:22 JST

## Current task
Phase 4 Safe Capture Adapterのfixture経路を実装し、隔離テストと既存回帰を完了する。

## Current phase
Phase 4 Safe Capture Adapter fixture。production HTTP/HLS/captureは未実装。

## Status
completed

## Completed
- `backend/radioflix/timefree/capture/` にDB job再取得・metadata/期限/重複/preflight検証、auth/playlist/media/transcoder/audioの注入境界、fixture実装、shell-free ffmpeg argv helper、production NotReady adapterを追加。
- `TimefreeWorker` はjob_idだけを渡してAdapter contextを受け取り、RadioFlix管理領域内のcapture workspace成果物を既存publisherへ渡す。公開前の音声検証と既存preflightを維持。
- rfriends3本体の既存調査結果を現行sourceの仕様として整理。認証mode、station/時間指定playlist、HLS/area context、tf30分割、ffmpeg/output検証の順序と安全上の停止条件をruntime docへ記録。rfriends3本体は変更せず、source取得はread-only。
- `ProductionCaptureAdapter.ready=false`、`bridge_approved=false` と既存 `ProductionBootstrap` の同じfalse状態を確認。実HTTP/HLS client、live port、production worker配線はない。
- backend/PHP/worker全体225件PASS。capture専用31件PASS。すべてのbackend試験containerはnetwork none、read-only root、UID1000、cap-drop ALL、no-new-privileges。capture専用runは`/tmp` noexec、専用test volumeのみwrite。native領域・通常録音領域・Docker socketはmountなし。
- Python compileall PASS。PHP syntax 5 files PASS。schedule UI 148 checks、reservation UI 24 scenarios、playback/navigation 21 checks PASS（localhost + mock API/audio）。`npx tsc --noEmit` PASS、lint error 0 / warning 5、production build PASS。
- `git diff --check` PASS。task対象13ファイルのsecret-pattern scanは0 findings。runtimeのbackend containerから `RFRIENDS_ENABLE_WRITES=0`、`RADIOFLIX_TIMEFREE_ENABLE_WRITES=<unset>` を確認。

## In progress
- fixture adapter境界は完成。production transportはNotReadyのままで、現行rfriends3認証/HLS helperはwget/`system(command string)`とglobal設定に結合しているため、安全な再利用APIはまだない。

## Next actions
1. production captureの前提となる、secretを漏らさない認証と許可host/segment制限付きHTTP/HLS APIの安全なsource境界を別途確定する。
2. その境界がレビュー可能になってから、二重gate OFFの隔離環境でproduction port実装・preflight・fixture置換テストを行う。
3. 本番deploy・gate変更・実radiko接続・実録音は別途受入と明示指示があるまで行わない。

## Blockers / Issues
- rfriends3の現行 `timefree_kwrec_ex()` / `rfriends_downloader()` およびそのauth/HLS下位helperに安全なargv/path注入境界がない。禁止されたrfriends3変更をせずにproduction captureを実装することはできない。
- frontend testを3本同時に起動した試行ではlocalhost資源競合が起きた。単独実行でschedule 148、reservation 24、playback/navigation 21がPASS。コード障害として再現していない。
- 初回host Python 3.11はPython 3.12向けpydantic_core不一致、最初の全backend containerはPHP/temp dir不足、最初の`/tmp noexec` backend全体runは既存fake at実行に不適合だった。専用isolated image/tmpfs設定に直した最終runは225件PASS。

## Files changed
- `backend/radioflix/timefree/capture/__init__.py`, `adapter.py`, `argv.py`, `errors.py`, `fixture.py`, `models.py`, `ports.py`, `production.py`: Safe Capture Adapterのfixture経路、stage ports、検証、shell-free将来境界、production fail-closed interface。
- `backend/radioflix/timefree/worker.py`: capture context成果物を既存publisherへ渡すworkspace境界。
- `backend/tests/test_timefree_capture.py`: job/metadata/duplicate/native unknown/path/shell/ffmpeg/audio/failure/cleanup/recovery/gateの31ケース。
- `docs/radioflix-timefree-runtime.md`, `docs/radioflix-timefree-phase4-validation.md`: source仕様、adapter境界、production要件、隔離検証記録。
- `docs/dev-log/latest.md` と本snapshot。
- `.codex/`、frontend Dockerfile backup、既存untracked history等は変更せず保持。

## Git state
branch `main`、HEAD `cd9fb4edbfb167cf1d6d23d6601689a1c7be35b7`（checkpointから不変）。今回commit/pushなし。Adapter・worker・docsの変更は未commit。既存 `.codex/`、Dockerfile backup、history等のuntrackedは保持。`git reset` / `git restore`不使用。

## Tests
- 今回実行: backend/PHP/worker 225 tests PASS、capture-specific 31 tests PASS、Python compileall PASS、PHP syntax 5 files PASS、schedule 148 checks PASS、reservation 24 scenarios PASS、playback/navigation 21 checks PASS、TypeScript PASS、lint error 0 / existing warnings 5、Next production build PASS、`git diff --check` PASS、secret-pattern scan 0 findings。
- network: backendとcapture testsはnetwork none。UIはlocalhost mock。実radiko hostへアクセスしていない。
- 初期環境不適合の失敗は上記Blockersに記録。最終有効設定でのrunはすべてPASS。

## Runtime / Safety
- production capture/bootstrap: `ready=false`, `bridge_approved=false`。production adapterはNotReadyで常に停止。
- backend containerのgate: `RFRIENDS_ENABLE_WRITES=0`、`RADIOFLIX_TIMEFREE_ENABLE_WRITES`未設定。値を変更していない。
- 実radiko認証/HTTP/HLS・実タイムフリー録音: 0。production worker deploy/restart/recreate: なし。
- native rsv/dat/sh/at、通常録音領域、Docker socketは隔離testにmountせず、今回書き込みなし。active reservation/weekly/timefree job件数はこの作業では再照会していない。
- production capture実装へ進める状態: NO（安全なrfriends3 source boundary待ち）。本番worker deploy: NO。実タイムフリー1本試験: NO。

## Important decisions
- `timefree_kwrec_ex()` / `rfriends_downloader()` は直接使わない。現行sourceはqueue/process、shell string、global/config、通常録音先副作用に結合。
- production adapterにHTTP/HLS/auth実装を追加せず、同じAdapter orchestrator上のfake auth/playlist/mediaとsynthetic WAVだけを使う。
- ffmpeg helperはargv list + `shell=False` + executable allowlist + 固定workspace/protocolに限定し、production経路へ接続しない。
- 両write gateをONにせず、fixture modeをAPI/envから切り替え可能にしない。

## Recovery instructions
次回はこの未commit差分を保持したまま再開。まず `git status --short` と `git diff` を確認する。次の作業は安全なauth/HLS/library API source boundaryの設計・レビューであり、現行の `ready=false` / `bridge_approved=false`、gate設定、実通信0・録音0を維持する。production境界が確立しなければfail-closedで停止する。

## at spool調査（2026-10-14、read-only）
- 10/12 before/after atjobs hash差は、17:25のrfriends3定時cronを挟んでおり、通常cronによるnative予約at job再生成が最有力。dat/sh aggregate hashと中身はbefore/after/currentで同一。
- RadioFlix隔離試験はproduction queue/mount非接続。at spool差分はRadioFlix操作由来ではないと判断。前後のjob ID別一覧がなく旧ID単位の削除/追加/変更は未確定。放送時刻自然消化よりcron再生成と整合。
- 過去の詳細atq情報は2026-10-14 read-only調査記録と既存history snapshotを参照。今回at/native queue操作なし。
