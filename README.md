# RadioFlix

Netflix for Radio.

## Features

- Radio discovery
- Recommendations
- rfriends3 integration
- Podcast integration

## Environment

- Frontend: Next.js
- Backend: FastAPI
- Database: SQLite
- Deployment: Docker Compose

## rfriends3 予約連携（第1段階）

既存の曜日別画面から番組詳細を開き、次回の放送回を選んで「今回だけ録音」「毎週録音」を登録できます。詳細画面と `/reservations` で予約状態の確認・解除ができます。録音一覧・再生機能は従来どおりです。

曜日別画面の時刻は録音履歴からの推定値です。予約には、設定地域のradiko番組表から照合した実際の開始・終了日時を使用します。放送局と正規化した番組名が一致しない場合は予約できません。特番・改題・終了番組などを推測で予約する機能はありません。時刻はすべて日本時間です。午前5時より前の曜日別表示は、引き続き前日の24〜28時台です。

### 構成と対応範囲

```text
番組詳細・曜日別予約バッジ・予約一覧
  → FastAPI 予約API → ReservationService → SQLite
                                      → RfriendsAdapter
                                        → 内部専用rfriends-gateway
                                          → Docker exec（既存の録音ユーザー）
                                            → RadioFlix専用PHPドライバー
                                              → 予約データ＋atジョブ
                                                → 既存rfriends3の録音処理
```

- rfriends3依存コードは `backend/radioflix/adapters/` に集約しています。rfriends3のソース、キーワード設定、crontabは変更しません。
- 予約操作ではrfriends3のWeb画面や `rf_inc.php` を読み込まず、更新・掃除などのPHP初期化処理を実行しません。録音時だけ既存の `rfriends_rec.php` と `rfriends_rec_fin.php` に処理を渡します。
- 対応するのは、調査したLinux／PHP／`at`方式のradikoライブ録音です。らじる・タイムフリー・systemd方式・他OSは対象外です。rfriends3更新後は隔離テストと互換性確認が必要です。
- 予約データは既存の19項目形式で、名前に `_radioflix_<ID>` を付けます。`rsv/.radioflix/` に所有情報・登録／開始／終了／解除の記録を保存します。予約データには番組表の地域IDも含めます。
- 所有情報と内容が一致する予約だけを操作します。同じ放送局の既存予約と時間が重なる場合は登録を拒否します。別の操作画面との同時登録を完全に排他する仕組みはないため、試験中は同じ番組をrfriends3側で操作しないでください。
- 一覧とバッジは **RadioFlixから登録した予約** が対象です。rfriends3で直接作成した予約の取り込み・解除は対象外です。既存予約は上書き・削除しません。
- 毎週予約は **同じ放送局・曜日・開始／終了時刻の固定枠** です。RadioFlixのDBにルールを保存し、60秒ごとの確認で前回の処理終了を確認してから次週分を作ります。番組移動や特番には追従しません。次週以降を登録するにはRadioFlixの稼働が必要です。すでに登録した単発ジョブはRadioFlix停止中もrfriends3が実行します。
- 録音ジョブは開始約2分前（分単位に切り下げ）に起動します。新規登録は開始3分前まで、解除はジョブ起動前までです。録音中の強制停止は行いません。大きな録音前マージン等を設定している環境は別途互換性確認が必要です。

### 設定と確認済み範囲

元の `docker-compose.yml` は変更していません。`docker-compose.rfriends.yml` を明示的に重ねた場合だけ、DB永続ボリュームと内部Gatewayを追加します。rfriends3の再作成や既存ネットワークの変更は不要です。

backend/frontendは本番へ反映済みです。確認時点では `RFRIENDS_ENABLE_WRITES=0` に戻してあり、デフォルト値も `0` です。次の範囲を実機で確認しています。

- RadioFlix UIからrfriends3への単発予約登録
- rfriends3側での対応するdat/sh/atジョブ生成
- RadioFlix UIからの予約解除と、対応するdat/sh/atジョブ削除
- 既存rfriends3予約へ影響しないこと
- rfriends3の既存予約による実録音の完走

この確認は上記の範囲に限られます。すべての録音方式や障害条件、毎週予約の長期運用を検証済みとするものではありません。

放送予定取得については、一部の日が一時失敗しても取得できた日を返す耐障害性改善を実装済みです。

GatewayにはホストのDockerソケットへのアクセス権があるため、ホストを操作できる強い権限があります。ソケットはGatewayだけに渡し、APIを外部公開しないでください。バックエンドとの通信には専用トークンを使用します。rfriends3のログイン情報やCookieは不要です。

1. NAS上で録音ユーザー、`atd`の稼働、以下のパスと地域設定を確認します。設定確認のために認証用INIファイル全体を表示しないでください。
2. 専用トークンを `secrets/rfriends_token` に用意します。32文字以上のランダム値をファイルへ直接生成し、画面やログに出力しないでください。`secrets/` はGit除外済みです。既存トークンを上書きしない生成例:

   ```bash
   python3 - <<'PY'
   import os
   import secrets
   from pathlib import Path
   directory = Path('secrets')
   directory.mkdir(mode=0o700, exist_ok=True)
   descriptor = os.open(directory / 'rfriends_token', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
   with os.fdopen(descriptor, 'w') as stream:
       stream.write(secrets.token_urlsafe(48) + '\n')
   PY
   ```

3. 環境に合わせて次の設定を指定します。APIの認証は既存のリバースプロキシ／LAN制限側で行ってください。Gateway用トークンはブラウザーの利用者認証にはなりません。予約APIを含め、認証なしでインターネットへ公開しないでください。

| 設定 | 初期値／意味 |
|---|---|
| `RADIOFLIX_DB_PATH` | 追加Composeでは `/data/radioflix.sqlite3`。`radioflix-reservations` ボリュームに保存 |
| `RFRIENDS_GATEWAY_URL` | バックエンド専用。`http://rfriends-gateway:8011` |
| `RFRIENDS_TOKEN_FILE` | 両サービスで `/run/secrets/rfriends_token` |
| `RFRIENDS_AREA` | 番組表地域。初期値 `JP13`。rfriends3の録音地域に合わせる |
| `RFRIENDS_CONTAINER` | Gateway側。既存コンテナ名 `rfriends3` |
| `RFRIENDS_USER` | Gateway側。既存録音ユーザー `user` |
| `RFRIENDS_BASE` | Gateway側。`/home/user/rfriends3` |
| `RFRIENDS_TMP` | Gateway側。`/home/user/tmp` |
| `RFRIENDS_QUEUE` | Gateway側。`a`。小文字英字1文字のatキュー |
| `RFRIENDS_ENABLE_WRITES` | **デフォルト値・現在確認値ともに `0`**。登録・解除を拒否。必要な操作時だけ明示的に `1` にする |

`RFRIENDS_AREA` と `RFRIENDS_ENABLE_WRITES` はシェル環境またはGit除外対象の `.env` で指定できます。それ以外のパス等は追加Composeの値を環境に合わせます。既存の録音マウントは読み取り専用のままです。Gatewayは内部ネットワークだけに接続し、ホスト側ポートを公開しません。

構成確認・ビルド例:

```bash
docker compose -f docker-compose.yml -f docker-compose.rfriends.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.rfriends.yml build
```

今後再反映する場合は、対象と影響を確認したうえで上記の2ファイルを指定します。実機操作後は `RFRIENDS_ENABLE_WRITES=0` に戻し、DB・番組表・画面と既存予約への影響を確認してください。

調査時点ではrfriends3の `config` と `rsv`、コンテナ内のatキューが永続化されていません。この追加Composeはその構成を変更しません。rfriends3を再作成すると設定・予約を失う可能性があるため、既存設定と予約のバックアップ／永続化を先に別途計画してください。

### 操作と状態

1. 曜日別画面の番組をタップします。録音一覧の上に予約欄が表示されます。
2. 実際の放送日時を確認して放送回を選び、「今回だけ録音」または「毎週録音」を押します。
3. 録音側のジョブ存在を確認できた場合だけ「予約済み」になります。連打や再送では同じ予約IDを使います。方式を変更する場合は既存予約を解除してから登録します。
4. 詳細画面または「録音予約一覧」で解除します。毎週の場合は以降の生成も停止します。解除の応答が途切れた場合も解除意図をDBに保持し、次週分を追加しません。

| 状態 | 意味と対応 |
|---|---|
| 登録処理中 | DBへ操作意図を保存済み。録音側の確認待ち |
| 予約済み | 対応する録音ジョブを確認済み |
| 登録失敗 | RadioFlixの予約成立を確認できていない。「再登録」は同じIDで再試行 |
| 予約状態不明／確認遅延 | 通信断、外部変更、確認停止など。新規予約を重ねず「状態を再確認」 |
| 解除処理中／解除失敗／解除結果不明 | 予約が残っている可能性がある。成功扱いにせず再確認する |
| 解除済み | 所有する未開始ジョブの解除を確認済み |
| 放送時間終了 | 実行終了記録と終了時刻を確認済み。録音成功の保証ではないため録音ファイルを確認 |

`GET /api/reservations` はDBの状態を返します。読取要求で録音側へ書き込みません。最終確認から3分以上経過した予約は、最新状態と誤認しないよう確認遅延を表示します。`refresh` は中断操作の復旧や毎週の次回生成を含むためPOSTです。

| API | 用途 |
|---|---|
| `GET /api/programs/{id}/broadcasts` | 予約可能な放送回を取得 |
| `GET /api/reservations` | 対応情報・状態・処理履歴を一覧取得 |
| `POST /api/reservations` | `program_id`, `broadcast_id`, `mode: once/weekly` で登録 |
| `DELETE /api/reservations/{id}` | 解除（再実行可能） |
| `POST /api/reservations/{id}/refresh` | 録音側の状態再確認と中断処理の復旧 |
| `POST /api/reservations/{id}/retry` | 未登録を確認したジョブを同じIDで再登録 |

操作結果は返却JSONの `state` と `message` で判定します。操作記録が保存できた場合、録音側で失敗してもHTTP 200と失敗状態を返します。HTTP 200だけを予約成功として扱わないでください。

### バックアップと復旧

- SQLiteを削除して再登録しないでください。DBには予約ID・毎週ルール・解除意図・録音側の対応情報が入っています。SQLiteのbackup APIまたはRadioFlix停止中のファイルコピーで保全します。`docker compose down -v` は予約DBを削除するため使用しないでください。
- rfriends3側は、RadioFlixが作った `rsv/*_radioflix_*` と `rsv/.radioflix/` の所有情報も保全します。認証情報を含み得るatジョブ全文や環境変数をログ・Gitへ保存しないでください。バックアップ先はリポジトリの外に置きます。
- 通信切断・Gateway停止: 接続を復旧し「状態を再確認」。同じIDのジョブを確認して状態を復元するため、二重登録しません。
- 登録途中で停止: DBと所有記録を保持して再起動。ジョブが存在すれば予約済みに復旧します。存在しないことを確認した場合は再登録できます。開始3分前を過ぎた放送は新規登録しません。
- 解除途中で停止: 解除意図を維持して解除を再試行します。解除が完了するまで予約履歴を削除せず、毎週の次回生成も止めます。
- rfriends3の再作成・予約データの外部変更: 自動で既存予約を作り直したり上書きしたりしません。DB・所有情報と現在のジョブを照合し、未開始のものだけ同じIDで再登録してください。所有情報が欠落／不一致の場合は操作を停止します。
- ジョブがなく、開始・終了記録も確認できない場合: 録音中・完了と推測せず結果不明を保持します。管理者がrfriends3の実行状況と対象ファイルを確認してから、対象だけの復旧方針を決めてください。未知状態を消すために既存予約全体やDBを初期化しないでください。
- 長期間RadioFlixを停止した場合: 確認できた前回処理から、未来の同じ曜日・時間帯へ進めます。過去の未録音回の埋め合わせはしません。

### 開発時の検証（実予約なし）

```bash
cd backend
python3 -m venv /tmp/radioflix-tests
/tmp/radioflix-tests/bin/pip install -r requirements-test.txt
/tmp/radioflix-tests/bin/python -m compileall -q app.py radioflix tests
/tmp/radioflix-tests/bin/python -m unittest discover -s tests -v
cd ../frontend
npx tsc --noEmit
npm run lint
npm run build
```

API／Adapterテストは模擬通信と一時DBを使用します。PHPドライバーテストは空の録音スクリプトと偽の `at/atq/atrm` を使い、初期化・既存予約の変更・二重登録が起きないことを検証します。PHP CLIがない場合はPHPテストがスキップされます。PHP入りのローカルイメージを使う場合は、ネットワーク無効・テスト用ディレクトリだけのマウントで実行できます（実コンテナへのexecは行いません）。

```bash
cd backend
RADIOFLIX_TEST_PHP_COMMAND='["docker","run","--rm","--network=none","--read-only","--mount","type=bind,source=/tmp/radioflix-driver-tests,target=/tmp/radioflix-driver-tests","--entrypoint","php","rfriends3-rfriends3"]' \
  /tmp/radioflix-tests/bin/python -m unittest discover -s tests -p test_rfriends_driver.py -v
```

実機試験は別です。既存予約と重ならず、開始まで十分余裕のある番組・日時を利用者と合意してから、単発登録→表示確認→解除、毎週登録→解除、最後に必要なら録音完了まで確認します。毎週の試験ルールを残さないようにしてください。
