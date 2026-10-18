# Phase 4: 起動制御・開始前照合・公開・復旧

## 範囲と現状

今回実装したのは backend → worker の**起動制御 transport**、録音前/公開前の読み取り照合、専用保存領域への原子的公開、DBと実ファイルを用いる復旧である。実radiko音声取得bootstrapは接続していない。production serviceの `CaptureUnavailable` は `capture_ready=false` を返し、実録音受付・起動を拒否する。この区別は意図的であり、合成音声の成功を実radiko互換性の証明とはしない。

両ゲートを0のまま使う本番隔離workerの**制御・health・復旧の反映試験候補**は用意した。本番deployも、実録音も今回はしていない。実タイムフリー1本試験へは進めない。

## 起動制御 transport

既存future reservation gatewayはDocker API経由でrfriends3内の予約driverを動かす。timefreeを追加すると録音・公開・復旧と既存予約の権限が混ざるため、gatewayは変更せず `timefree-worker` 専用serviceを追加した。

- `control.py`: FastAPI/Uvicornの単一process。`/run/timefree/control.sock` だけで待受け、公開TCP portなし、Docker socketなし。
- `transport.py`: backend側のHTTP over Unix socketクライアント。固定 `/dispatch` へ32桁lowercase hexの `job_id` だけをJSONで渡す。任意URL・command・output_path・metadataを受け付けず、redirectも追従しない。
- 共有socketディレクトリは0770、umask0007。socket volumeを持つbackendと専用workerだけがアクセスする。token/secretを引数・リクエストに渡さず、資格情報の共有も増やさない。
- `POST /dispatch` はDBからjobを読み直し、実行種別・ゲート・capture準備状態を確認。正式metadataをHTTPから受け取らない。
- 通知IDは `timefree_dispatches` に永続化・重複排除し、単一loopを起床させる。workerはIDからDBを再取得して実行する。登録だけでは録音を開始しない。
- backendはcommit済みqueued jobをoutboxとして、起動直後と10秒ごとに同じIDで通知を再試行する。HTTP応答消失・どちらかの再起動でも新jobを作らない。
- 環境変数やHTTPからfixture/capture実装を指定する入口はない。試験でのみコンストラクタから合成音声を注入する。

`RFRIENDS_ENABLE_WRITES` と `RADIOFLIX_TIMEFREE_ENABLE_WRITES` の両方が1でなければ、backend通知・service受付・worker captureは拒否する。さらにcapture未準備も拒否する。今回環境値は両方0。正常系分岐は関数/コンストラクタのmockだけで検証した。OFFでもファイルの検証・DBの状態修復は行うが、captureの `run_once` は呼ばない。

## 開始直前と公開直前の再照合

`Preflight` は毎回読み取り直す。

1. job_idを検証し、DBの正式snapshotと取得済みrowが変わっていないか確認。
2. station/start/endから従来方式のbroadcast episode SHA-256を再計算。row列とsnapshotのID・局・時間の一致を確認。
3. 登録時の正式局一覧を `station_ids` に保存。native datを既存read-only parserで読み直す。局が解決できない、壊れたdat、参照先欠落ならunknownとして開始禁止。
4. native予約の局・時間重複を確認。native dat/sh/atを書き換えず、所有予約の除外もしない。
5. 通常録音/native timefreeのread-only rootを走査。既知ファイル名の局/開始/終了で重複を止める。曖昧な音声名、symlink、読み取り不能は `recordings_unknown` として止める。mtimeや題名だけで「未録音」を推測しない。
6. 他timefree jobのqueued/running/completed/unknownと既存RadioFlix recording_jobs、保存済み最新revision（存在する場合）を照合。
7. 管理領域内の出所不明ディレクトリ・自jobの既存公開先も拒否。

競合はcapture前にfailedへ遷移する。収録中に現れた競合も公開前の再照合で公開を止める。外部native処理はこのworkerのロックを共有しないため、照合直後の外部同時開始までは完全排除できない。native側を変更する共有ロックは今回導入しない。

workerの排他は出力rootではなく **DBに対応したflock** で行う。違うoutput rootを指定しても同じDBのrunning jobを別workerが横取りできない。古いjobに局一覧がない場合は開始を止める（後方互換migrationは既存jobを消さない）。

## NAS保存先と原子的公開

Composeと実コンテナのread-only mountを確認した。

- 既存通常録音: `/volume1/@home/kool-fox/radiko_public/radiko` → `/recordings:ro`
- 既存native予約: `/home/kool-fox/Share/Radio/rfriends3/data/rsv` → `/native-reservations:ro`
- 既存DB: `radioflix-reservations` named volume。backendと専用workerで共有する。
- 新しい公開候補: `/volume1/@home/kool-fox/radiko_public/radioflix-timefree` → worker `/timefree`、backend `/timefree:ro`
- native timefree参照候補: `/volume1/@home/kool-fox/radiko_public/timefree` → worker `/native-timefree:ro`

新しい公開候補ディレクトリは今回作成・書込していない。反映前に存在・owner/permission・共有DBのアクセス権・NAS filesystemのrename/fsync対応を確認する。専用Composeはそのためのレビュー候補であり、実行許可ではない。

`Publisher` の手順:

1. 固定管理root内の `.staging/<job_id>-<random>/` に音声をコピーする。
2. WAVヘッダー・実データ量・予定時間との差（2秒以内）・サイズ・SHA-256を検証する。
3. broadcast、execution_kind、ランダムpublication_id、hash/size/durationを含むmanifestを作り、音声/manifest/親ディレクトリをfsyncする。
4. 同じmanifestをDBの `timefree_publications` に公開intentとしてcommitする。
5. Linux `renameat2(RENAME_NOREPLACE)` でディレクトリごと `<job_id>/` へ原子的に移動し、rootとstagingをfsyncする。
6. 最後にDBをcompletedへcommitする。

完成音声とmanifestは同時に現れる。空ディレクトリとの衝突も上書きしない。RENAME_NOREPLACE非対応なら失敗し、上書き可能なrenameへfallbackしない。名前はjob_idで固定し、番組名やクライアント指定pathを利用しない。symlink/特殊ファイル/管理root外を拒否する。途中ファイルは `.staging` に留まり、読み取り側の `completed_assets` は検証済み完成jobしか返さない。

今回のNAS試験は `/volume1/@docker/volumes` 下の**専用テストvolume**だけを使い、通常録音領域はマウントすらしていない。本番公開候補そのもののfilesystem受入は次段階で行う。

## 復旧

専用service起動時・周期確認・次job実行前に、排他ロックを取得してreconcileする。生存中workerがロックを持っていれば触らない。経過時間やPIDの推測で再実行しない。

| 状態 | 処理 |
|---|---|
| worker実行中に停止 / DB running・processなし | completedの証拠がなければunknown、自動再録音なし |
| backend再起動 | queued IDの通知再開。completedのGETも実ファイル検証し、不整合を即unknown表示 |
| 公開rename直前で停止 | hidden stagingを保持、unknown。自動公開しない |
| 公開後・completed commit直前で停止 | DB公開intent・最終manifest・実音声・snapshotが完全一致した時だけcompleted復旧 |
| tempだけ残る / orphan temp | 保存・非公開。削除も昇格も自動でしない |
| outputあり・DB未completed | 自jobの公開intentがあり内容検証できた場合だけ復旧。既存の他ファイルを取り込まない |
| DB completed・output欠落/破損/列不整合 | unknownへ。backendの読み取りもcompletedを返さない |
| DBのpath等だけ不整合・元の音声は検証可能 | unknown後、元のintentと音声に基づいて正式な列を再設定できる |

read-onlyのbackendは成果物を書かず、DB修復も専用workerに任せる。Phase 5の一覧/再生API合流は今回対象外。音声取得側が実形式を増やす際は、WAV以外の検証を追加して同等の試験を行う必要がある。

## 隔離検証と再実行

`backend/tests/test_timefree_runtime.py` はtransport正常/不正ID/注入、native unknown/競合、既存音声/他job/RadioFlix録音、atomic publish、空ディレクトリ衝突、hidden staging、実SIGKILL、再起動、orphan、完成不整合、gate OFF、native/通常録音不変を検証する。既存 `test_timefree.py` とPhase 1〜3テストも維持した。

全backend試験は `rfriends3-rfriends3:latest` 内のPython3.12とPHPを使い、network none・read-only・UID1000・cap-drop ALLで実施する。Python依存wheelを事前に/tmpへ用意する。テスト中は依存取得も外部通信もしない。

```sh
# backend/tests、依存ディレクトリ、ハッシュ固定したPHPソースはread-only mount。
# /test-output は今回作る空のテスト専用named volumeだけ。
# 実行前にテストvolumeをUID1000が書けることを確認する。
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/deps:/code \
RFRIENDS_ENABLE_WRITES=0 RADIOFLIX_TIMEFREE_ENABLE_WRITES=0 \
RADIOFLIX_TIMEFREE_TEST_PHP='["php"]' \
RADIOFLIX_TIMEFREE_TEST_SOURCE=/sources \
RADIOFLIX_TIMEFREE_TEST_OUTPUT=/test-output \
python3 -m unittest discover -s /code/tests -q
```

本番同等Python3.14の専用review imageは別途ビルドし、tmpfsだけをマウントしてhealth/ゲートOFF/DB未作成を確認する。既存4コンテナはinspectのみ。最終結果と前後比較は `docs/dev-log/latest.md` とhistory参照。

## rfriends3 bootstrap source audit（2026-10-16）

稼働中 `rfriends3` の `/home/user/rfriends3/script` から対象sourceを読み取り専用で取得し、fingerprintを確認した。既存fixture manifestの `rf_timefree.php` / `rf_downloader.php` は稼働中sourceと一致した。追加候補sourceと用途・hash・関数名は `backend/radioflix/timefree/bootstrap-source-manifest.json` に固定した。候補は次の6ファイルに限定し、manifest不一致は失敗させる。

| source | 対象関数 | 理由 |
|---|---|---|
| `script/rf_timefree.php` | `timefree_kwrec_ex`, `timefree_check`, stream URL helpers | timefree処理 |
| `script/rf_downloader.php` | `rfriends_downloader` | 既存取得・変換・保存処理 |
| `script/rf_radiko.php` | `rfriends_auth_radiko` | 認証 |
| `script/rf_gateway_def.php` | `rfgw_ffmpeg_opt` | ffmpeg option生成 |
| `script/rf_common04.php` | `get_para`, `get_fnam`, `fnam_edit` | 予約metadata/filename helper |
| `script/rf_common.php` | `rf_movefile` | downloader file move helper |

既存処理をそのまま呼べる安全な境界は確認できなかった。`timefree_kwrec_ex()` は入力queue fileを最後に削除・再作成し、cancel marker時にprocessを `exit` する。`rfriends_downloader()` は多数の設定globalを必要とし、shell文字列でffmpegを実行し、通常録音directoryへのmove、通常録音後処理・transfer hookを呼ぶ。汎用retry branchもあるが、通常の `ex_timefree` typeでは条件上実行されない。timefree stream/auth関数の依存全体と、CLI初期化なしで使える設定契約も未確認である。batch functionを隔離queueへ向けるだけでは副作用を閉じられず、downloaderをshell/API境界の安全な下位処理へ分けるか、rfriends側に検証可能なargument-based library APIが必要となる。

`bootstrap.py` とbootstrap source manifestを追加し、source allowlist/hash検証、job/pathのfail-closed判定、二重gateのOFF時拒否を用意した。secretは存在・型だけを検査する設計で内容は読まない。現時点の `ProductionBootstrap.ready` と `bridge_approved` はfalse固定で、PHPを起動せず、上記source関数も呼ばない。これはproduction capture bootstrap完成ではなく、未承認source bridgeを実行不能に保つpreflight境界である。fixture runnerは引き続き合成WAVとfake auth/downloaderのみを使用する。

## Capture dependency graph audit（2026-10-16、read-only）

現行稼働中rfriends3 sourceをread-onlyで追跡した。以下は関数間の実行経路であり、RadioFlixから呼び出してよいという意味ではない。

```text
RadioFlix job metadata
  └─ timefree_kwrec_ex()                         [C: 呼ばない]
       ├─ queue file読取・削除・再作成、cancel markerでprocess exit
       └─ rfriends_downloader(ex_timefree, ...)
            ├─ rfriends_auth_radiko() → rf_auth()
            │    ├─ normal / auth-mode2 / auth-mode3 / premium auth helpers
            │    └─ rf_wget() → external_program() → system(command string)
            ├─ get_timefree_stream_url*()
            │    ├─ wget command string → external_program() → system()
            │    └─ temp URL/playlist file write/read/cleanup
            ├─ rfgw_ffmpeg_opt() → option string + config/global依存
            ├─ external_program("$expgm $opt $recfiletmp.$dwn")
            │    └─ bindir + command string → system()
            ├─ optional ffmpeg conversion command string → external_program()
            ├─ get_recdir(ex_timefree) → configured timefree/normal recording root
            ├─ fnam_edit() → configured output name
            ├─ mkdir / rf_movefile(copy, sleep, unlink) → recording rootへ保存
            └─ rec_file_check(), logging, rftrans_job()等の通常録音後処理
```

`rfriends_downloader()` は多数のglobal/config値（tmpdir/cfgdir/usrdir、録音先、拡張子、認証・地域、proxy/header、録音状態、ログ等）を参照する。認証・playlist/HLS・ffmpegのコマンド文字列を作る層が `external_program()` に集まり、同関数は `system()` を実行する。入力値をargvとして渡すAPIではない。固定作業dirを指定しても、通常保存先へのmove、ファイル管理、後処理hookは残る。汎用 `rf_rsv_retry()` 呼び出しは `ex_radiko` / `ex_radiru` 条件であり、通常の `ex_timefree` 経路では呼ばれない。

| 分類 | 関数/層 | 判断 |
|---|---|---|
| A: 入出力を伴わず再利用可能 | `get_radiko_streamurlhls_sel()`、`rf_radiko_make_rectime*()` | XML選択・時刻表現の限定的helper。音声取得境界ではない。 |
| B: 明示的path/config注入が成立する場合に限る | `get_recdir()`、`fnam_edit()`、`calc_timefree_timeout()`、`rf_diff_timefree()` | global/config依存または環境時刻依存。単独helperとして扱える余地はあるが、downloaderの安全化を提供しない。 |
| C: bridgeから直接利用不可 | `timefree_kwrec_ex()`、`rfriends_downloader()`、`rfriends_auth_radiko()`/`rf_auth()`の現行orchestrator、`get_timefree_stream_url*()`、`rf_wget()`、`external_program()`、`rfgw_ffmpeg_opt()`、`rf_movefile()`、`rftrans_job()` | queue/process/secret/network/file/global/shell/output副作用がある。コマンド文字列・通常保存先・共通後処理を閉じられない。 |

認証と音声取得に必要な処理を、現行sourceだけで「固定実行ファイル＋argv配列＋RadioFlix専用temp/output」に閉じる下位APIは確認できなかった。特に `rfriends_downloader()` から下位helperだけを呼んでも、現行radiko auth/HLS helperが `rf_wget()` / `external_program()` に戻る。CLIの `rf_inc.php` 初期化はさらに予約・共通処理・設定群を読み込むため使えない。したがって結論は **安全に直接再利用できる境界なし**。bootstrap/manifestの候補登録は実行許可ではなく、既存 `ProductionBootstrap.ready=false` を維持する。

将来接続するには、rfriends側に副作用を持たないauth/playlist/HLSライブラリAPIとargv型の取得実行APIを追加し、そのAPIに必要なsourceだけを固定fingerprintで束ねる必要がある。これは今回禁止されたrfriends3変更に当たり、実施していない。現行 `docker-compose.timefree.yml` はPython-onlyかつ `network_mode: none` であり、本番capture serviceとして完成扱いにしない。PHP runtime/source/secret/限定egressを設計・起動する段階にも進まない。

本番候補 `docker-compose.timefree.yml` はPython専用imageで、PHP runtime・rfriends source bundle・radiko credential fileを提供せず、`network_mode: none` でもあるため、実radiko接続を行うworker Composeとして未完成である。今回Compose変更やdeployは行っていない。次の設計では安全なCLI-free source boundaryと最小source bundleを確定してから、read-only source/secret mount・非root PHP runtime・timefree専用write root・radiko限定egressを別サービスにする。二重gateは維持する。
