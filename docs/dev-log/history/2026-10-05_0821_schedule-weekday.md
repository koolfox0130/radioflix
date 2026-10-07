# RadioFlix Development Status

## Last updated
2026-10-05 08:21:43 JST

## Current task
番組表の日付ボタンへ日本語1文字の曜日を追加する。表示ラベルだけを変更する。

## Current phase
Phase 2 小規模UI改善・回帰確認

## Status
completed

## Completed
- 日付ラベル1行のみ変更。10/03(土)、10/04(日)、10/05(月) 今日、10/06(火)、10/07(水)。
- 全15日ラベル、48px以上のタップ領域、文字が1行で収まること、360pxを含む横幅、日付選択/API日付値・局/日付/縦横スクロール復元、再生継続のUI回帰を確認。
- AGENTS.md、frontend/AGENTS.md、前回latest、Git状態・既存差分を確認。
- ユーザーよりAndroid実機で番組表・画面遷移・再生継続すべて正常との完了報告（2026-10-05）。修正前の確認結果。

## In progress
なし。UI修正と指定検証を完了。deployせず停止。

## Next actions
1. 次のユーザー指示を待つ。曜日表示はローカルのみ、本番未反映。
2. 別途本番反映を指示された後、Androidで曜日ラベルと横スクロールを短く再確認する。
3. 実予約/実録音・writes設定変更・commit/pushは禁止のまま。

## Blockers / Issues
過去の/tmp Playwright環境が消失。sandbox内npm installはDNS EAI_AGAINで失敗。制約外で/tmpにPlaywright/Chromiumを導入済み。プロジェクト依存は変更なし。

## Files changed
今回変更: frontend/app/schedule/page.tsx、frontend/tests/schedule-ui.mjs、frontend/tests/playback-navigation-ui.mjs、本ログと終了history。
既存のbackend、frontend layout/config、AGENTS.md等の変更は保持。

## Git state
branch main、HEAD 20b379703bc36818e5d37616cec927b19ba973c9。
開始時tracked変更7ファイル、108追加/28削除。番組表API/UI・ナビ・tests・docs・.codex・Dockerfile類の未追跡項目あり。
stage/commit/push/reset/restoreなし。開始時ファイルのSHA-256比較で今回差分は対象UI/テスト3ファイルとログのみ。tracked差分量は7ファイル108追加/28削除のまま（今回の対象コードは元から未追跡）。

## Tests
実行コマンド（frontend）: `PLAYWRIGHT_BROWSERS_PATH=/tmp/radioflix-weekly-ui/browsers NODE_PATH=/tmp/radioflix-weekly-ui/node_modules node tests/{schedule-ui,playback-navigation-ui,reservations-ui}.mjs`（各々実行）、`npx tsc --noEmit`、`npm run lint`、`npm run build`。UI/buildは一時サーバー起動制約を避けsandbox外で実行。
今回の物理Android再確認は未実施（実機操作環境なし）。本番反映後に新ラベルの短い目視確認を推奨。backendは未変更のためテスト未実施。
今回: npx tsc --noEmit PASS。frontend npm run lint PASS（既存warning 5、error 0）。npm run build PASS。UI3本PASS: schedule 104チェック（360/390/412/1280px各26）、playback/navigation 21チェック（360px）、reservations 24シナリオ（360/1280px）。git diff --check PASS。初回ルートでのlintはpackage.json不在で失敗し、frontendで再実行して成功。
過去記録: UI 96件、再生ナビ21件、typecheck/lint/build成功。今回の成功として扱わない。

## Runtime / Safety
今回本番稼働状態は未確認。Docker/deploy・rfriends3変更・実予約/実録音なし。RFRIENDS_ENABLE_WRITES設定変更なし。
前回2026-10-04読取確認: writes=0、active reservation=0、weekly=0、9/29限定deployと同じコンテナ稼働。現在値として再確認はしていない。
前回deploy詳細・rollback情報・DBバックアップ参照はhistory/2026-09-29_0516_android-limited-deploy.mdに保存済み。

## Important decisions
日付内部値/API/05:00境界/状態復元/再生処理は変更しない。曜日のみUTC日付から計算。
UI試験は一時Nextアプリ・mock APIで実施し、本番へ接続しない。

## Recovery instructions
1. AGENTS.mdとlatest、Git状態を照合し既存差分を保持。
2. 今回対象の曜日表示・試験結果から再開し、完了済みなら次の指示を待つ。
3. 本ログはdeploy・本番書き込み・commit/pushの許可ではない。
