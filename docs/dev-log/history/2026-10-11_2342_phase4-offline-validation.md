# RadioFlix Development Status

## Last updated
2026-10-11 23:42:40 JST

## Current task
Phase 4「隔離worker + API + UI + mock/隔離テスト」の中断復旧・通常検証。今回の隔離検証を完了し、ユーザー指定に従って停止する。本番反映・実タイムフリー録音は対象外。

## Current phase
オフラインfixture範囲の実装・回帰検証完了。本番transportを含むPhase 4全体の完成/リリースではない。

## Status
completed

## Completed
- Phase 1〜3は正式リリース済み。main/HEADと全追跡差分・Phase 4未追跡ファイルを再照合し、既存変更を保持した。
- 中断前のworker WAV実データ量検証・作業領域作成失敗対策・追加5テストは保存済み。途中編集はなかった。
- ログのbuild実行中・依存取得中という記録を訂正。中断直前のbuildは成功していた。結果不明だった試験は再実行した。
- 永続job/API/fixture worker/PHP隔離bootstrap/番組表状態表示とmock試験を確認。
- worker修正: WAVヘッダーと実データ量の照合、作業領域作成失敗をfailedへ保存、hash計算のストリーム化。
- 新たに保存途中失敗、公開後DB失敗、worker排他、fixture/live分離、revision/時間重複、GET副作用ゼロの6件を追加。
- UIはオフライン拒否、受付エラー、連打抑止、polling、各状態とgate OFF、48pxタップ領域を検証。
- 検証手順・未完成条件をdocs/radioflix-timefree-phase4-validation.mdに記載。

## In progress
実行中の試験なし。今回の検証範囲は完了。本番向け開発・反映は未実施。

## Next actions
1. 次の指示時にAGENTS.md、本ログ、Git/実ファイルを再確認する。既存差分を取り消さない。
2. 本番transport/bootstrap・実形式検証、native実行/保存済み照合と開始前/公開前再照合、NAS原子的公開/復旧、資源制限と配置手順を実装・隔離検証する。
3. 本番隔離workerのgate OFF反映試験は上記準備と明示的な本番操作許可の後。現在は進行不可。
4. 実タイムフリー1本試験は本番受入と別途明示承認の後。現在は進行不可。

## Blockers / Issues
- production transport/worker運用・NAS publisher・本番認証プロキシ/Origin経路は未受入。APIはfixture以外の新規jobを拒否する。
- native保存済み録音/実行中照合・開始前/公開前再照合は未実装。受付時の予約照合のみ。
- 一覧/再生APIへのasset統合はPhase 5。completed_assetsは将来の読み取り境界で、fixtureは既定除外。
- 番組表UI初回は予約一覧から戻った際の局ボタン待ちでtimeout。単独360px再実行と拡張後4幅全試験では再現しなかった。原因未確定、既知の偶発失敗として残す。
- lintの既存警告5件、試験依存のStarlette/httpx非推奨警告あり。依存ファイルの変更なし。

## Files changed
中断前から保持した機能差分:
- backend/app.py: timefree service/router接続。
- backend/radioflix/services/schedule_service.py: job状態の番組表投影。
- backend/radioflix/api/timefree.py: job受付/状態/待機取消API。
- backend/radioflix/timefree/: store/service/worker.py/worker.php/fixture-bindings.php/source-manifest.json/__main__.py/__init__.py。
- backend/tests/test_timefree.py: API/worker/PHP fixture試験。
- frontend/app/schedule/page.tsx: timefree状態/受付/polling。
- frontend/next.config.ts: timefree proxy。
- frontend/tests/schedule-ui.mjs: timefree UI回帰。
- docker-compose.timefree-test.yml: 独立したoffline fixture設定。
今回の継続編集:
- worker.py: 上記WAV/作業領域/hash修正（中断直前に保存済み）。
- test_timefree.py: 上記計11件の追加回帰。gate ON分岐は関数mockへ変更し環境値を有効化しない。
- schedule-ui.mjs: offline/エラー/polling/gate OFF/unknown/取消状態/タップ領域、失敗時fixture画面保存。
- docs/radioflix-timefree-phase4-validation.md: 隔離条件・再実行・未完成条件。
- docs/dev-log/latest.md と今回history: 復旧・検証結果。
既存history/2026-10-08_0744_phase123-release.md、.codex/、Dockerfile.dev-backup、Dockerfile.productionは保持・未編集。

## Git state
branch: main
HEAD: d46babe85db84b4ee08ff1ccf3d14fe97ed4fa0f
commit/push/stage/reset/restoreなし。既存追跡6ファイル変更とPhase 4未追跡コード/Composeを保持。今回追加docs/historyあり。依存package.json/lockfile変更なし。

## Tests
今回の実行結果（前回記録とは区別）:
- backend unittest: **160件すべて成功、skip0**（16.885秒）。PHP既存driver10件とtimefree1件（6シナリオ）を含む。APIはTestClient、一時DB、mock schedule/gateway。
- 初回backend154件は143成功・PHP11skip。PHP隔離準備後154件全成功、追加6件後に最終160件全成功。
- PHP: source-manifestの2ファイルSHA一致、worker.php/fixture-bindings.php構文成功。network none/read-only/user1000/本番mountなしをinspectで確認。
- frontend番組表: **148チェック成功**（360/390/412/1280px、各37）。拡張前単独360px31チェックも成功。360/1280px画像を目視確認。
- frontend予約: **24シナリオ成功**（360/1280px）。
- frontend再生/遷移: **21チェック成功**（360px、mock音声）。
- TypeScript: `npx --prefix frontend tsc --noEmit -p frontend/tsconfig.json` 成功。
- lint: `npm run lint` 成功、エラー0・既存警告5。
- build: `npm run build` 成功（中断直前、現行製品コードと同一）。初回sandboxでTurbopackのポートbind禁止により失敗し、制限外再実行で成功。
- Python構文: backend38ファイルをast.parse、成功。
- 隔離Compose: `docker compose -f docker-compose.timefree-test.yml config --quiet` 成功。`build` は成功終了だが既存imageのみでbuild対象なし。製品Composeのbuild/deployはしていない。
- `git diff --check`: 成功。
- 変更/新規対象全文のsecret pattern scan: 19ファイルで検出0（最終history生成後も再検査）。private key、代表的token、JWT、Bearer長値、秘密値代入を走査。一致内容は出力しない。.codex/・既存除外Dockerfile・.env/credentialは読み取らない。
- 未実施: Android実機、実radiko認証/HLS/ffmpeg録音、本番NAS公開/復旧、本番API経由E2E。禁止された本番操作と未実装transportを要するため。
- 環境復旧: /tmpに依存を再用意。venvはensurepip不足、最初のpipはsandbox DNS失敗。`pip --target /tmp/radioflix-test-deps` とPlaywright/Chromiumの/tmp取得で解決。製品依存追加なし。

## Runtime / Safety
- 実タイムフリー録音を今回作業で一度も開始していない: **YES**。音声はfixture合成WAVのみ、PHPコンテナはnetwork none。
- 本番隔離worker反映試験へ進める状態: **NO**。実transport・配置/安全受入条件が未完成。
- 実タイムフリー1本試験へ進める状態: **NO**。前項と実録音の個別承認が必要。
- 本番4コンテナ（backend/frontend/gateway/rfriends3）はrunning。試験中に取得した前後のID/StartedAt/RestartCountは不変、RestartCountは0。
- backend/gatewayのコンテナ環境RFRIENDS_ENABLE_WRITES=0確認。4コンテナのtimefree専用gateは未設定（コード既定OFF）。他の設定箇所の値は今回未確認。前回「全7箇所0」は過去記録であり今回結果に流用しない。
- active weekly/reservation数、native dat/sh/atの内容/ハッシュ、録音volume内容は今回未確認・操作なし。過去/tmp native snapshotは残っておらず、今回の証拠として使わない。
- 本番反映、gate変更、実予約/録音、rfriends3変更、native dat/sh/at変更、本番volume write、restart/recreateなし。
- 専用fixtureコンテナradioflix-phase4-offline-testのみ作成・停止・削除。テスト用サーバー/ブラウザはテスト終了時に終了。
- /tmpのテスト用依存・fixture音声/ソース・検証ログ・画面画像は再検証資料で、本番成果物ではない。

## Important decisions
- Git/実ファイルを正とする。ログの古い計画に合わせてコードを戻さない。
- fixture/liveは明確に分離し、API/envでfixture実行を選ばせない。実gateをONにしても本番transport未実装のAPIは拒否する（関数mockで検証）。
- unknownは自動再試行しない。既存ファイルの上書き・削除・nativeへの取り込みをしない。
- 本番反映・実録音・commit/pushは禁止されたまま。今回の成功は本番操作の許可ではない。

## Recovery instructions
本ログとdocs/radioflix-timefree-phase4-validation.md、Git差分を照合してから次の指示に従う。今回のoffline検証は終了済み。Phase 4全体完成と誤認しない。/tmp環境は消失し得るため再利用時に存在・source SHA・隔離条件を確認する。秘密設定や本番録音領域をテスト環境へマウントしない。
