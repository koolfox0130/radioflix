# RadioFlix Development Status

## Last updated
2026-10-19 12:36:41 JST

## Current task
Safe Capture Adapter fixtureを独立checkpointとして最終レビュー・commit・pushする。

## Current phase
Phase 4 Safe Capture Adapter fixture checkpoint。

## Status
ready_to_commit

## Completed
- job_idから正式DB metadataを再取得し、metadata/期限/duplicate/preflightを確認する共通Capture Adapter、auth/playlist/media/transcoder interface、fake fixture port、audio validationを実装。
- `TimefreeWorker`からAdapter contextを呼び、固定managed root配下のworkspace成果物を既存publisherへ渡す境界を追加。
- ffmpeg将来helperをargv + `shell=False` + executable allowlistに限定。実HTTP/HLSおよびproduction portは未実装、`ready=false` / `bridge_approved=false`。
- capture専用31 tests PASS、backend/PHP/worker全体225 tests PASS。Python compileall、PHP syntax 5 filesもPASS。
- schedule UI 148、reservation UI 24、playback/navigation 21 checks PASS。TypeScript PASS、lint error 0 / warning 5、production build PASS。
- backend containerからgate `RFRIENDS_ENABLE_WRITES=0`、`RADIOFLIX_TIMEFREE_ENABLE_WRITES=<unset>`を確認。実radiko通信/実録音/worker deployなし。

## In progress
- 対象差分の明示stageとstaged review後に、指定messageで1 commitを作成してorigin/mainへpushする。

## Next actions
1. Safe Capture Adapter本体、tests、worker接続、runtime/validation docs、latestと関連historyだけを明示stageする。
2. staged file list/diff、secret scan、`git diff --cached --check`を確認し、無関係untrackedが含まれないことを確認する。
3. `Add fixture-safe RadioFlix capture adapter`でcommitし、`origin/main`へpushしてHEAD・tracking ref・実remote refを照合する。
4. push後の最新状態をlatest/historyへ保存する。production source API開発・radiko接続・録音は開始しない。

## Blockers / Issues
- テストの初期再実行でtest-only volume上のffmpeg dummy directoryが既存だと失敗することを発見。`mkdir(exist_ok=True)`に直し、capture 31件および全225件を再実行してPASS。これはテスト再実行性の修正。
- 現行rfriends3に安全なauth/HLS source APIがないためproduction captureはNotReady。この点は今回のcheckpoint対象外。
- frontend mock testsはlocalhost serverを使うため単独実行。schedule 148、reservation 24、playback/navigation 21が終了コード0。

## Files changed
- `backend/radioflix/timefree/capture/`: Adapter、stage contracts、fixture ports、argv helper、production NotReady adapter。
- `backend/radioflix/timefree/worker.py`: Adapter capture contextからpublisherへの安全な引渡し。
- `backend/tests/test_timefree_capture.py`: 31 security/regression tests。
- `docs/radioflix-timefree-runtime.md`, `docs/radioflix-timefree-phase4-validation.md`: source仕様、安全境界、fixture検証記録。
- `docs/dev-log/latest.md`、関連するSafe Capture Adapter history snapshots。
- `.codex/`、frontend Dockerfile backups、bootstrap checkpoint history、その他の既存untrackedはstage対象外。

## Git state
branch `main`、HEAD `cd9fb4edbfb167cf1d6d23d6601689a1c7be35b7`。今回未commit、originへの更新なし。commit候補は上記allowlistのみ。無関係untrackedは保持する。`git reset` / `git restore`不使用。

## Tests
- 最終実行: capture adapter 31 PASS、backend/PHP/worker 225 PASS（bootstrap/Phase 1〜3を含む）、Python compileall PASS、PHP syntax 5 files PASS。
- frontend: schedule 148 checks PASS、reservation 24 scenarios PASS、playback/navigation 21 checks PASS、`npx tsc --noEmit` PASS、lint error 0 / warning 5、`npm run build` PASS。
- `git diff --check` PASS。secret-pattern scanはstage前の変更対象で0 findings、stage後にstaged contentを再scanする。
- backend/capture testsはnetwork none、read-only root、非root、cap-drop ALL、no-new-privileges。capture専用runはtmpfs noexecとtest-only write volume。native・通常録音領域・Docker socketはmountなし。UIはlocalhost mocks。

## Runtime / Safety
- `ProductionBootstrap.ready=false`、`ProductionBootstrap.bridge_approved=false`、`ProductionCaptureAdapter.ready=false`、`ProductionCaptureAdapter.bridge_approved=false`。
- `RFRIENDS_ENABLE_WRITES=0`、`RADIOFLIX_TIMEFREE_ENABLE_WRITES`未設定。両者を変更せず、testでは両方0。
- 実radiko認証/HTTP/HLS/録音: 0。production timefree worker containerなし。deploy/restart/recreateなし。
- native rsv/dat/sh/at、通常録音領域は未接続・未変更。rfriends3本体に変更なし。
- Safe Capture Adapter checkpointはcommit/push前。Safe Source API設計へは進めるが、production implementation/deploy/実録音は不可。

## Important decisions
- fixture Adapterをproduction workerに接続しない。production adapterはNotReady、二重gate OFF。
- `timefree_kwrec_ex()` / `rfriends_downloader()`とshell command経路を再利用しない。
- commit対象は今回のfixture境界とその検証・docs/logのみ。未追跡ファイルを一括stageしない。

## Recovery instructions
commit前に`git status --short`とstaged diffを確認する。push後も`ready=false` / `bridge_approved=false`、両gate OFF、実radiko通信0・録音0を維持し、次はSafe Source APIの設計から始める。

## at spool調査（2026-10-14、read-only）
- 10/12 before/after atjobs hash差は、17:25のrfriends3定時cronを挟んでおり、通常cronによるnative予約at job再生成が最有力。dat/sh aggregate hashと中身はbefore/after/currentで同一。
- RadioFlix隔離試験はproduction queue/mount非接続。at spool差分はRadioFlix操作由来ではないと判断。前後のjob ID別一覧がなく旧ID単位の削除/追加/変更は未確定。放送時刻自然消化よりcron再生成と整合。
- 過去の詳細atq情報は2026-10-14 read-only調査記録と既存history snapshotを参照。今回at/native queue操作なし。
