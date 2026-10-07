# RadioFlix Development Status

## Last updated
2026-09-29 05:16:45 JST

## Current task
Android実機UI確認向けに、RadioFlix backend/frontendだけを既存の実稼働Compose構成から限定build/deployし、安全状態とGET応答を確認する。

## Current phase
Phase 2 UI仕上げ・統合確認を含むPhase 1〜3のAndroid実機確認準備。限定deployとHTTP確認が完了し、実機操作待ち。

## Status
waiting_for_user

## Completed
- セッション開始時にAGENTS.md、frontend/AGENTS.md、latest.md、branch/HEAD/status/差分を確認。既存の未commit差分を保持。
- deploy前に実稼働Compose構成 `docker-compose.yml` + `docker-compose.rfriends.yml`、project `radioflix`、backend/frontend/gateway serviceを確認。
- deploy前記録:
  - backend container `2df516ff483f4f69987c6224de45b931de40e98df32f15749b3092eea32b090c` / image `sha256:95ed479bb019bd7501c51a7f2835a35edd306e47b827fbae0e06eab08a22af7f` / RestartCount 0。
  - frontend container `c82a70cd963818d9160d585f7d537274e5b95ea09d8cc8d25a34568faac33fba` / image `sha256:ef7de2ed5027537e20fc505a0b72210c02c80193de0995228c85e9bca61526d1` / RestartCount 0。
  - gateway container `8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6` / image `sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68` / RestartCount 0。
  - rfriends3 container `e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968` / image `sha256:da10070ca91ba4838e96a2205aa2993456dbcc2149c61bad26efd3058cc32c80` / RestartCount 0。
- backend inspectで予約DBはnamed volume `radioflix_radioflix-reservations`、container `/data/radioflix.sqlite3` と特定。volumeをread-only mountし、SQLite online backupを作成: `/home/kool-fox/Share/Radio/backups/radioflix-reservations-pre-android-20260929_051210.sqlite3`。integrity_check `ok`、36,864 bytes。`.env`その他secretは含めていない。
- deploy前およびdeploy直前に `.env` / effective Compose backend / effective Compose gateway / backend Config.Env / backend PID1 / gateway Config.Env / gateway PID1が全て `RFRIENDS_ENABLE_WRITES=0` と確認。
- deploy前後ともactive RadioFlix reservations=0、active weekly subscriptions=0。
- 指定された `docker compose -p radioflix -f docker-compose.yml -f docker-compose.rfriends.yml build backend frontend` を実行し両方成功。BuildKitの初期表示にgateway target名が出たが、実行されたDockerfile/build/export stepはbackend/frontendのみで、gateway image IDは不変。
- 指定された `docker compose -p radioflix -f docker-compose.yml -f docker-compose.rfriends.yml up -d --no-deps backend frontend` を実行。backend/frontendだけを再作成・起動し、両方running。
- deploy後のbackend container `48a8c7223440610221f053c5bd1ade57b8b28d15a068c632c2da5f2908ae0b62` / image `sha256:ecd52b9d8aef7cbd467655d7528c93cd78ed6ffe128daae42b61312ab542bfdd`。
- deploy後のfrontend container `54263667422a783911c2004476c0d4aa5f86b4617683c3be37a27bc13fa74624` / image `sha256:dc382be476ba0449e5011225650ecb94a5ae76de4122f2a8ac77e1107a1a55b1`。
- deploy後gateway container IDは `8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6` のまま、running、RestartCount=0。rfriends3 IDは `e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968` のまま、running、RestartCount=0。
- deploy後も `.env`/backend Config.Env/backend PID1/gateway Config.Env/gateway PID1の安全値は全て0。active reservation/weeklyは各0。
- localhost GET確認: frontend `/`, `/schedule`, `/reservations`、backend `/`, `/programs` は全てHTTP 200。frontend各画面HTMLに「録音一覧」「番組表」「予約一覧」の共通ナビ文字列を確認。
- 番組表API GET `/api/stations` は200、16局。TBS・2026-09-29の `/api/schedule` GETは200、availability `ok`、番組23件、`writes_enabled=false`。POST/DELETEは呼んでいない。
- deploy前backend/frontendのimage IDはローカルに残存することを `docker image inspect` で確認。rollback参照情報を以下とRecovery instructionsに記録。

## In progress
Androidスマートフォン上でPWAを開き、番組表・録音一覧・予約一覧、共通ナビ、戻る/状態復元、再生継続を実機確認する段階。実機操作はこのセッションでは未実施。

## Next actions
1. Android端末から `http://<RadioFlixホストのLANアドレス>:3001/` を開き、PWA UIを確認する。
2. 録音一覧・番組表・予約一覧を移動し、再生中の番組、位置、速度、Media Session操作の継続、および戻る時の局/日付/スクロール復元を確認する。
3. 実機確認が終わるまで、実予約・毎週登録・タイムフリー録音を行わない。結果をこのログへ記録する。
4. 実機確認後に次の指示を待つ。commit/pushは行わない。

## Blockers / Issues
- Android実機そのものを使った表示・タッチ・音声継続確認は未実施。
- このdeploy作業ではfrontend UI自動テスト、lint、独立したhost上typecheckを再実行していない。frontend Docker build内ではNext.js production buildとTypeScript工程が成功。

## Files changed
この作業でのリポジトリ内変更:
- `docs/dev-log/latest.md`: 実際の限定deploy・安全確認・HTTP結果・次の実機確認を記録。
- `docs/dev-log/history/2026-09-29_0516_android-limited-deploy.md`: 終了時のlatestと同内容のsnapshot。

リポジトリ外の安全バックアップ:
- `/home/kool-fox/Share/Radio/backups/radioflix-reservations-pre-android-20260929_051210.sqlite3`

機能コードやCompose、`.env`は今回変更していない。稼働backend/frontend containerのみ指定範囲で更新。gateway/rfriends3は変更なし。

## Git state
- branch `main`、HEAD `20b379703bc36818e5d37616cec927b19ba973c9`。
- commit/push/fetchなし。stage/reset/restoreなし。
- 作業開始時の未commit差分を保持。開始時status: `M AGENTS.md`, `M backend/app.py`, `M backend/radioflix/adapters/rfriends.py`, `M backend/radioflix/api/reservations.py`, `M backend/radioflix/services/reservation_service.py`, `M frontend/app/layout.tsx`, `M frontend/next.config.ts`; untracked: `.codex/config.toml`, `backend/radioflix/adapters/schedule.py`, `backend/radioflix/api/recording_auth.py`, `backend/radioflix/api/schedule.py`, `backend/radioflix/services/schedule_service.py`, `backend/tests/test_schedule.py`, `docs/dev-log/history/2026-09-26_1704_devlog-setup.md`, `docs/dev-log/history/2026-09-28_0819_phase2-ui.md`, `docs/dev-log/history/2026-09-28_0901_phase2-ui.md`, `docs/dev-log/history/2026-09-28_1949_deploy-safety.md`, `docs/dev-log/history/2026-09-28_2132_compose-audit.md`, `docs/dev-log/latest.md`, `docs/radioflix-program-guide-phase123-implementation.md`, `docs/radioflix-program-guide-timefree-design.md`, `frontend/Dockerfile.dev-backup`, `frontend/Dockerfile.production`, `frontend/app/@modal/(.)reservations/page.tsx`, `frontend/app/@modal/(.)schedule/page.tsx`, `frontend/app/@modal/default.tsx`, `frontend/app/@modal/page.tsx`, `frontend/app/components/InterceptedRoute.tsx`, `frontend/app/components/Navigation.tsx`, `frontend/app/components/PrimaryRouteContext.tsx`, `frontend/app/schedule/page.tsx`, `frontend/tests/playback-navigation-ui.mjs`, `frontend/tests/schedule-ui.mjs`.
- 作業開始時tracked diff stat: 7 files, 108 insertions, 28 deletions（untrackedは含まず）。作業後もsource差分は変わっていない。`git diff --check` PASS。
- 最新のGit statusでは既存差分に加えて本ログとhistoryが未追跡のまま存在。これ以外のコード/Compose差分は作成していない。

## Tests
今回実行:
- backend/frontend Compose build: PASS。Next.js compile、TypeScript工程、static page generation、image export成功。
- localhost HTTP GET: frontend `/`, `/schedule`, `/reservations`; backend `/`, `/programs` 全て200。
- 番組表API GET: `/api/stations` 200/16局、TBS 2026-09-29 schedule 200/23番組/availability ok/writes false。
- 共通ナビ: 3 frontendページのHTMLで3つのナビラベル確認。
- active reservation/weekly read-only query: 0/0。
- gateway/rfriends3 running・container ID unchanged・RestartCount不増を確認。
- `git diff --check`: PASS。
- frontend UI自動テスト、lint、独立host上 `npx tsc --noEmit` は今回未実施。過去のログにある前回テスト結果は今回の結果ではない。
- HTTP確認はGETのみ。予約API POST/DELETE、実予約、実録音は行っていない。

## Runtime / Safety
- project `radioflix`、Compose files `docker-compose.yml` + `docker-compose.rfriends.yml`。
- backend/frontend running、限定deploy済み。gateway runningかつID/RestartCount不変。別projectのrfriends3もrunningかつID/RestartCount不変。
- `.env`、effective Compose backend/gateway、backend Config.Env/PID1、gateway Config.Env/PID1は全て `RFRIENDS_ENABLE_WRITES=0`。
- active RadioFlix reservation=0、active weekly subscription=0。deploy後も同じ。
- DB backupはread-only sourceから取得しintegrity check済み。rfriends3予約状態、dat/sh/at、rfriends3 container/filesystemは変更していない。
- 本番Docker操作は承認されたRadioFlix backend/frontendのみのbuildと `up -d --no-deps`。gateway/rfriends3へのbuild/restart/recreateなし。
- 実予約・週次登録・タイムフリー実録音・writes=1・commit/pushなし。
- Android実機確認へ進める状態: YES（LAN上でUIが200応答し、共通ナビと番組表APIを確認済み。実機操作と音声継続は未確認）。

## Important decisions
- deploy対象をbackend/frontendに限定し、`--no-deps`を使用。rfriends-gatewayはbackendのdepends_onにあたるが、明示的なno-depsにより暗黙更新を防いだ。rfriends3は別Compose project。
- RFRIENDS_ENABLE_WRITESはdeploy前後とも0であり、UI・番組表確認のみ実施。
- 予約DBは稼働backendを停止せず、volumeをread-only mountした一時helperからSQLite backup APIでコピー。バックアップ自体のintegrity_checkはok。

## Recovery instructions
1. `AGENTS.md`、このログ、`git status`/branch/HEADを照合し、未commit source差分を保持する。
2. Android用runtimeはproject `radioflix`。backend/frontend現在container IDs: `48a8c7223440610221f053c5bd1ade57b8b28d15a068c632c2da5f2908ae0b62`, `54263667422a783911c2004476c0d4aa5f86b4617683c3be37a27bc13fa74624`。
3. deploy前rollback reference: backend old container `2df516ff483f4f69987c6224de45b931de40e98df32f15749b3092eea32b090c`, image `sha256:95ed479bb019bd7501c51a7f2835a35edd306e47b827fbae0e06eab08a22af7f`; frontend old container `c82a70cd963818d9160d585f7d537274e5b95ea09d8cc8d25a34568faac33fba`, image `sha256:ef7de2ed5027537e20fc505a0b72210c02c80193de0995228c85e9bca61526d1`。old images are still locally inspectable; old containers were replaced by the authorized deploy.
4. Predeploy DB snapshot: `/home/kool-fox/Share/Radio/backups/radioflix-reservations-pre-android-20260929_051210.sqlite3` (integrity_check ok)。`.env`やsecretは含まない。
5. gateway container ID `8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6`、rfriends3 ID `e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968`。runtime変更を行う前に最新状態とwrites=0を再確認する。
6. 次はAndroid端末でHTTP `:3001`のUI・ナビ・再生継続・番組表状態復元を確認する。reservation API POST/DELETE、実予約/録音、writes=1、commit/pushは引き続き禁止。
