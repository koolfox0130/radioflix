# 番組表 Phase 1〜3 実装・検証記録

2026-09-25。ローカル・mock・一時DBのみ。本番反映、実Gateway呼び出し、実予約、実weekly、実タイムフリー録音、Docker操作、commit/pushは実施していない。

調査設計は `radioflix-program-guide-timefree-design.md` に元ファイルを完全コピーした。SHA-256: `5ab4377afc02919c86795cfd54f48913dda7600d18e35af648869d1e24cc4d74`。調査時点の記載は書き換えていない。

## API

| Method / path | 内容 |
|---|---|
| `GET /api/stations` | 設定地域の局ID・局名。局一覧専用キャッシュ |
| `GET /api/schedule?station=JORF&date=2026-09-25` | 局・放送日指定。station省略時は全局 |
| `GET /api/schedule?date=2026-09-25&date=2026-09-26` | 最大15日。日別availabilityと全体のok/partial/unavailable |
| `POST /api/broadcasts/{broadcast_id}/reservations` | `{date, schedule_revision, mode: "once" | "weekly"}`。公開XMLを再取得・照合して既存予約サービスに接続 |

全APIは `Cache-Control: no-store`。番組表の日別キャッシュは5分、局一覧は1時間、失敗日は15秒。取得は10秒timeout、0.2秒後に1回retry（404はnot_available）、最大4並列。gzip magicで判別しplain/gzip両対応、圧縮前後8MB制限、DTD/ENTITY拒否は既存decoderを共有する。

JST 05:00を放送日境界として、放送日の-7〜+7日を許容。範囲外・不明局は422。404/全失敗でも日別結果を返し、別日を失敗に巻き込まない。局の番組がなければstation_missing。前日データの流用・番組の補完生成はしない。

公開する情報は局ID・局名・番組名・開始終了・出演者・provider ID・説明等metadataとrevision。metadataのURLをサーバーから追加取得せず、UIは文字列として表示する。

## ID・カタログ・予約

- 放送回IDは既存互換の `SHA256(station + ":" + start_JST.isoformat() + ":" + end_JST.isoformat())`。録音フォルダ、タイトル、weekly subscription UUIDには依存しない。
- タイトル・出演者等の変更はschedule_revisionで検出。タイトル修正で放送回IDは変えない。終了変更によるID変更も同局時間重複で拒否する。
- dateは再取得する日付のlocator。ブラウザ指定の局・時刻・タイトルを予約入力として採用しない。
- 同放送回の再POSTは既存予約を返す。クライアント任意のidempotency_keyは追加せず、放送回と既存の永続予約台帳を冪等性のキーとして使う。
- program_seriesはUUID。局・正規化題名・曜日・時刻でカタログ候補を解決。録音フォルダがなくても作成・再起動後の参照・weekly翌週追従が可能。
- 一意に対応する録音済み番組はprogram_aliasesに保存し、既存program_idを維持。録音フォルダが消えてもaliasから解決する。
- broadcasts/broadcast_revisionsは受付時の再検証済み情報を保持。GETはDBを作成・更新しない。
- 既存ReservationServiceの開始3分前ガード、once/weekly、waiting_write、解除監査・再照合を再利用。program_idをまたぐ放送枠重複、weekly重複、モード競合を同じロック内で判定する。
- writes無効時はwaiting_write。Gateway.createを呼ばず、予約済みと表示しない。過去録音のPOST/API/workerは実装していない。

## native予約・認証

`RADIOFLIX_NATIVE_RESERVATIONS_DIR` はオプションの読み取り専用予約datディレクトリ。PHP、Gateway.inspect、ロックファイル生成、dat/sh/at変更は行わない。1回の一覧処理に対しスナップショットを1回取得する。永続台帳で確認済みの所有予約名を除き、同局時間重複はnative_conflict。POSTでは再取得し、上書き・解除・取り込みをしない。既存driverの作成直前競合チェックも維持する。

未設定・読取不能・形式不明はunknown。writes無効時の待機意図は保存可能だが、実書き込みが有効な場合はunknownのまま番組表由来の予約を開始できない。この環境の本番マウント設定は追加していない。現在の本番native予約を確認済みとは主張しない。

`RADIOFLIX_WRITE_TOKEN_FILE` を設定した場合、予約mutationには同ファイルのBearer認証を必須とする。実書き込み有効時は未設定でも拒否する。`RADIOFLIX_WRITE_ORIGIN` と異なるOriginも拒否する。既存予約・解除APIにも同じdependencyを適用し、GETは対象外。資格情報はブラウザへ渡さない。将来の公開時は、ユーザーを認証・認可したプロキシだけがこのヘッダーを注入し、クライアント指定ヘッダーを除去し、backendへの直接到達を制限する構成が必要。

今回の既存writes無効・認証未設定のローカル動作は維持する。待機情報を保存できるため、これを未認証の公開運用として使う想定ではない。本番プロキシの実効保護は今回変更・検証していない。

## UI

共通ナビ「録音一覧／番組表／予約一覧」、`/schedule`。全局・個別局選択、15日の横スクロールと今日表示、JST・05:00切替注記、翌未明の「翌」表示。時間順カードに番組・局・出演者・予約状態、タップで操作を表示する。

未来は今回だけ／毎週。過去は「タイムフリー録音は準備中」。録音済みの判定はPhase 5のasset照合が必要なため「録音状態：未確認」とする。waiting_write・native未確認・予約失敗も表示する。選択変更時は旧データを消し、遅い応答を採用しない。連打防止、オフラインmutation拒否、再読み込みを実装。Service Workerは既存の非キャッシュ方式を維持した。

## 検証結果

- backend: 119件、109成功・10skip。43件追加。skipは既存PHP CLI依存テスト（ホストにPHP CLIなし）。既存予約・weekly・解除監査テストは回帰なし。
- 番組表UI: 52チェック成功（360/390/412/1280px × 13）。局・日付・今日・一覧・横幅・未来once/weekly・連打・競合・過去・失敗・復帰。
- 既存予約UI: 24シナリオ成功（360/1280px）。weekly/once/登録失敗/再取得失敗/古いpoll/解除4xx・5xx・通信・parse・ID不一致・連打。
- `py_compile`: backend 31ファイル成功。
- `npx tsc --noEmit`: 成功。
- `npm run lint`: エラー0、既存警告5。新規ファイルの警告0。
- `npm run build`: 成功、`/schedule`を生成。
- `git diff --check`: 成功。
- `.env`の`RFRIENDS_ENABLE_WRITES=0`を確認。全検証プロセスは0。fake Gatewayの状態遷移テストのみPythonオブジェクトのwrites_enabledを切り替え、環境変数や実Gatewayには反映しない。

sandbox内ではTestClientのスレッド通信停止、Next/Turbopackの内部ポート拒否が発生した。sandbox外で全通信mock・一時DB・一時Nextアプリに限定して再実行し成功。依存パッケージの追加・更新なし。PlaywrightとChromiumは既存の `/tmp/radioflix-weekly-ui` を使用。

再現コマンド（backend/UIは上記sandbox制限に注意）:

```sh
RFRIENDS_ENABLE_WRITES=0 PYTHONPATH=backend /tmp/radioflix-test-venv/bin/python -m unittest discover -s backend/tests -q
cd frontend
PLAYWRIGHT_BROWSERS_PATH=/tmp/radioflix-weekly-ui/browsers NODE_PATH=/tmp/radioflix-weekly-ui/node_modules RFRIENDS_ENABLE_WRITES=0 node tests/schedule-ui.mjs
PLAYWRIGHT_BROWSERS_PATH=/tmp/radioflix-weekly-ui/browsers NODE_PATH=/tmp/radioflix-weekly-ui/node_modules RFRIENDS_ENABLE_WRITES=0 node tests/reservations-ui.mjs
npx tsc --noEmit
npm run lint
npm run build
```

## 判定・残作業

- Phase 1〜3のローカル/mock実装: YES。
- 直ちに本番反映試験へ進める: NO。native読取専用sourceの配置・認証プロキシ設定と接続確認、およびPHP CLI依存10件の検証環境が未整備。本番Dockerは触っていない。
- Phase 4の隔離/mock実装へ進める: YES。実録音の有効化を意味しない。worker隔離・配信可否・期限・job台帳・原子的公開・異常復旧は元設計に従い別途実装する。

既存の `.codex/`、`frontend/Dockerfile.dev-backup`、`frontend/Dockerfile.production` は未変更・未追跡のまま。今回のファイルもstage/commitしていない。

## 最終git status

追跡ファイル6変更、新規10ファイル、すべて未stage。既存未追跡3項目は保持。

```text
 M backend/app.py
 M backend/radioflix/adapters/rfriends.py
 M backend/radioflix/api/reservations.py
 M backend/radioflix/services/reservation_service.py
 M frontend/app/layout.tsx
 M frontend/next.config.ts
?? .codex/
?? backend/radioflix/adapters/schedule.py
?? backend/radioflix/api/recording_auth.py
?? backend/radioflix/api/schedule.py
?? backend/radioflix/services/schedule_service.py
?? backend/tests/test_schedule.py
?? docs/
?? frontend/Dockerfile.dev-backup
?? frontend/Dockerfile.production
?? frontend/app/components/Navigation.tsx
?? frontend/app/schedule/
?? frontend/tests/schedule-ui.mjs
```
