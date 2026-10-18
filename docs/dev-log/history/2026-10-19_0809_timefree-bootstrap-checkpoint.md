# RadioFlix Development Status

## Last updated
2026-10-19 08:09:33 JST

## Current task
fail-closed RadioFlix timefree bootstrapとrfriends3 dependency investigationを独立checkpointとしてcommit/pushする。

## Current phase
Phase 4 fail-closed bootstrap checkpoint。Safe Capture Adapterは未実装。

## Status
ready_to_commit

## Completed
- 開始時branch `main`、HEAD/origin/main `2ad058817b520e85f8f830ac160bf617afbf9f69` を確認。checkpointと一致。既存のlatest変更・未追跡ファイルは保持。
- `/home/user/rfriends3/script/rf_timefree.php` と `rf_downloader.php` を稼働中rfriends3から読み取り専用で調査。2ファイルのhashはfixture manifestと一致。
- 直接依存候補として `rf_radiko.php`、`rf_gateway_def.php`、`rf_common04.php`、`rf_common.php` も確認し、6 sourceのpath/purpose/function/hash/requiredをbootstrap source manifestに記録。
- `timefree_kwrec_ex()` → `rfriends_downloader()`、認証/HLS → `rf_wget()` → `external_program()` → `system(command string)`、ffmpeg、temp、出力move、log/cleanup/post-processingまで関数単位で追跡し、A/B/C分類と結論をruntime docへ追記。
- 安全なauth/HLS取得用のargv型・path注入型library APIは現行sourceに存在しないと判定。両timefree関数はproduction bridgeから直接使わず、bridgeを作らずfail-closedを維持。
- `backend/radioflix/timefree/bootstrap.py` にallowlist/hash/path検証と二重gateのfail-closed境界を追加。bridgeは承認false/ready false固定で、PHPやrfriends関数を起動しない。
- 2026-10-19にbackend/PHP/worker、bootstrap、frontend回帰・型・lint・buildを再実行。schedule UIは中断前のrunがexit 0で148 checks PASS、その後の連続2 runもPASS。

## In progress
- rfriends3に副作用を隔離した認証・HLS・取得APIがない。rfriends3側で専用library API/argv境界を設けない限りcapture bridgeに進めない。
- production用PHP runtime/source bundle/secret/限定egressを備えた専用Composeは未作成。既存 `docker-compose.timefree.yml` はPython-only、`network_mode: none` でcapture用ではない。

## Next actions
1. 指定ファイルのみで `Add fail-closed RadioFlix timefree bootstrap` の1 commitを作成する。
2. `origin/main` へpushし、実remote refとHEADの一致を確認する。
3. 以後はrfriends3側の副作用なし・argv型capture APIを前提とするSafe Capture Adapterの隔離開発へ進む。実録音/本番deployは別途受入まで行わない。

## Blockers / Issues
- 現行sourceに安全に直接再利用できる境界なし。rfriends3変更なしでproduction capture bridgeを実装するのは危険。
- fingerprint一致だけでは副作用・shell command安全性を証明できない。
- `timefree_kwrec_ex()` を直接呼ぶとRadioFlix専用queueへ差し替えてもqueueを削除/再生成し、cancel marker時にprocess全体を終了する。
- `rfriends_downloader()` は組み立て済みshell stringを外部実行へ渡し、通常録音領域・移動・hookの既存設計に依存する。secret/auth/playlistの実データを読み取らず、安全なargv変換は今回未検証。
- 実radiko認証/HTTP/HLS/ffmpeg、実録音、production deployは未実施。実タイムフリー1本試験へ進めない。

## Files changed
- `backend/radioflix/timefree/bootstrap.py` / `control.py`: fingerprint/metadata/path/gate preflightをproduction appに配線。production bridgeはfail-closed。
- `backend/radioflix/timefree/bootstrap-source-manifest.json`: 6 direct candidate sourcesのallowlist/fingerprint。activation false。
- `backend/tests/test_timefree_bootstrap.py`: manifest/path/gate回帰6件。
- `docs/radioflix-timefree-runtime.md`: 現行source dependency graphとA/B/C分類、安全境界なしの判断。
- `docs/radioflix-timefree-phase4-validation.md`: read-only auditと今回の回帰検証。
- `docs/dev-log/latest.md` と今回のhistory snapshot。
- 既存未追跡 `.codex/`、`frontend/Dockerfile.dev-backup`、`frontend/Dockerfile.production`、既存historyは変更/削除していない。

## Git state
branch `main`。開始HEAD `2ad058817b520e85f8f830ac160bf617afbf9f69`。今回の指定checkpoint commit/push前。関係ファイルのみ明示stageする。既存 `.codex/`、Dockerfile backup、過去history等は除外して保持。`git reset` / `git restore` 不使用。

## Tests
- 2026-10-19 backend/PHP/worker: 194 tests PASS（Phase 1〜3回帰含む）。network none、read-only rootfs、UID1000、cap-drop ALL、両gate 0、専用test volumeのみwrite。
- bootstrap-specific: 6 tests PASS（allowlist/hash、missing/mismatch、traversal、symlink、gate OFF）。network none、read-only、両gate 0。
- Python syntax: backend 45 files compile PASS。PHP `-l`: worker/fixtureとmanifest対象6 source PASS。初回確認では不存在のtest-driver.phpを指定して失敗し、実在対象に絞ってPASS。
- UI mocks: schedule 148 checksを3連続run PASS（中断前runの完了ログ＋今回2回）、reservation 24 scenarios PASS、playback/navigation 21 checks PASS。すべてmock/localhostのみ。
- `npx tsc --noEmit`: PASS。
- `npm run lint`: error 0、既存warning 5。
- `npm run build`: PASS。初回sandbox時はTurbopack subprocess port bind不可で失敗、制約付き再実行PASS。
- source manifest: 稼働中rfriends3からread-only取得した6 fingerprintsと一致。
- `PYTHONPYCACHEPREFIX=/tmp/... python3 -m compileall -q backend`: PASS。PHP syntaxはworker/fixtureとmanifest 6 source PASS。
- `git diff --check`: PASS。
- secret pattern scan: PASS、変更/追加16ファイルで0 findings（内容は出力せず）。
- Compose build/configとproduction service testは未実施。ComposeにPHP/source/secret/egressがなく、実bootstrapが未接続のため。

## Runtime / Safety
- 稼働中backendの `RFRIENDS_ENABLE_WRITES=0`、`RADIOFLIX_TIMEFREE_ENABLE_WRITES` 未設定を確認。隔離testsでは両gate明示0。
- 実radiko認証/HTTP/HLS/音声通信: 0。backend/PHP/workerはnetwork none、UIはmock/localhostで外部originをabort。
- 実タイムフリー録音: 0。生成音声はsynthetic WAVのみ。
- native dat/sh/at: 試験containerへmountせず、全作業で読み書きなし。rfriends3 source調査はcontainer read-only exec/copyのみ。今回の作業由来変更なし。
- Docker read-only一覧でtimefree workerなし。worker deploy/restart/recreate、通常録音領域write、secret readなし。commit/pushはこのcheckpointで実行予定。
- production bootstrap deploy試験: NO。実タイムフリー1本試験: NO。

## Important decisions
- `timefree_kwrec_ex()` はqueue/process副作用があり直接呼び出さない。`rfriends_downloader()` もshell/config/output hookが結合しており丸ごと再利用不可。
- 現行rfriends3 sourceだけでは安全な直接再利用境界なし。独自のradiko認証/HLS再実装はせず、rfriends側の専用API追加まで停止する。
- source hash allowlistは必要条件であり、実行承認ではない。manifest更新だけでproduction bridgeを有効化しない。
- fixture modeとproduction modeは分離。fixtureは既存fake auth/HLS/downloader + synthetic WAVだけ。production transportはProductionBootstrap/ready falseを維持。
- 双方のwrite gateを変更せず、どちらかがOFFならproduction captureを起動しない。

## Recovery instructions
指定commit/push完了後、次回は隔離Safe Capture Adapter開発から再開する。`ProductionBootstrap.ready=false` / `bridge_approved=false`、gateを変更せず、実radiko通信・録音・deployを行わない。

## at spool調査（2026-10-14、read-only）
- 10/12 before/after atjobs hash差は、17:25のrfriends3定時cronを挟んでおり、通常cronによるnative予約at job再生成が最有力。dat/sh aggregate hashと中身はbefore/after/currentで同一。
- RadioFlix隔離試験はproduction queue/mount非接続。at spool差分はRadioFlix操作由来ではないと判断。前後のjob ID別一覧がなく旧ID単位の削除/追加/変更は未確定。放送時刻自然消化よりcron再生成と整合。
- 過去の詳細atq情報は2026-10-14 read-only調査記録と既存history snapshotを参照。今回at/native queue操作なし。
