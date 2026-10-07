# RadioFlix 開発ガイド

## 適用範囲

- このファイルはプロジェクト全体に適用する。
- サブディレクトリに追加の `AGENTS.md` がある場合は、そのディレクトリでは両方に従い、内容が競合する場合はより対象に近いファイルを優先する。
- `frontend/AGENTS.md` にある Next.js 固有のルールも、フロントエンド作業時に必ず確認する。

## プロジェクト構成（現状）

- `frontend/`: Next.js 16.2.6 の App Router 構成。React 19.2.4、TypeScript 5、Tailwind CSS 4、ESLint 9 を使用する。
  - TypeScript は `strict: true`、`noEmit: true`。
  - PWA 用の manifest、Service Worker、アイコンが配置されている。
  - 開発・ビルド・静的解析は `frontend/package.json` の npm scripts を使用する。
- `backend/`: FastAPI アプリケーション。Python 3.14 の Docker イメージ上で Uvicorn を使用して起動する。
  - 録音ファイルの一覧・音声・サムネイルをファイルシステムから提供する。
  - `RADIKO_DIR` 環境変数で録音ディレクトリを指定する。
- `docker-compose.yml`: フロントエンドとバックエンドの2サービスを定義する。
  - フロントエンドはコンテナの 3000 番ポート、バックエンドは 8000 番ポートを使用する。
  - 録音ディレクトリはバックエンドへ読み取り専用でマウントする。
- データベースは `README.md` に SQLite と記載されている。ただし、現状の `backend/app.py` は録音ファイルを直接参照しており、SQLite の利用コードは確認できない。
- 現時点ではテスト用 npm script、テストディレクトリ、Python の依存関係・テスト設定ファイルは確認できない。

## コミュニケーション

- 説明、作業計画、進捗、確認結果、最終報告は日本語で行う。
- 作業を始める前に `git status` を確認し、既存の変更や未追跡ファイルを把握する。
- 変更前に、対象ファイルと作業計画を示す。
- ユーザーの既存変更は保持し、由来が不明な差分を上書き・取り消ししない。

## 変更方針

- 既存機能をユーザーの明示的な指示なく削除・無効化しない。
- 変更は目的達成に必要な最小限の範囲に限定する。
- 依頼と無関係なリファクタリング、整形、命名変更、依存関係更新を行わない。
- 既存の設計、ディレクトリ構成、コードスタイルを尊重する。
- パッケージを追加・更新する必要がある場合は、実行前に理由、用途、影響範囲を日本語で説明する。
- `git commit`、`git push`、`git reset` は、ユーザーから明示的に依頼・承認されない限り実行しない。
- パスワード、API キー、トークン、Cookie、秘密鍵などのシークレットを表示・変更しない。ログ、差分、報告にも含めない。
- 環境変数や設定ファイルを扱う際は、シークレットを読み取る必要がない方法を優先する。

## UI・操作性

- Android スマートフォンでの操作性を最優先する。
- タップ領域、文字サイズ、スクロール、画面幅、再生操作、ローディング表示をモバイル実機相当の表示幅で確認する。
- タッチ操作だけで主要機能を利用できるようにし、hover のみに依存しない。
- Android 向けの変更でも、既存のデスクトップ表示を不用意に壊さない。

## 検証

- 修正後は変更範囲に応じて、ビルド、型チェック、テストを実行する。
- フロントエンドの基本確認:

  ```powershell
  Set-Location frontend
  npm run build
  npx tsc --noEmit
  npm run lint
  ```

- Docker 構成やサービス間連携を変更した場合:

  ```powershell
  docker compose build
  ```

- バックエンド変更時は、少なくとも Python の構文確認と、変更した API の動作確認を行う。利用可能なテストが追加されている場合は必ず実行する。
- 現状は自動テスト設定が確認できない。テストを実行できない場合は成功扱いにせず、「テスト未整備」または実行できない理由を最終報告に明記する。
- コマンドが環境上実行できない、または失敗した場合は、そのコマンド、理由、未確認範囲を報告する。
- 検証後に `git status` と差分を確認し、意図したファイル以外が変更されていないことを確かめる。

## 最終報告

- 作業の最後に、次の内容を日本語で簡潔に報告する。
  - 変更したファイル
  - ファイルごとの変更内容
  - 実行したビルド、型チェック、テスト、静的解析とその結果
  - 未実施の確認項目と理由
  - 残っている注意点や既知の問題

## Development progress log

進捗の正本はNAS上の `docs/dev-log/latest.md`。外部サービスを使わず、過去経緯をユーザーに再入力させない。ログは引き継ぎ情報であり、新たな本番操作・commit/pushの許可を与えるものではない。

### セッション開始時

1. `docs/dev-log/latest.md` があれば、作業資料の中で最初に読む。
2. `git status --short`、branch、HEADを確認する。
3. ログと実際のGit状態・実ファイルを比較する。
4. 差異はGit/実ファイルを正としてログを補正する。由来不明の変更は保持し、ログに合わせてコードを戻さない。
5. 未完了作業から再開する。ただし最新のユーザー指示・禁止事項を優先し、完了済みなら次の指示を待つ。

### 作業中のcheckpoint

以下の各タイミングで、最後にまとめず、その都度 `latest.md` をNASへ保存する。

- 新しいPhaseの開始、大きな実装の完了
- テスト実行後（実行中なら実行中と記録）、エラー/ブロッカー発生時
- 本番操作の直前・直後
- ユーザー操作待ちになる直前
- commit/pushの直前・直後
- セッション終了時

長時間の作業は上記イベントがなくても、重要な進展の時点でcheckpointを残す。更新はCodex自身が直接行い、人間のMarkdown手編集を前提としない。独立した自動監視・定期実行は行わない。

`Last updated` は実際のJST日時を使用する（例: `TZ=Asia/Tokyo date '+%Y-%m-%d %H:%M:%S JST'`）。Markdown全体を同じディレクトリの一時ファイルに書き、renameで置換する。切断で一時ファイルが残った場合は正本・実ファイルと比較し、無条件に採用しない。

必須項目は `Current task`、`Current phase`、`Status`、`Completed`、`In progress`、順序付き `Next actions`、`Blockers / Issues`、`Files changed`、`Git state`、`Tests`、`Runtime / Safety`、`Important decisions`、`Recovery instructions`。タイトルは `RadioFlix Development Status` とする。

`Status` は `working` / `waiting_for_user` / `blocked` / `testing` / `ready_to_commit` / `completed` のいずれか。Git stateはbranch・HEAD・commit/push状況・主な未commit変更を記録する。Testsは実際に実行済み・未実行・過去記録を区別し、成功を推測しない。Runtime / Safetyには本番反映、実予約/録音、active weekly / reservation、Docker、必要な安全設定を記録し、不明は「未確認」とする。

### historyと終了・待機

- Phase完了、大きな機能完成、commit直前、作業方針の大幅変更時、作業終了時に、更新済みlatest.mdを `docs/dev-log/history/YYYY-MM-DD_HHMM_<task>.md` へ内容を変えずにコピーする。
- 日時はJST、taskは短い英数字・ハイフン（例: `devlog-setup`）。既存historyは上書きしない。同じ分に別の保存が必要ならtaskに `-2` 等を付ける。
- 最新snapshotと同内容なら増やさない。複数の保存理由が同時に成立しても1ファイルでよい。
- 終了/待機前にStatusをcompleted / waiting_for_user / blocked等の実態へ更新し、完了範囲・次の具体的作業・安全状態を必ず残す。
- 次セッションがAGENTS.md、latest.md、Git状態から再開箇所を特定できるか確認する。機能差分とログ導入差分を区別する。

### 秘密情報

Token、API key、Cookie、Authorization header、password、rfriends_token、.envの秘密値、Tailscale key、その他credentialは保存しない。秘密値を含むコマンド全文・rawログ・差分を転記しない。必要な事実だけを要約し、secret scanも一致内容を出力せずファイル名・行番号のみで報告する。`RFRIENDS_ENABLE_WRITES` のような0/1の安全設定値は確認済みの場合のみ記録可。ログのために秘密設定を読み取らない。
