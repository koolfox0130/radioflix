# RadioFlix 番組表・未来予約・過去録音 統合設計

調査日: 2026-09-25 JST。対象は実稼働rfriends3コンテナ内ソースと現在のRadioFlix。調査・設計のみで終了。以下の「確認」はソースまたは公開XMLの読み取りによるもの。「設計」は今後実装する内容であり、動作検証済みの機能ではない。

## 1. rfriends3タイムフリー録音の仕組み

本体はホストの`/home/kool-fox/Share/Radio/rfriends3`直下ではなく、コンテナ`rfriends3`内の`/home/user/rfriends3/script`にある。ホスト側はconfig、rsv、at spool等の永続化領域。読み取った`rf_inc.php`のverは2025.09.02、downloader表示はVer.3.2.2であり、配布最新版と同じとは仮定しない。

UIで選択した番組の経路:

```text
html/menu/menu03.php、menu03s.phpで局・日・番組選択
  → html/menu/menu03ss.php（0301/0302、sel=1）
  → ht_sub.php::ht_rec_start("rec", wdat, ex_timefree)
  → rf_common06.php::rf_batsh_rec(ex_timefree, 0, ...)
      tmpdir/timefree_kw_*.datへ選択番組のwdataを保存
  → rf_gateway_def.php::rfgw_batsh_sub()
  → sh ex_rfriends.sh 4 "0,1,<dat basename>"（バックグラウンド）
  → rfriends_exec.php::rfriends_exec_sub()、case 4
  → rfriends_exec_timefree_kw.php
  → rf_timefree.php::timefree_kwrec_ex()
  → rf_downloader.php::rfriends_downloader(ex_timefree=5, ...)
  → radiko認証 → HLSプレイリスト取得 → ffmpeg
  → メディア検査・タグ付け・保存 → 設定による転送等
```

`rfriends_exec_timefree_kw.php`は選択datを処理後、失敗分をもう一度処理し、最後にdatを削除する。処理済み行は`#`になる。このdatを永続ジョブ台帳として使用しない。

別経路として`rfriends_exec_timefree.php`は日付・日数とキーワードで一括抽出し、`timefree_ex → timefree_go → timefree_kwrec_ex`を呼ぶ。`rfriends_exec_timefree_multi.php`は複数日を扱う。現行ユーザーcrontabには毎日05:25、17:25の`ex_rfriends.sh`呼び出しがあり、`sch_rsv_timefree="on"`。デイリー処理からcase 5へ進む。選択番組の即時タイムフリー録音自体は、未来予約用のat登録を必要としない。

注意: 名前が適切に見える`rfriends_rec_timefree.php`は今回読んだソースに`require_once("rf_timfree.php")`と`$reg_dur = para[2]`がある。主要UI経路でもなく、採用しない。実行はしていない。

実際のdownloaderは`rfriends_auth_radiko()`を利用し、normal auth／premium auth／設定された認証モードを切り替える。normal authはauth1/auth2とキャッシュ、premium側はログイン状態・Cookie等を扱う。これらは既存PHPを再利用し、RadioFlixで再実装しない。認証ファイルの内容・アカウント設定は今回取得していない。

現在のタイムフリー分岐には`$tf30 = 1`があり、7日以内でも`get_timefree_stream_url_tf30()`を通る。同関数は300秒単位のプレイリストを集める。関数名がtf30でも、30日分を利用できる権利が確認されたことにはならない。

## 2. RadioFlixから利用できる安全な入口

**そのまま安全に呼べる単一番組・冪等・結果確認付きAPIはない。** 既存RadioFlix Gatewayの`/execute`は未来予約のcreate/inspect/cancelだけで、過去録音には対応しない。

既存CLIは機能上利用できるが、`rf_inc.php`のトップレベルで`dir_init`、`rf_update`、キーワードコピー、ログ清掃起動等が走る。downloader内部にも共有tmpの古い音声削除、既存ファイルの上書き、録音ファイル削除・移動、転送、配信、ユーザースクリプト、通知への経路がある。CLIを本番コンテナ内で直接呼ぶ方式は採用しない。

最小の安全な追加単位は、専用Gateway操作、永続ジョブworker、rfriends互換bootstrap、所有物だけをNASに公開するpublisher。

- Gateway操作は`timefree.create`、`timefree.inspect`と読み取り専用のnative状態照会だけに限定する。任意コマンド・パス・URLは受け付けない。
- 専用workerはrfriends3の同じソース版と必要な実行環境を使用。本番config/rsv/at/tmp/録音ディレクトリを書き込み可能で渡さない。Docker socketも渡さない。
- `rf_inc.php`をrequireしないbootstrapを用意し、必要な関数定義・設定値だけを構成して`rfriends_downloader(5, ...)`を直接呼ぶ。認証・HLS・ffmpeg・メディア処理は既存PHPを再利用する。依存ファイルのトップレベル副作用とバージョンを検査し、不一致時は起動拒否。
- 全tmp・log・認証キャッシュ・出力はRadioFlix専用領域。`timefree_radiko_del=0`、転送・配信・ユーザーフック・自動更新・自動清掃による共有領域アクセスを禁止する。これは専用worker内だけの設定で、本番設定は変更しない。
- workerから実NASの既存録音に書き込めない構造にする。publisherが検証済みの新規ファイルだけを、上書き不可の原子的公開手順で配置する。
- bootstrapの依存関係充足、設定再現、秘密情報を含む出力の抑止はPhase 4の隔離試験で証明する。現段階で「既に安全に呼べる」とはしない。

既存選択CLIを隔離環境で比較対象として使うことは可能だが、その終了コード・テキストログだけを正式なジョブ結果にはしない。

既存未来予約driverの`inspect`も、条件次第でロックファイルを開き、`.submitted`を補完するため、ファイルシステム上で完全な読み取り専用ではない。番組表のnative状態照会にはこの処理を流用せず、明示的な読み取り専用readerを追加する。今回は既存Gatewayのinspectも呼んでいない。

## 3. 必要な入力パラメータ

ブラウザからは`broadcast_id`、`schedule_revision`、`idempotency_key`のみを受け取る。未来予約では追加で`mode=once|weekly`。station/start/end/titleをクライアントの申告だけで採用しない。

サーバーが再取得した番組表から確定する内部入力:

| 項目 | 内容 |
|---|---|
| station | radiko局ID。局一覧の許可集合に一致すること |
| start/end | JSTの日時。rfriendsへはYYYYMMDDHHMMSS |
| duration | end-startの秒数。XMLと整合確認 |
| title | 表示用の原題と、安全に扱う内部値を分離 |
| region | サーバー設定地域。v1は既存設定のJP13を基本とする |
| provider_program_id | XML prog/@id。監査・照合の補助。クライアント任意指定不可 |
| restrictions | failed_record、ts_in_ng、ts_out_ng等。欠落時は許可扱いにしない |
| optional metadata | pfm、画像、genre等。任意URLのサーバー取得は禁止・制限 |
| job_id/attempt_id | RadioFlix発行UUID。出力・ロック・結果ファイルの所有権に利用 |

rfriendsのwdataは19フィールド。添字順に`ft, to, dur, failed_record, in_ng, out_ng, channel, title, artist, img, kw, prog_id, jobno, jparea, area, album, genre, genrec, musiclist`。空欄は`;`。`get_para`と`rf_make_wdata`が処理する。program IDはHLS要求の必須識別子ではなく、基本は局・開始・終了で録音する。過去録音ではXML由来IDを保持する。

生のwdata文字列・シェル引数・画像URLをユーザーに構築させない。PHP側もPython側と同じ検証を行う。rfriends内部にはシェル文字列の組み立てがあるため、外側でescapeshellargするだけでは不十分。workerの物理パス・一時ファイル名・内部録音名は固定形式のASCIIとUUIDを使い、自由文メタデータはシェルに流さず安全なargv経由で付与する。既存PHPのどの補助処理もこの境界を越えないことをテストする。

## 4. タイムフリー期限

公式の通常タイムフリーは過去7日、タイムフリー30は対象プランで過去30日。通常は聴取開始後24時間以内・合計3時間という制限もあり、「番組表があるから録音可能」とは判定しない。[radiko公式ヘルプ](https://help.radiko.jp/--67aeb822b872f9ca816d8519)

rfriendsのUIは通常-7日〜当日、30対応は-30日〜当日。`rf_calc_radiodate`は05:00を日境界とし、`rf_diff_timefree`はその放送日差を計算する。一方`timefree_check()`の主な検査は「終了時刻+t_rmarginに達したか」で、確認した標準値は120秒。期限切れを単独で厳格に拒否する入口にはなっていない。配信不可情報もdownloaderの入口だけでは安全に拒否しきれないためGateway側で検査が必要。

v1は7日枠のみ。放送日Dを`date(start_at - 5時間)`とし、暫定的な受付上限を`D+8日の05:00 JST`とする（rfriendsの-7日表示と整合する保守的なアプリ受付規則）。配信側からより早い期限が判明した場合はその時刻を優先し、境界直前は余裕時間を設けて受け付けない。この日時はradikoの成功保証ではない。

実行条件は`end+120秒 <= now < acceptance_deadline`、対象局・地域・配信可否の確認済み。放送中はv1対象外。未終了／配信準備待ち／期限切れ／地域対象外／配信対象外／状態不明を区別する。30日機能と追いかけ録音はv1に含めない。

## 5. 成功・失敗・録音中・録音済みの判定

既存関数の戻り値は正常0、録音済み1、配信なし2、異常3、正常＋別録音削除等11。現在の本番設定は`timefree_radiko_del=0`だが、今後の変更に依存しない安全制約が必要。

- 実行中の補助証拠: dispatcherの`.trun`、downloaderの`.run`、workerプロセス。`.run`はffmpegの実行区間だけで認証・保存中にはない。ファイル単独で実行中を確定しない。
- `.end`はffmpegが非0終了でも作られる。`.skp`は重複検出。どちらも正常なNAS保存の証明ではない。
- downloaderはffmpeg終了、ファイル存在、メディアduration、保存成否を検査する。予定より20秒以上短い場合は不良扱いになる。ただし転送処理は結果が十分伝播しないため、戻り値0だけで最終NAS公開成功とはしない。
- 既存予約の`elapsed/completed`は「放送時間終了」であり録音済み判定に転用しない。

新規状態は`queued → starting → running → verifying → publishing → succeeded`。補助的に`already_recorded, failed, expired, unavailable, blocked_native, unknown`を持つ。受付HTTPは202とjob_idを返し、録音中のHTTP接続を保持しない。

成功条件は構造化結果＋音声ストリーム存在＋非ゼロサイズ＋期待durationとの整合＋NASへの完全公開＋recording_assetsへの登録。短い・壊れたファイルは隔離し「録音済み」にしない。`not_deliver`だけから期限切れを断定しない。

worker台帳にはプロセス識別子、開始時刻、heartbeat、段階、attempt、戻り値、成果物相対パス、サイズ、durationを原子的に記録。プロセス消滅／通信断はまずunknown。NASだけ完成して応答が失われた場合はmanifestと成果物を検査して復元し、再録音しない。

## 6. 番組表で取得できた実際の日付範囲

2026-09-25 05:47〜05:48 JST、公開`https://radiko.jp/v3/program/date/YYYYMMDD/JP13.xml`をGET。認証・再生APIは呼んでいない。

| 調査範囲 | 結果 |
|---|---|
| 9/18〜9/24（過去7日） | 7日すべてHTTP 200、番組あり |
| 9/25（当日） | HTTP 200、15局・462番組 |
| 9/26〜10/2（未来7日） | 7日すべてHTTP 200、番組あり |
| 10/3、10/4（未来8・9日） | HTTP 404 |
| 9/16、9/17（過去9・8日） | HTTP 200 |
| 8/24〜8/27、9/10、9/15（追加点検） | HTTP 200。少なくとも32日前のXMLも存在 |

従って今回の15日表示は可能。過去データ保持の最古境界は未確定で、7日や30日がXML保持上限とは言えない。上記はJP13での一時点の観測であり、全地域・全局・今後の保証ではない。

9/30応答は実際にgzipバイナリだった。10/1・10/2の番組数は361・358で、当日の462件より少ない。XML取得成功と各局の全枠公開は分ける。番組なしの局・欠落区間を補完生成しない。

現adapterの`broadcasts/weekly_candidates`は放送日当日〜+7日の8日を取得し、開始3分前より未来だけを返す。`_fetch_day`自体は日付URLの取得処理で、過去7日検索は公開APIとして未実装。

再利用可能: 5分キャッシュ、4並列、各10秒timeout、失敗時0.2秒後に1回retry、gzip magic判定、圧縮前後8MB上限、DTD/ENTITY拒否、日別部分成功。404は現状空配列になるため、新しい番組表APIではnot_available／fetch_failed／station_missing／ok等の日別結果を別途保持する。weeklyの既存戻り値の意味は変更しない。

通常は選択中の1日を取得し、隣接日を控えめに先読み。15日一括取得を画面操作ごとに繰り返さない。404・空・破損・timeoutでは「番組表を取得できませんでした」と理由に応じた再試行導線を表示し、前日データを当日と誤表示しない。

## 7. 放送局一覧取得方法

`GET https://radiko.jp/v3/station/list/JP13.xml`を使用。station一覧のIDは`<station><id>`、日付番組表では`<station id="...">`で構造が違う。

確認した15局: TBS、QRR、LFR、RN1、RN2、INT、FMT、FMJ、JORF、BAYFM78、NACK5、YFM、IBS、JOAK、JOAK-FM。局名・ロゴ等は局XMLから取得可能。番組表の局一覧はフォールバック候補だが、番組がない日でも局を消さない。局一覧キャッシュは日別番組表と分離する。

局一覧に載ることとタイムフリー対応は別。rfriendsのタイムフリー抽出にはNHK除外があり、v1のNHK過去録音は非対応表示。未来予約についても現行連携の対応局として確認できたものだけを有効化する。

番組XMLで確認した情報は`id, master_id, ft, to, dur, title, pfm, desc, info, img, genre, failed_record, ts_in_ng, ts_out_ng, tsplus_in_ng, tsplus_out_ng`等。今回の先頭番組のmaster_idは空。idは存在するが週をまたぐ安定したシリーズIDとは確認できず、依存しない。現在のBroadcastはstation/title/region/start/endと独自idのみで、出演者等は捨てている。

## 8. 番組表用ID設計

既存IDを混用しない。

| ID | 用途・設計 |
|---|---|
| legacy program_id | 録音フォルダ名のURL-safe Base64。既存URL・APIを維持 |
| broadcast_id | 現adapterのSHA-256(station + ':' + start.isoformat() + ':' + end.isoformat())を維持。JSTへ正規化 |
| schedule_revision | タイトル・出演者・配信制限等を含むメタデータのfingerprint。変更検出用 |
| provider_program_id | radiko XML idの保存値。主キーにしない |
| series_id | 録音フォルダがなくても存在できる内部UUID。シリーズのカタログ |
| subscription_id | 現行weeklyのUUIDを維持。ユーザーの継続予約意思 |
| job_id / attempt_id | 個々の処理と再試行。broadcast_idとは別 |

タイトルをbroadcast_idに加えるとタイトル修正で別放送扱いになるので加えない。終了時刻変更では既存方式上IDが変わるため、同一局・同一開始時刻または時間重複も確認し、別IDだから新規録音可能とはしない。旧→新放送IDの対応は予定変更履歴として残す。

seriesは`station + weekly_title_key + 曜日・時刻アンカー`を照合候補にするが、その文字列hashを唯一のシリーズIDにはしない。同名番組、複数枠、番組改編を曖昧扱いにできるUUIDとalias表を使用。候補が複数なら自動統合しない。

現行weeklyは局・title_key一致、予想時刻±2時間、候補1件のみ採用、次回予定+7日という仕組み。これを保持する。放送回IDからsubscription IDを生成せず、録音フォルダがなくてもseriesとsubscriptionの保存情報だけで追従できるようにする。

## 9. 未来予約との統合

番組表選択 → 最新番組表でID/revision再検証 → server側のprogram/series resolver → 既存ReservationService.create/create_weekly → 既存Gateway/driver。

現APIは`programs.find_program()`で録音フォルダの存在を必須とし、weeklyの追従も同関数を使う。この2箇所は対応が必要。架空フォルダを作らず、カタログを参照するresolverを追加する。既存program_idはaliasとして保持し、既存subscription IDと履歴を変更しない。

現行重複判定はprogram_idに依存する箇所があるため、画面が違っても同一局・同一放送回で共有する重複判定を追加。既存録音詳細画面からの予約と番組表からの予約が二重登録されないようにする。once→weeklyを自動変換しない。

開始3分前ガード、時刻変更時の所有予約だけの解除→確定後再作成、解除監査、unknown時に停止する既存原則を維持。native予約の同局時間重複はconflict。native予約をRadioFlix所有へ取り込まず、上書き・解除・自動置換しない。

## 10. 過去タイムフリー録音との統合と出力先

本番設定の許可リスト部分を読み取った結果:

- usrdir: `/home/user/smbdir/usr2/`
- tmpdir: `/home/user/tmp/`
- timefree出力の通常サブディレクトリ: `timefree`
- `rftrans=2`, `rftrans_s=1`, `rftrans_timefree=0`
- ファイル名書式: `%4$s_%5$s_%1$s_%2$s`、開始`Ymd_Hi`、終了`Hi`
- 標準拡張子m4a、tf_footerは空

正常時の名前は基本的に`STATION_加工済みタイトル_YYYYMMDD_HHMM_HHMM.m4a`。NG／短時間録音のprefix、callsign変換、タイトル短縮等で変わる。固定文字列の推測だけで照合しない。

現在の通常タイムフリー保存先は、確認した設定から`/home/user/smbdir/usr2/timefree/`、NAS側`/volume1/@home/kool-fox/radiko_public/timefree/`になる。転送がoffなので、番組別フォルダ整理も自動では期待できない。

RadioFlixの実マウントは`.../radiko_public/radiko → /recordings:ro`のみ。ProgramServiceも直下の番組フォルダを一覧化する。したがって既存タイムフリーCLIを呼ぶだけではRadioFlixの一覧に出ない。

採用設計: workerは専用stagingへ録音、publisherがNASの専用`radioflix-timefree`ルートへ公開し、backendはそのルートを読み取り専用で追加。recording_assetsがseriesと既存program_idに紐付け、一覧・再生APIから一緒に見せる。実NASのradiko/timefree既存ファイルは移動・改名しない。native timefreeの既存分も照合するため、当該ルートを別のread-only sourceとしてindexerに渡す。

新規番組はseries UUIDで一覧化し、従来番組にはaliasで合流する。音声URLはasset_idで解決し、クライアント指定パスをそのまま返さない。保存後にindex登録が失敗した場合はpublishing/unknownから復旧し、再録音しない。

## 11. 二重録音防止

RadioFlix内はDBのUNIQUE制約と永続台帳、workerの同一broadcastロック、同じidempotency_keyで同じjobを返す仕組みで防止する。queued/starting/running/verifying/publishing/unknownの間は新規attempt不可。終了時刻変更・改題も同局時間重複で検出する。成功後の再録音ボタンはv1では提供しない。

既存録音の照合は「局ID＋実放送開始＋終了／音声duration＋タイトル補助」。メディアタグ、既知のrfriends命名書式、出所、正常性を保存する。mtime単独・ファイル存在だけ・同じタイトルだけで録音済みを確定しない。独自命名や断片録音など曖昧なものは`recording_match_unknown`として再実行を止める。

native rsv dat、実行中状態、保存済みファイルは読み取りだけ。native予約／実行が同枠にあれば取り込みも解除もせずblocked_native。rfriendsの`timefree_double_rec=0`はファイル名ベースであり、原子的な実行ロックではない。現在のdownloaderは保存時に既存の宛先を削除できるため、その防止はファイルシステム隔離で強制する。

**限界:** RadioFlixのロックを本番native処理は見ない。照会直後にnative cron/UIが同番組を開始する競合を、native側無変更のまま数学的に排除することはできない。v1はnative処理検出時に停止し、開始前と公開前に再照合する。競合が判明した出力は隔離して自動公開・既存置換をしない。RadioFlix自身の二重実行と既存データ破壊は防ぐが、外部同時開始による重複ダウンロードまで完全保証とはしない。完全保証が要件なら共有ロック等の別設計が必要で、今回の権限では本番へ導入しない。

## 12. API構成案

| API | 用途 |
|---|---|
| GET /api/stations | 設定地域の局一覧、対応機能 |
| GET /api/schedule?station=...&date=YYYY-MM-DD | 放送日05:00〜翌05:00。番組と日別取得状態 |
| GET /api/broadcasts/{id} | 詳細、revision、出所、各状態、allowed_actionsと理由 |
| POST /api/broadcasts/{id}/reservations | once/weekly。既存サービスに接続 |
| POST /api/broadcasts/{id}/timefree-recordings | 冪等受付。202または既存job |
| GET /api/timefree-recordings/{job_id} | 永続状態照会 |
| POST /api/timefree-recordings/{job_id}/retry | 確定失敗のみ。期限・native状態を再確認 |
| GET /api/recordings/{asset_id} | 保存済み成果物の安全な参照 |

既存のreservations/subscriptions APIは維持。過去録音の取消・削除はv1対象外。

番組表レスポンスは`radio_date/timezone/fetched_at/stale/availability/broadcasts`、番組ごとに予約状態、録音状態、配信状態を別フィールドで返す。巨大な全番組表に逐次Gateway照会を付けず、まとめて取得した状態スナップショットと照合する。POST時はキャッシュだけを信じず再検証する。

## 13. DB追加

SQLiteは既に存在する。現状説明の「SQLite利用コードなし・テスト未整備」は現在のソースには当てはまらず、reservations/recording_jobs/weekly_subscriptionsとテストが実装済み。

新DB製品は不要。既存SQLiteへ段階的migrationで次を追加する:

- `program_series`、`program_aliases`: 録音フォルダに依存しないシリーズと既存ID対応。
- `broadcasts`、`broadcast_revisions`: 放送情報、XML由来ID、配信条件、更新履歴。キャッシュと予約時のsnapshotを区別。
- `timefree_jobs`、`timefree_attempts`: 受付意思、冪等キー、状態、worker識別、期限、再試行、結果。
- `recording_assets`: root識別子・安全な相対パス、局・時間・duration・size、source、所有者、照合確度。
- `audit_events`／outbox: intentと同一transactionで必要な監査を確定し、配送を再試行可能にする。

既存recording_jobsはreservation_id必須なので、過去録音を無理に混ぜない。schema_versionで管理し、既存weeklyへの後方互換を保つ。長時間ネットワークI/O中に全予約ロックを保持しない。DB制約と短いtransactionで受付を確定し、workerへ引き渡す。

## 14. UI構成

上部に`録音一覧 / 番組表 / 予約一覧`。局は選択状態の明確なチップと「すべての局」選択。日付は横スクロール15日、初期位置は放送日としての今日。05:00切替を明示し、翌日未明は「翌01:00」等と表示する。

縦の番組一覧には開始時刻、番組名、開始〜終了、出演者、状態。詳細はタップで表示し、操作ボタンを十分な幅で配置。現在の黒基調を維持。360/390/412px幅、タップ領域48px目安、本文16px目安、hover不要、長い題名の折り返し、端末の戻る・スクロール復元に対応する。

| 状況 | 表示・操作 |
|---|---|
| 未来・受付可能 | 今回だけ録音／毎週録音 |
| RadioFlix単発確定 | 今回のみ予約済み |
| weekly確定 | 毎週録音中。待機・確認失敗は別注記 |
| native予約 | rfriends3で予約済み。編集・解除なし |
| 過去・受付可能 | 録音 |
| 受付中／実行中 | 受付中…／録音中…、再クリック不可 |
| 完成を検証済み | 録音済み、再生へ |
| 確定失敗 | 録音失敗、許可された場合だけ再試行 |
| 期限超過 | 録音期限切れ |
| 放送中／直後 | 放送中／配信準備待ち |
| 非対応／不明 | 対象外／状態を確認できません。操作不可 |

一覧GETだけで副作用を起こさない。予定のstale表示と予約・録音状態のstaleを区別。書込み無効を「予約済み」と見せない。PWAでmutationやジョブ状態を古いキャッシュから返さず、offlineでは録音操作を受け付けない。

## 15. セキュリティ・安全制御

- backendとGatewayの両方で`RFRIENDS_ENABLE_WRITES`を確認。過去録音にはさらに既定offの専用enableを追加。通常0運用を維持する。
- 過去録音はwrites=0時に409で拒否し、将来のenableで突然録音する待機ジョブは作らない。未来予約は現在のwaiting_write方式を維持し、画面で明示する。
- workerがqueuedを取得するときにもgateを確認。実行中の読み取り照会は許可。gate offで勝手にnative処理を中断・削除しない。
- Gateway認証は既存のserver間Bearer、非公開network、redirect拒否を維持。tokenをブラウザに渡さない。
- 現backend APIにはアプリ認証dependencyがなく、CORSは`*`。外部認証プロキシの実効保護は今回未確認。新しい書込み公開前にユーザー認証、認可、trusted proxy検証、Cookie利用時のCSRF対策とOrigin制限を整える。CORSだけを認証としない。
- workerに汎用Docker API・root・native予約の書込み権限を与えない。Gatewayも固定worker操作だけを許可し、実行時間・同時数（v1は1件）・受付件数・ディスク空きを制限する。
- path traversal・symlink・任意ホスト取得・shell injectionを拒否。番組説明HTMLはプレーンテキスト化またはsanitize。画像取得先も制限。
- rfriends内部のraw出力には認証headerを含むコマンドやURLが出る可能性がある。標準出力をそのままAPI/auditへ流さない。認証token/Cookie/秘密設定は保存・表示しない。構造化イベントだけをログとする。
- auditはrequest_id、actor、broadcast/job、操作、gate判定、native conflict、状態遷移、attempt、安全なerror_code、成果物検証を記録。監査を確定できなければ新規開始しない。
- retryは確定した一時障害に限り回数制限・backoff。unknown、認証不備、地域不可、期限切れ、native conflictでは自動再実行しない。CLI内部の自動retryと二重管理しない。
- backend再起動後はDB→worker台帳→成果物を照合し復元。worker再起動でもheartbeatの古さだけで再録音しない。ジョブの生存確認と出力調査を先に行う。

## 16. Phase 1〜6 実装計画

| Phase | 内容 | 完了条件 |
|---|---|---|
| 1 番組表API | station/dayの読み取りAPI、metadata拡張、05:00日付、欠損日、gzip、制約・ID/revision | fixturesでgzip/404/部分欠落/日跨ぎ/ID安定性を検証。予約・録音の副作用ゼロ |
| 2 番組表UI | 共通ナビ、局・15日選択、時系列カード・詳細。実行ボタンは未接続またはdisabled | Android相当幅、読み込み/失敗/再試行、デスクトップ、PWAを確認 |
| 3 未来予約 | series/alias、weekly resolver、既存サービス再利用、横断重複/native状態表示、書込み認証 | fake Gatewayで既存weekly回帰・時刻変更・解除監査・native保護を検証。writes=0で安全 |
| 4 過去録音 | 隔離bootstrap/worker、永続job、期限・制限検査、read-only照合、NAS publisher | fake認証/HLS/ffmpegで通信断・クラッシュ・短い出力・保存失敗・シークレット漏洩・既存ファイル不変を証明。実録音は別途承認された段階のみ |
| 5 状態表示統合 | recording_assets、native録音照合、一覧合流、状態polling、再起動復旧 | 完成・失敗・unknownを誤表示しない。NAS完成後応答消失でも再録音しない |
| 6 スマホ実機試験 | Androidの局日付操作、連打、戻る、再接続、画面回転、一覧再生、既存weekly回帰 | 認証・ゲート・所有権を含むE2E。実データを伴う試験は個別に許可されたものだけ |

状態モデル、DBの一意性、最低限の実行中表示はPhase 4以前に実装する。Phase 5まで二重クリック対策を延期しない。Phase 4は隔離試験・安全条件を満たすまで本番enable不可。

## 17. 既存コードへの影響

今回は変更ゼロ。今後の主な対象:

- `backend/radioflix/adapters/rfriends.py`: 日別取得の情報を共有しつつschedule専用adapter/serviceへ展開。既存broadcasts/weeklyの契約は維持。
- `schemas/reservations.py`: 既存Broadcastを壊さずschedule metadataの別schemaを追加。
- `services/reservation_service.py`: program resolverとID横断重複防止。weekly照合・解除の規則は維持。
- `database/reservations.py`: 互換migration。新規領域は別store/moduleに分ける。
- `api/reservations.py`: 既存URL維持。番組表起点の入口を追加して同じサービスに接続。
- `adapters/rfriends_gateway.py`: 新しい限定操作・状態のschema。録音完了までの長い同期Docker execは使わない。
- `adapters/rfriends_driver.php`: 未来予約の動作を維持。timefreeは別driver/workerで扱う。
- `services/program_service.py`、`backend/app.py`: 新しいasset sourceを既存録音一覧・再生に合流。パス境界を保証。
- `frontend/app/schedule/page.tsx`等の新規UI、既存ナビ・予約部品の再利用。
- `frontend/next.config.ts`: schedule/stations/broadcasts/timefree APIのrewriteを追加。
- Docker設定: 将来の専用worker・永続状態・read-only録音source。現在の本番rfriendsサービスは変更しない。

依存パッケージ追加・更新は今回なし。新workerの実行環境は既存rfriendsのPHP/ffmpeg等を再利用する方針で、具体的な導入変更はPhase 4実装前に説明する。

## 18. 最初に実装すべきPhase

**Phase 1の読み取り専用番組表API。** 局一覧、1日取得、05:00日境界、metadata、配信制約、失敗表現、ID互換を先に確定する。これだけなら通常のwrites=0を維持でき、既存の正式リリース済みweeklyを触る必要も小さい。

## 19. 実装を開始してよい状態か

**YES — Phase 1から段階的な実装を開始できる設計になった。今回は開始せず停止する。**

**NO — 現時点で本番タイムフリー録音を有効化してよい状態ではない。** 隔離bootstrapの互換性、既存PHPの副作用封じ込め、NAS原子的公開、認証境界、クラッシュ復旧、native同時実行の扱いはPhase 4受入条件。完全なnativeとの重複ダウンロード防止を必須とする場合は、共有ロック等を導入できる別の権限・設計が必要。

## 検証・変更記録

- RadioFlixの追跡ファイル変更なし。開始時・終了時とも未追跡は`.codex/`、`frontend/Dockerfile.dev-backup`、`frontend/Dockerfile.production`のまま。中身は変更していない。
- 本番rfriendsのPHPは実行せず、ソース・許可リスト内設定・cronの該当行・マウント情報だけ読み取り。config/rsv/at/録音ファイル変更、実録音、予約、ゲート変更、restart/recreate、commit/push/reset/restoreは未実施。
- `/tmp/radioflix-timefree-analysis`に解析用ソースコピー、表示用整形コピー、公開XML、GET調査スクリプト、この設計書を作成。秘密設定・Cookie・tokenはコピーしていない。
- 公開番組表は前後9日と追加の過去6日付、局一覧を実GET。通常sandboxではネットワークが失敗し、読み取り専用の権限拡張で成功。最初の局ID読み取りは属性としていたため空で、実構造の子要素idに直して確認した。
- ホストの`python`コマンドは存在しなかったため`python3`を使用。システムPythonのunittestはfastapi/pydantic不足でimport失敗。その後、既存`/tmp/radioflix-test-venv/bin/python`で`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend ... -m unittest discover -s backend/tests -q`を実行し、76件中66件成功・PHP CLIを要する10件skip。テスト出力のschedule警告はfixtureの異常系によるもの。
- build、TypeScript、lint、Docker build、UI実機試験は未実施。今回は製品コード変更がなく、UIも未実装であるため。PHP録音実行・本番での成功失敗・認証の実効権利は未検証であり、成功扱いにしていない。
- at spoolのホスト列挙はPermission denied。中身を取得する必要がないため回避して調査を継続した。native予約の個別内容・現在の録音ログ・Cookieは今回読んでいない。
