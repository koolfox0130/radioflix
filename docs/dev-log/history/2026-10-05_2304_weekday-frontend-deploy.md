# RadioFlix Development Status

## Last updated
2026-10-05 23:04:06 JST

## Current task
曜日表示修正をAndroidで確認するため、RadioFlix frontendだけを指定Compose構成で限定build/deployする。

## Current phase
frontend限定deploy・HTTP・安全値・非対象コンテナ不変の確認完了。Android実機確認待ち。

## Status
waiting_for_user

## Completed
- AGENTS.md、frontend/AGENTS.md、latest、Git状態と既存差分を確認。main/HEAD・tracked差分量は前回記録と整合。
- deploy前: .env、effective Compose backend/gateway、稼働backend/gateway Config.Env/PID1のRFRIENDS_ENABLE_WRITESは全て0。
- backend/frontend/gateway/rfriends3のID・image・起動時刻・RestartCountを記録。
- 修正前のAndroid番組表・画面遷移・再生継続はユーザーより正常確認済み。新曜日表示の実機確認は未実施。

## In progress
frontend限定deploy・HTTP・安全値・非対象コンテナ不変の確認完了。Android実機確認待ち。

## Next actions
1. Androidで番組表を再読み込みし、曜日・今日表示と横スクロールを確認する。
2. 実予約/実録音・writes変更・commit/pushは行わない。
3. 結果を記録して停止し、次の指示を待つ。

## Blockers / Issues
なし。Android実機操作はユーザー確認待ち。

## Files changed
今回のリポジトリ変更はdocs/dev-log/latest.mdと終了historyのみ。機能コード・Compose・.env変更なし。既存の未commit差分は保持。

## Git state
branch main、HEAD 20b379703bc36818e5d37616cec927b19ba973c9。
既存tracked変更7ファイル、108追加/28削除。番組表API/UI・ナビ・tests・docs・.codex・Dockerfile類は未追跡を含む。stage/commit/push/reset/restoreなし。

## Tests
今回: preflight安全値PASS。git diff --check PASS。
frontend Compose build: PASS（Next.js production build/TypeScript/static generation成功）。
frontend限定up: PASS。
反映後検証: frontend running、GET / と /schedule がHTTP 200。backend/gateway/rfriends3のID・image・StartedAt・RestartCount不変。安全値7箇所すべて0。
今回UI/lint/独立host typecheckは再実行しない（機能コード変更なし）。前タスク: schedule 104、playback/navigation 21、reservations 24成功。typecheck/build成功、lint既存warning5/error0。

## Runtime / Safety
Compose project radioflix、docker-compose.yml + docker-compose.rfriends.yml。
ユーザー指定コマンド: `docker compose -p radioflix -f docker-compose.yml -f docker-compose.rfriends.yml build frontend`、成功後 `up -d --no-deps frontend`。
frontendのみ更新。backend/gateway/rfriends3のrestart/recreate禁止。実予約・実録音なし。書き込み設定変更なし。
active reservation/weeklyは今回未確認。2026-10-04の読取結果は0/0（過去記録）。
前回バックアップ・rollback詳細: history/2026-09-29_0516_android-limited-deploy.md。

### Deploy前の識別情報
- radioflix-frontend: ID `54263667422a783911c2004476c0d4aa5f86b4617683c3be37a27bc13fa74624`、image `sha256:dc382be476ba0449e5011225650ecb94a5ae76de4122f2a8ac77e1107a1a55b1`、StartedAt 2026-10-03T15:17:49.325363564Z、RestartCount 0。
- radioflix-backend: ID `48a8c7223440610221f053c5bd1ade57b8b28d15a068c632c2da5f2908ae0b62`、image `sha256:ecd52b9d8aef7cbd467655d7528c93cd78ed6ffe128daae42b61312ab542bfdd`、StartedAt 2026-10-03T15:17:49.372430449Z、RestartCount 0。
- radioflix-rfriends-gateway-1: ID `8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6`、image `sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68`、StartedAt 2026-10-03T15:17:49.37234528Z、RestartCount 0。
- rfriends3: ID `e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968`、image `sha256:da10070ca91ba4838e96a2205aa2993456dbcc2149c61bad26efd3058cc32c80`、StartedAt 2026-10-03T15:17:49.325801073Z、RestartCount 0。

### Deploy後
- radioflix-frontend: ID `5480a0de5bfb8b5f73688aac722d52b22983db4d68b6d291dfc7d0d82ce8ea5f`、image `sha256:d864eaa2df57da00e6bba8eaecf249688576e294943221c53e2f349f83f56a6d`、running、StartedAt 2026-10-05T14:03:42.394490342Z、RestartCount 0。
- radioflix-backend: ID `48a8c7223440610221f053c5bd1ade57b8b28d15a068c632c2da5f2908ae0b62`、image `sha256:ecd52b9d8aef7cbd467655d7528c93cd78ed6ffe128daae42b61312ab542bfdd`、running、StartedAt 2026-10-03T15:17:49.372430449Z、RestartCount 0。
- radioflix-rfriends-gateway-1: ID `8213af2c0f97ee0e58b81cc7e58644b0f3dfe3e81c6ba2ce3494c7d9fc054ad6`、image `sha256:5dbf129c839cac8f7d532b0502530ba62d3b27b59c4bc4a78685e6b42f551e68`、running、StartedAt 2026-10-03T15:17:49.37234528Z、RestartCount 0。
- rfriends3: ID `e346364f5944ab252d0d12e056469ed16af64a9303f5a47b4aa36d7d2439b968`、image `sha256:da10070ca91ba4838e96a2205aa2993456dbcc2149c61bad26efd3058cc32c80`、running、StartedAt 2026-10-03T15:17:49.325801073Z、RestartCount 0。

## Important decisions
指定されたfrontendのみbuildし、upは--no-depsで依存サービスを更新しない。HTTPはGETのみ。

## Recovery instructions
1. AGENTS.md・latest・Git状態を照合し、既存差分を保持。
2. 新曜日表示のAndroid確認結果を受け取る。再deployや本番書き込みは新しい指示なく実行しない。
3. rollbackが必要なら上記deploy前frontend imageを参照し、最新runtime確認後に別途指示に従う。
