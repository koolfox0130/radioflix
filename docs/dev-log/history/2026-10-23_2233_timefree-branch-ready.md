# RadioFlix Development Status

## Last updated
2026-10-23 22:32:43 JST

## Current task
BLOCK 2: rfriends3 production wire read-only audit completed; production implementation stopped at unresolved auth/HTTP safety contracts.

## Current phase
Phase 4 Safe Source API checkpoint pushed; Block 2 wire audit documented; ProductionHttpTransport remains NotReady.

## Status
ready_to_commit

## Completed
- Safe Source API fixtureをreview・隔離検証し、commit a7615f0f0f62d020d0256565f8caff5394c802ba (Add fixture-safe RadioFlix source API)をorigin/mainへpush。HEAD・tracking ref・実remote refの一致を確認した。
- ProductionHttpTransportはNotReadyでsocket/DNS/HTTP clientへ到達しない。
- Block 2 read-only: radiko_auth_mode=0, hls_type=0; timefree branch hardcodes tf30 helper; premium.ini numeric selectors premium=1/areafree=1/timefree30=0; auth1/auth2 retry/timeout options were redacted-extracted. Block 2 docs commits 780a359 and 3e93155 pushed after Block 1 a7615f0.
- rf_premium_mode()/product statusに依存するnormal-vs-premium auth mode、final HLS hosts、tf30/HLS request bounds、status/body contract、redirect/TLS policyが未確定でBlock 3未開始。

## In progress
- wire auditの確定/条件付き/未確定とProduction HTTPを止めた理由をruntime/source-api/validation docs、latest/historyへ修正記録した。corrective docs-only checkpointをreview・commit/pushする。

## Next actions
1. corrected current downloader/auth branch findingsをdocs-only follow-up checkpointとして保存する。
2. ProductionHttpTransportはNotReadyのまま維持する。未確定wire事項の安全な解決が得られるまでBlock 3へ進まない。

## Blockers / Issues
- rf_premium_mode()/product statusによるcapture auth modeが未確認。tf30 branchはtimefree-specific caseでhardcode。auth retry/timeoutはredacted確認済みだがtf30/HLSはrequest boundsなし。response contract、redirect safety、final stream host setが未確定。
- 既存auth wgetはTLS検証を無効にし、PHP stream wrapperもpeer/name verificationなしで、redirect先host再検証がない。安全なProduction HTTPへそのまま移植できない。

## Files changed
- Block 1 implementation/tests committed at a7615f0; Block 2 wire docs committed at 780a359 and effective option follow-up at 3e93155.
- Current correction docs-only change: docs/radioflix-timefree-source-api.md、docs/radioflix-timefree-runtime.md、docs/radioflix-timefree-phase4-validation.md、this latest、current history snapshot。
- .codex/、以前からの無関係history、frontend Dockerfile backupsは未追跡のまま保持し、stage対象外。

## Git state
branch main。HEAD/origin/main/実remote=3e93155fb5ab9c3ac6a7ee638aed633c1a475ad8で一致。current source-branch correction docs/latest/historyのみworktree差分。既存untrackedを保持。reset/restore/add -A未使用。

## Tests
- Block 1: Source API + Capture Adapter 63 PASS; backend discovery 257 PASS / 0 skipped（isolated PHP/driver/offline worker fixtures, network none）; Python syntax 62 files PASS; PHP syntax 3 files PASS.
- schedule UI 148 checksを直列で3回連続PASS。reservation UI 24 PASS、playback/navigation 21 PASS。tsc PASS、lint 0 errors / 5 warnings、build PASS。
- git diff --check PASS、staged diff check PASS、16 explicitly staged filesのsecret-pattern scan PASS。
- 初回fixture環境attemptでnoexec/missing /tmp mounts、並行UI負荷のschedule timeout、sandboxのbuild internal port bindが出た。test harness/mountと実行方法のみを是正して全検証を通し、アプリコード変更はしていない。
- Block 2 docs diff check PASS; after branch correction rerun before commit. Read-only source inspection only; no production communication test.

## Runtime / Safety
- RFRIENDS_ENABLE_WRITES=0、RADIOFLIX_TIMEFREE_ENABLE_WRITES unset (OFF)。変更なし。
- ProductionBootstrap.ready=false、ProductionCaptureAdapter.ready=false、bridge_approved=false、ProductionHttpTransport.ready=false。
- 全fixture/backend testsはnetwork none、UIはlocalhost mock。実外部network・実radiko DNS/HTTP/HLS/auth/録音0。本番worker deploy/restartなし。
- rfriends3/native rsv/dat/sh/at/通常録音領域への変更なし。

## Important decisions
- Block 1実装checkpointとBlock 2 wire audit docs checkpointを分ける。
- Source/configだけで安全な契約を確定できないため、実radiko疎通許可前のProduction HTTP実装を進めない。
- 無関係な既存untracked files/historyを保持し、明示allowlistのみstageする。

## Recovery instructions
次回はまずgit status --short、git diff、HEADを確認。Block 2 correction docs-only checkpointをcommit/push後、Production HTTPはNotReadyのまま停止。premium/tf30・実効HTTP client policy・host/TLSの安全な契約が解決しない限りBlock 3へ進まない。

## at spool調査（2026-10-14、read-only）
- 10/12 before/after atjobs hash差は、17:25のrfriends3定時cronを挟んでおり、通常cronによるnative予約at job再生成が最有力。dat/sh aggregate hashと中身はbefore/after/currentで同一。
- RadioFlix隔離試験はproduction queue/mount非接続。at spool差分はRadioFlix操作由来ではないと判断。前後のjob ID別一覧がなく旧ID単位の削除/追加/変更は未確定。放送時刻自然消化よりcron再生成と整合。
- 過去の詳細atq情報は2026-10-14 read-only調査記録と既存history snapshotを参照。今回at/native queue操作なし。
