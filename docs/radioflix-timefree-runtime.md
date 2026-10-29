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

## Safe Capture Adapter（fixture専用）

2026-10-19、jobから音声検証までのRadioFlix側境界を追加した。`capture_job(job_id)` はjob IDだけを受け、storeから正式rowを再取得し、snapshotのBroadcast、episode SHA-256、station、timezone付きstart/end、state、期限、重複、必須preflightを再検証する。任意出力先やコマンド文字列を受け取らない。書込みは `managed_root/.staging/capture-work/<job_id>-<random>/` のみに導出し、一時workspaceはcontext終了時に削除する。workerは結果を既存のpublisherへ渡し、公開前にもWAV実データ・予定時間・native/duplicate preflightを確認する。

上位処理の境界は次のとおり。各portはfixtureで置換可能だが、Adapter本体の順序・metadata検証・path検査・音声検証は共通である。

```text
DB row by job_id → metadata/eligibility/duplicate/preflight
  → Authenticator → PlaylistProvider → MediaFetcher
  → AudioTranscoder → audio_info(WAV + byte count + duration)
  → existing worker Publisher
```

現行rfriends3 sourceから抽出した仕様は、認証mode（通常、mode2/3、premium）の選択が設定に依存すること、stationと開始/終了（時間境界・余白を含む）からタイムフリーplaylistを解決すること、HLS playlist/segment取得時に認証情報・地域情報を使うこと、tf30経路では概ね300秒単位で分割してplaylistを連結すること、playlist終端/時刻情報を検証すること、ffmpegで音声へ変換し出力を確認すること。認証資格情報・area/tokenの値はログやmanifestへ出さない。現行helperはwget/`external_program()`のshell文字列経路へ戻るため、この仕様をHTTP/HLS実装として移植してはいない。

現行sourceを仕様として読む際の入力・順序・取得値・停止条件は次のように整理した。厳密なHTTP status/retry matrixや、全auth modeごとのwire contractは既存のshell/global依存から安全に確定できないため、production contractとしては未確定扱いにする。

| 順序 | 必要な入力 | 取得/生成する値 | 開始を止める条件 |
|---|---|---|---|
| 1. job確認 | job_idからDB取得したepisode id、station、timezone付きstart/end、期限、実行状態 | canonical episode fingerprint、予定秒数 | job/state不正、日時不整合、期限切れ、duplicate/native preflight不明 |
| 2. 認証 | station/timefree利用条件、既存設定が選ぶ認証mode、secret source | 認証contextと地域/area情報 | 設定・secret欠落、認証失敗、想定外応答。credential値は返却値のrepr/logへ含めない |
| 3. playlist | station、開始/終了時刻、既存仕様の時間余白、認証context | HTTPS HLS playlist参照、必要な時刻/segment情報 | HTTP/parse失敗、空/不正playlist、時間範囲と合わない応答 |
| 4. media | 検証済みplaylist/segment参照、認証context | RadioFlix workspace内のmedia input | host/scheme不許可、playlist終端不正、segment欠落、timeout/byte上限超過 |
| 5. audio | 固定ffmpeg実行ファイル、workspace内media input、予定秒数 | WAV成果物 | ffmpeg非zero/timeout、音声streamなし、zero/truncated/予定時間不一致 |
| 6. publish | 検証済み成果物とDB job | 既存publisherのatomic公開manifest | 再照合不一致、衝突、成果物fingerprint不一致 |

この表は既存処理の観察をRadioFlix側の安全契約に翻訳したもの。表にあるHLS host/size policyやretry上限をrfriends3が保証しているという主張ではなく、production adapterを作る際に新たに実装・検証する必須条件である。

| 境界 | fixtureでの実装 | 将来productionで必要な契約 |
|---|---|---|
| auth | `FixtureAuthenticator` が固定fixture contextを返す | secret fileを読み、秘密値をrepr/log/argvに出さず、指定station/期間向け認証contextを返す。現在はNotReady |
| playlist | `FixturePlaylistProvider` が `fixture://` URIを返す | HTTPSの許可hostのみ、station/start/endと認証contextからplaylistを取得し、redirect/URL/hostを検証する。HTTP clientは未実装 |
| media | fixture bytesを書き込む | HLS URI/segment/byte/time limits、bounded retry、connect/read/overall timeout、許可host egressを実装する。現行wget helperは使わない |
| ffmpeg | `SyntheticAudioTranscoder` でWAVを生成 | ffmpeg固定pathまたはpreflight確定path、argv list、`shell=False`、固定cwd、protocol allowlist、非同期停止可能なtimeoutを使う |
| audio | `audio_info` でWAV、実byte数、durationを確認 | codec/container許可、期待時間許容差、最大byte数、truncation/zero-byte拒否を保つ |

`FfmpegArgvTranscoder` は将来向けのshell-free境界だがproduction経路には未接続。固定 `/usr/bin/ffmpeg` または `/usr/local/bin/ffmpeg`、あるいは明示的にpreflightから渡された実体path以外を拒否し、argv配列のみで `subprocess.run(..., shell=False)` を呼ぶ。呼出元がexecutable/commandをmetadataから指定する入口はない。試験では `subprocess.run` をmockし、ダミー実行ファイルを実行していない。

production adapterは `ProductionCaptureAdapter` のinterfaceだけで、`ready=false` / `bridge_approved=false`、認証・HTTP・HLS portなし、capture呼出しは常にNotReady。両gateがONでも本実装を起動しない。fixture modeはコンストラクタでのみ注入し、環境変数・APIからproduction/fixture portを切り替える機能はない。production化には、secret mount、allowlisted HTTPS egress、HTTP/HLS/segment総時間・サイズ制限、bounded retryと再試行可能性、認証/playlist/media/ffmpeg/audio/preflightのstructured error mapping、ffmpegのresource limit、egress監査が必要。現時点のworker serviceはnetwork noneであり、本adapter fixtureが通ってもproduction capture準備完了を意味しない。

## Safe Source API fixture reference（2026-10-20、wire read-only follow-up 2026-10-21）

現行rfriends3 HTTP処理のfingerprint照合結果、確認済みauth/timefree/HLSフロー、確定できなかったwire詳細、fixture source boundary、URL/secret/retry/error policyは [`radioflix-timefree-source-api.md`](radioflix-timefree-source-api.md) に記録した。read-onlyのactive config確認では `radiko_auth_mode=0`。endpointのsource-defined host/pathとmode別処理も追記したが、effective `hls_type`、premium branch、timeout/retry/redirectの実効値は未確定。実requestは行っていない。これはfixture-only contractであり、production HTTP transportはNotReady。
## Production wire audit update (2026-10-23)

The current source/config audit establishes radiko_auth_mode=0 and source-default hls_type=0. Normal mode-0 auth is auth1→auth2, but the per-capture mode argument comes from rf_premium_mode() and may select premium auth. The timefree-specific downloader case sets tf30=1 unconditionally and uses the 300-second tf30 helper; the standard primary-playlist POST body flash=1 helper is not used on this call path. The numeric premium selectors are premium=1, premium_areafree=1, premium_timefree30=0; product status/effective auth mode remains unresolved.

No PHP helper, shell helper, HTTP request, DNS lookup, HLS request, or recording was run. --no-check-certificate, unbounded/unknown redirect policy, request bounds missing on the direct tf30/PHP HLS path, and account/product-dependent normal-vs-premium auth remains unresolved; these facts remain reasons not to implement a production transport yet.

A further read-only extraction of non-secret option names/numeric values established mode-0 auth1 wget bounds (-t 10, -T 5, connect-timeout 5, waitretry 5) and auth2 retries (-t 5). Those flags are not used by the direct timefree playlist/tf30 wget commands or PHP HLS stream reads. The generic tf30 predicate/age condition does not govern the explicit timefree case, which hardcodes the tf30 helper. The effective auth mode still depends on unresolved rf_premium_mode()/product status. See the source-api audit for exact scope and remaining blockers.

## 2026-10-24 limited Radiko wire observation

Before network activity, a read-only snapshot confirmed backend `RFRIENDS_ENABLE_WRITES=0`, Timefree gate unset/OFF, active RadioFlix reservations=0, weekly subscriptions=0, and no `timefree_jobs` table (no active Timefree jobs). `rfriends3` was running without a healthcheck; process-name enumeration showed no ffmpeg/wget process. The sole native `.dat`/`.sh` pair and `atq` output fingerprints were unchanged after the observation. The at queue showed one future 2026-10-25 02:55 job and one stale 2026-10-04 00:05 entry. No queue or reservation operation was performed.

DNS and verified TLS handshakes only were first performed for `radiko.jp` and the two source-configured timefree playlist hosts; all resolved to public IPv4 and passed hostname/certificate validation. Then an in-memory-only HTTP probe fetched `playerCommon.js` and performed the normal mode-0 auth1/auth2 exchange. auth1 returned 200; auth2 returned 401. Only request/response header names, status, content type/length, timing, and host/path shape were emitted. Token, partial-key, cookie, response body content, and account data were not logged or saved. No playlist/HLS/segment request, ffmpeg, audio file, publisher, worker deploy, or gate change occurred.

Because auth2 was rejected and the account/product-dependent capture branch remains unresolved, Production HTTP remains unimplemented and NotReady. Do not retry auth or proceed to playlist without resolving the 401 and effective mode safely.

## 2026-10-24 one-segment observation

Following the successful normal `pc_html5` authentication and manifest observations, one segment was fetched from the same in-area five-minute item. The media manifest had three entries, no `ENDLIST`, and no encryption key or init map. Only the first segment was requested: HTTP 200, `application/octet-stream`, 31,707 bytes, about 0.09 seconds, valid AAC ADTS framing. The sole file was in a temporary test workspace and was removed after validation. No ffmpeg, concatenation, publisher, complete program, or recording ran. Native reservation/queue fingerprints and the running rfriends3 container were unchanged.

The source package now has a pinned-TLS standard-library HTTPS transport and `ProductionMediaFetcher`, but both are observation/fixture building blocks only: `ProductionHttpTransport.ready=false`, `ProductionMediaFetcher.ready=false`, `ProductionCaptureAdapter.ready=false`, and `bridge_approved=false`. Live network use requires an explicit short-lived observation-mode budget; default construction remains NotReady. Media fetching has a hard 1–3 segment ceiling and is not wired into the capture worker. No production service or Compose deployment was changed.

## 2026-10-24 bounded live ffmpeg attempt stopped

The authorized normal-auth test used the previously confirmed in-area CRK five-minute item and the bounded media fetcher (hard maximum three segments). Authentication succeeded, the media fetch returned, and ffmpeg exited zero. The output then failed the internal WAV validation with `ffmpeg_output_invalid`. The diagnostic printed no WAV properties before failure; its `finally` removed the test workspace, so exact output size/duration and exact per-request segment metrics are unavailable. No retry or second live request was made. No publisher, catalogue, recording, deploy, gate change, or native write occurred. Treat the production transcoder integration as unverified and stop before any program recording.

## 2026-10-25 offline WAV failure diagnosis

The failed live WAV was deleted by the prior test's cleanup and was not requested again. The old validator's single `ffmpeg_output_invalid` mapping covered: non-regular/symlink output; size at or below 44 bytes or over the cap; RIFF/WAVE/fmt/data parse failures raised by Python `wave`; compressed WAV; non-16-bit PCM; sample-rate mismatch; channel count outside 1–2; and zero frames. Duration mismatch was separately `ffmpeg_duration_mismatch`. The old implementation did not independently prove that the declared PCM payload was physically present.

An internal, non-sensitive `_wav_diagnostic()` now classifies RIFF/WAVE/fmt/codec/data/truncation/size/alignment/sample-rate/zero-payload/sample-count failures while the external capture error remains `ffmpeg_output_invalid`. It walks RIFF chunks and verifies declared bounds, PCM block alignment, data length, and frame count; unknown chunks before or after data and extra fmt bytes are accepted. `_ffprobe_wav()` is a bounded argv/`shell=False` diagnostic helper for isolated tests only; capture does not depend on ffprobe.

Network-none fixtures using local ffmpeg passed for AAC-LC mono/stereo at 44.1/48 kHz and 1/2/3 inputs, including a varied complete-frame boundary and ID3 prefix. ffprobe reported the expected WAV/PCM properties for the synthetic output. A WAV fixture with JUNK/LIST/fact/extended fmt/unknown chunks around data passed; zero, truncated and invalid-alignment fixtures were rejected. These cases did not reproduce `ffmpeg_output_invalid`; therefore A (bad ffmpeg output), B (validator false rejection), C (real ADTS-specific ffmpeg condition), and D (multi-segment duration/format interaction) remain unclassified. No argv, concat, or duration policy change is justified. No live request or real segment test was performed. See latest dev-log for the stop condition and targeted test results.

## 2026-10-25 bounded ffmpeg diagnostic retry stopped at playlist

The user-authorized single diagnostic used the previously observed in-area CRK item (2026-10-24 18:55–19:00 JST), ordinary `pc_html5` auth, a network-enabled ephemeral test container, and no production/native mounts. ffmpeg `-version` preflight passed before network activity. `playerCommon.js`, auth1, and auth2 each returned HTTP 200 from `radiko.jp`, with no redirects. The fixed timefree playlist POST to `radiko.jp` returned HTTP 404, `text/html`, 146 bytes, with no redirect. The probe did not log its query, headers, or body. It stopped at that response; no alternate endpoint or second request was attempted.

No HLS manifest/segment was fetched, no media file was created, no ffmpeg media conversion or ffprobe ran, and the AudioTranscoder validator was not reached. The isolated workspace was empty and removed; diagnostic driver/temp files were deleted. The prior `ffmpeg_output_invalid` cause therefore remains unclassified (A–F). This single attempt identifies a playlist-contract/endpoint discrepancy for the current diagnostic construction, but does not establish why the earlier WAV was rejected. Do not infer a fix or retry another endpoint without a separate scope. Both gates remained OFF; readiness flags remain false; publisher, full recording, deploy, and native operations were not used. Native dat/sh aggregate and atq count/fingerprint matched the pre-test snapshot.

## 2026-10-26 timefree playlist path correction

The earlier diagnostic used the generic standard-program playlist POST and received 404. Current rfriends3 timefree code instead GETs station stream XML at `https://radiko.jp/v3/station/stream/pc_html5/{station}.xml`, selects the unique URL whose `areafree="0"` and `timefree="1"` match the ordinary in-area job, then GETs that `playlist_create_url` with the tf30 query (`station_id`, `start_at`, `ft`, `end_at`, `to`, `preroll=0`, `seek`, `l=300`, random `lsid`, `type=b`). `playlist.py` now implements that path and rejects XML ambiguity, unexpected Smartstream host/path, unsupported area mode and intervals over five minutes. Auth token and area ID are headers in the media source; query strings contain no auth material. Fixture verification passes; bounded live revalidation is pending the separately documented safety snapshot. No segment, ffmpeg, publisher or native operation is implied by the fixture result.

## 2026-10-26 bounded playlist-path observation stopped at XML selection

Offline correction tests passed, but the one live attempt did not reach the Smartstream GET. Normal auth succeeded (auth1/auth2 200). Station stream XML GET returned 200, `application/xml`, 1,317 bytes, no redirect, matching station identity and eight URL nodes. Two nodes matched `areafree=0,timefree=1`, so the current single-candidate selector correctly failed closed with `PLAYLIST_INVALID` rather than choosing arbitrarily. A separate structure-only scan showed additional XML hosts outside the existing exact host allowlist (`dr-wowza.radiko-cf.com`, `si-c-radiko.smartstream.ne.jp`, `si-f-radiko.smartstream.ne.jp`). No unknown host was approved. No playlist/master/media request, segment download, media ffmpeg conversion, ffprobe, WAV creation, validator run, publisher, or recording occurred. The previous `ffmpeg_output_invalid` cause remains unclassified. The observation workspace was empty and removed.

Before/after state remained safe: both write gates OFF (Timefree unset), active RadioFlix reservation/weekly/recording counts 0 and no timefree table, `rfriends3` and the four RadioFlix production containers Up, no active ffmpeg/wget process. Native dat/sh count/fingerprint stayed 18 / `4273a770b11450c4835e20be446634dfe55f8edb08379df346306950d1f15953`; atq count/fingerprint stayed 10 / `8cb925613dd77e30264aa91a8828c4c3c8bab10be0339e839078625eef706dc8`. `ready=false` and `bridge_approved=false` remain. Stop before any further Radiko request until the current native selector's multi-candidate policy and the observed XML host set are reviewed and explicitly bounded.

## 2026-10-26 multiple stream candidate policy (offline only)

`TimefreePlaylistSource` now evaluates only XML entries matching the job's fixed `areafree=0,timefree=1`, preserves their XML order, and selects the first URL that passes the existing exact HTTPS host/path allowlist. Unknown or malformed candidates are marked unapproved and skipped; they are never contacted or used as fallback. Diagnostic metadata is restricted to candidate index, approval state, sanitized hostname, scheme and path, with no query or URL value. If there is no approved candidate, it remains fail-closed. New offline fixtures cover first/second ordering, multiple approved entries, duplicate URL/host and malformed/private/userinfo/path cases. The live XML has not yet been requested using this updated selector.

## 2026-10-26 approved-candidate live check and WAV stop

With the updated allowlist-only XML policy and all offline tests passing, a single normal-auth observation fetched the CRK stream XML. Two nodes matched `areafree=0,timefree=1`: the first contained the approved `tf-f-rpaa-radiko.smartstream.ne.jp` `/tf/playlist.m3u8` URL and was selected; the second had no usable URL. Nonmatching unapproved XML hosts were ignored and never contacted. No allowlist was expanded and no fallback was attempted.

The selected playlist GET returned 200 (`application/x-mpegurl`, 195 bytes, no redirect), master 200 with one variant, and media manifest 200 on the same host (`application/x-mpegurl`, 10,256 bytes, no redirect). The manifest listed 60 approved-host segment references. Two segments only were retrieved: 31,707 and 30,930 bytes, `application/octet-stream`, valid AAC ADTS, each 5.034667 seconds by frame parsing and 5.035 seconds by EXTINF. No other segment was fetched.

Production `FfmpegArgvTranscoder` exited 0 in 0.597 seconds with empty stderr (0 bytes) and produced a 1,933,390-byte WAV. ffprobe reported WAV/PCM signed 16-bit, 48 kHz, stereo, 10.069333 seconds. The internal validator returned `UNEXPECTED_SAMPLE_RATE`, mapped externally to `ffmpeg_output_invalid`. This invocation did not preserve the ADTS-derived expected sample rate or RIFF chunk details in its failure record (the diagnostic's info object was empty on that early return). The immediate sample-rate mismatch is established; whether it came from concat/ffmpeg resampling or a validator contract issue is not. No fix and no extra Radiko request was made. Segment/WAV/temp files were removed after the available diagnostics.

Pre/post safety values were unchanged: both gates OFF, active RadioFlix reservation/weekly/recording counts zero and no timefree table; native dat/sh 18 with fingerprint `4273a770b11450c4835e20be446634dfe55f8edb08379df346306950d1f15953`; atq count 10 with fingerprint `8cb925613dd77e30264aa91a8828c4c3c8bab10be0339e839078625eef706dc8`; no active ffmpeg/wget. The four RadioFlix containers and rfriends3 remained Up. `ready=false`, `bridge_approved=false`; no publisher, full recording, deploy, or native write occurred.


## 2026-10-28 AAC decoded sample-rate contract

The previously retained one-segment diagnostic was reused locally; no Radiko request was made. The ADTS parser reads the frame sampling-frequency index as a 24,000 Hz AAC core rate (118 frames; 5.034667 s). A bounded local `ffprobe` of that same AAC/ADTS file reports AAC-LC, 48,000 Hz decoded rate, stereo, 4.894063 s. The production transcoder's argv has no `-ar`, `-ac`, or resampling filter; ffmpeg exits 0 and produces PCM16 WAV at 48,000 Hz, stereo, 5.034667 s, 966,734 bytes. RIFF is `fmt `, `LIST`, `data`; PCM fmt is 16-bit, byte rate 192,000, block align 4; data offset 78, declared and actual data bytes 966,656, 241,664 sample frames.

An earlier two-segment run reported `UNEXPECTED_SAMPLE_RATE`, but it did not retain input ffprobe data, the validator's expected rate, or RIFF diagnostics. Later analysis proposed that the ADTS core rate may have been compared with the decoded PCM rate; that explanation was not proven by the failed run. A separate fresh one-segment run passed with decoded input rate, expected rate, WAV header rate, and validator rate all at 48,000 Hz. That successful run does not establish the cause of the older failure, which remains unconfirmed and was not reproduced. Current transcoder code obtains a bounded input decoder rate from allowlisted sibling `ffprobe` using argv/`shell=False`; WAV validation remains strict. This describes current behavior, not a confirmed retrospective repair.

Using a saved segment in a later, separate diagnostic, ffmpeg 7.1.1-Jellyfin exited 0. Output ffprobe reported WAV / pcm_s16le / s16 / 48,000 Hz / stereo / 5.034667 s / 966,734 bytes; RIFF diagnostics returned no reason and `_validate_wav()` passed with expected rate 48,000 Hz. Synthetic 44.1/48 kHz mono/stereo and 1/2/3-segment tests also pass. The older rejected run remains unclassified because its input/expected-rate evidence was not retained. The later one-segment run itself is classification E (normal PASS); it does not prove the older cause.

A diagnostic wrapper initially failed before invoking the validator due to a wrong ffprobe copy path. The available WAV was independently inspected and a later segment run passed. This evidence does not identify the cause of the older `UNEXPECTED_SAMPLE_RATE` result.

## 2026-10-28 fresh single-segment sample-rate confirmation

A fresh one-segment observation used the ordinary `pc_html5` route and only the previously approved Smartstream host. Seven bounded HTTPS requests completed with HTTP 200 and no redirects: player JS, auth1, auth2, station stream XML, playlist-create response, media playlist variant, and one segment. XML still had two matching candidate entries; the first approved candidate was selected, and no unapproved host was contacted. The segment was 31,707 bytes, `application/octet-stream`, AAC ADTS, with `EXTINF=5.035` seconds.

Before ffmpeg, local ffprobe reported AAC / HE-AAC, 48,000 Hz decoded rate, stereo, duration 4.894063 s. The ADTS parser separately reported its 24,000 Hz core rate, 118 frames, and 5.034667 s frame-derived duration. These rate values describe different AAC rates; the decoder rate was the PCM input contract. `EXPECTED_SAMPLE_RATE=48,000` was set from the bounded `_probe_aac_sample_rate()` result before conversion, and `INPUT_SAMPLE_RATE == EXPECTED_SAMPLE_RATE`; therefore conversion proceeded. The previous diagnostic's AAC-LC profile label is corrected: this fresh ffprobe explicitly identifies HE-AAC.

The production AudioTranscoder ran shell-free with one AAC input, fixed PCM16/WAV output, and overwrite disabled; exit=0 in 0.191 s, no stderr. Output ffprobe: WAV / pcm_s16le / s16 / 48,000 Hz / stereo / 5.034667 s / 966,734 bytes. RIFF chunks: `fmt `, `LIST`, `data`; fmt sample rate 48,000, block align 4; declared and actual data payload 966,656 bytes; 241,664 frames. `WAV_HEADER_SAMPLE_RATE=48,000`, `VALIDATOR_ACTUAL_SAMPLE_RATE=48,000`, internal reason=None, validator PASS. Classification for this run is E (normal PASS); the prior rejection is explained by the corrected expectation source, not an ADTS parse or WAV parse error.

The test segment and generated WAV were removed after ffprobe, RIFF diagnostics and validator completed. No publisher, recording catalogue, or worker was used. Read-only native fingerprints exactly matched before/after: rsv 10, dat/sh 76, atjobs 7, atspool 2, atq 6; target native overlap remained zero. Both gates remained OFF, `ready=false`, `bridge_approved=false`, active-like RadioFlix reservation/weekly/recording rows remained zero, no `timefree_jobs` table exists, and production services remained Up. This was a bounded source/transcoder diagnostic, not a program recording.

## 2026-10-28 isolated whole-program E2E preflight stopped

The bounded JP13 guide scan returned HTTP 200 for seven radio dates (2026-10-21 through 2026-10-27) and identified 271 ended, timefree-eligible 180–300 second entries with the required metadata flags. None overlapped the five parsed native reservations. The source/recording conflict gate then stopped every candidate: the existing ordinary-recordings root has 590 audio files, of which one filename is outside the strict known recording format; the native-timefree root has 371 audio files, all parseable. Existing `RecordingInventory` correctly maps the ambiguous ordinary file to `recordings_unknown`, so no candidate was selected. Its basename was not recorded. The remaining uncertainty means a duplicate cannot be ruled out safely.

The final diagnostic attempt made seven public guide GETs only. Across four complete guide scans after harness startup fixes, 28 guide GETs returned 200 (seven per scan); no station stream XML, auth1/auth2, playlist, HLS, segment, or audio request followed the inventory block. No segment, WAV, test job DB row, publisher output, or recovery action was created. `ready=false`, `bridge_approved=false`; both production gates remained OFF. No production DB, normal recording root, publisher root, native reservation, dat/sh/at spool, container, or worker was written/restarted/deployed.

The isolated ffmpeg/ffprobe version probe passed in a network-none read-only non-root container. The full backend/frontend suite was not run because E2E did not pass its duplicate-inventory preflight; no repository code changed. The older multi-segment `UNEXPECTED_SAMPLE_RATE` remains cause-unconfirmed; the separate recent one-segment run passed but does not prove the older failure was fixed.

## 2026-10-28 unresolved ordinary recording filename resolved

The only filename rejected by the strict inventory parser was `[SHT]LFR_霜降り明星のオールナイトニッポン_20261010_0102_0300.m4a`. Read-only metadata: regular file, not symlink, 344,411 bytes, mtime 2026-10-10 01:10:09 JST. The extension was already supported; parsing failed because the station field was prefixed by the exact `[SHT]` short-recording marker. The filename encodes station `LFR` and the conservative scheduled interval 2026-10-10 01:02–03:00 JST. No same-stem sidecar was present; mtime was not used to infer recording time.

A one-file copy in `/tmp` was probed in a disposable `--network=none`, read-only-root container with only that file mounted read-only. It is MP4/M4A with AAC HE-AAC, 48 kHz, stereo, 29.781333 seconds, and an MJPEG cover-art stream. The short media duration is not substituted for the filename schedule interval, so the whole 118-minute window continues to block overlapping jobs. The temporary copy was removed. Classification: the supported rfriends status-prefix naming form; audio stream is valid but short relative to the named schedule range.

`RecordingInventory` now parses only the existing canonical format plus the exact `[SHT]` prefix. Unknown markers, malformed dates, symlinks, and ambiguous audio still fail closed. An isolated read-only scan of the recording root found 590 total audio files: the previous 589 parse results were byte-for-byte equivalent in station/start/end values; only the `[SHT]` file was added. Result: 590 known, 0 unresolved, 0 parser errors, 0 symlinks/walk errors. The file remains present and unchanged.

Offline tests passed: inventory 14; inventory/runtime/timefree/bootstrap 78. Full backend discovery before the final added inventory case ran 313 tests: 311 passed, 2 synthetic ffprobe tests errored with `ffprobe_timeout` in the recovery PHP test image; no skips. After the final parser guard and 14th inventory test, the focused inventory/runtime/timefree/bootstrap suite passed 78 tests; full discovery was not repeated. Frontend schedule 148, reservation 24 scenarios, playback/navigation 21, typecheck and build passed; lint had 0 errors and 5 existing warnings. Python compile and PHP syntax passed. No Radiko request or capture occurred.

The earlier 271 eligible short guide entries were only retained as aggregate diagnostics, not individual program records. This task forbade guide requests, so no current candidate was selected and exact nonduplicate candidate count remains unverified. Do not resume capture until a candidate's metadata can be checked against all 590 known files, native reservations, and active RadioFlix jobs.


## 2026-10-28 [SHT] inventory regression checkpoint
The final inventory parser/test state was rerun in the isolated PHP-enabled backend image with network disabled and read-only source/dependency mounts. Backend full discovery: 314 PASS, 0 skipped. The initial rerun failure was caused by `/tmp` tmpfs lacking executable permission for fake `at` helpers; rerunning with test-only `tmpfs /tmp:exec` passed without changing application code or assertions. The earlier synthetic ffprobe timeouts did not recur with the existing portable Jellyfin ffprobe runtime wrapper. Frontend: schedule 148 PASS (360/390/412/1280 px), reservation UI 24 scenarios PASS (360/1280 px), playback/navigation 21 PASS (360 px), typecheck/build PASS, lint 0 errors and 5 warnings. Inventory remains 590 total/known, 0 unresolved/parser errors; prior 589 parse results unchanged. No guide request or capture occurred during this regression run.

## 2026-10-28 isolated short-program E2E stopped at area guard

The final inventory checkpoint was pushed as `b31960307c3ee132e22b12f0b62489e86dbd9294`. Backend discovery passed 314/314 with zero skips after setting `exec` only on the test container's tmpfs; frontend schedule 148, reservations 24 scenarios, playback/navigation 21, typecheck and build passed, lint had 0 errors/5 warnings. The read-only inventory remains 590 known / 0 unresolved, with the old 589 parses unchanged.

The allowed JP13 guide scan fetched seven dates (2026-10-21 through 2026-10-27), all HTTP 200, and found 435 ended/timefree-eligible 3–10 minute candidates after metadata filtering. The shortest item that passed ordinary/native recording overlap checks and the known approved source route was LFR, `看板娘ホッピー・ミーナのHOPPY HAPPY BAR`, 2026-10-27 21:57–22:00 JST (180 seconds). The isolated harness attempted ordinary pc_html5 authentication, then stopped at its area-consistency guard because the authenticated area did not equal configured JP13. No playlist/HLS/segment request, ffmpeg, test DB insert, publish, or recovery followed. No area override or access-control bypass was attempted.

The harness had production DB, ordinary recordings, native reservations, and native timefree recordings mounted read-only; only its dedicated `/tmp` E2E root was writable. Work/publish are empty and test DB is absent. Production gates stayed OFF, readiness/bridge approval false; the rsv all-file fingerprint and `atq` listing were unchanged. A normal `rfriends3` recording process was already active and was not touched.

## 2026-10-29 authenticated-area isolated E2E

A normal pc_html5 auth returned `JP28`; configured `JP13` remained untouched and was recorded as a mismatch. Candidate station area came from the official region catalog. The shortest safe in-area item was CRK / Radio Kansai `心に光を`, 2026-10-22 06:00–06:05 JST. All 61 AAC/ADTS segments were validated and converted to a 299.989333-second PCM16 WAV. The strict validator passed, followed by test-root atomic publication, test DB recognition, and idempotent recovery. Details, including missing persisted exact EXTINF sum and fingerprints, are in the Phase 4 validation document.

This is an isolated test result only: production capture remains `ready=false` / `bridge_approved=false`; both gates remain OFF; no production DB, recording root, worker, or native reservation/at state was changed.

## 2026-10-29 isolated recording catalogue integration

`RecordingCatalog` now composes the existing `ProgramService` with verified completed timefree assets below the existing API routes. Normal program order/IDs and normal episode filenames remain unchanged; their responses gain only the additive `source=normal` marker. Completed timefree jobs are validated against DB metadata, publication intent, manifest, WAV/hash/size, and safe output path before being listed. Fixture jobs remain excluded by default and are visible only when a test explicitly opts in.

Timefree programs use a URL-safe `tf~` plus SHA-256-derived station/title ID. An episode uses the existing `broadcast_episode_id` under a `timefree-` namespace, with a deterministic filename derived from its broadcast interval and episode ID. If any ordinary audio file cannot be safely parsed, or its inventory walk encounters a symlink/error, timefree catalogue visibility fails closed. A known overlapping ordinary recording wins display priority; no files are deleted. Audio resolution accepts only the generated episode filename and catalogued completed asset, then revalidates the manifest-owned file under the dedicated timefree root. It does not accept a caller-supplied path.

An isolated copy of the retained CRK test DB and published WAV traversed `/api/programs` → `/episodes` → `/audio`: one CRK / `心に光を` program and one stable episode were returned. WAV serving returned `audio/wav`, correct length, Range 206 and invalid Range 416; traversal/missing assets returned 404. Existing HEAD behavior remains 405. The shared frontend player played the timefree fixture with speed/seek controls and progress persistence; no separate player or favorite mechanism was added. The copied completed fixture remained a single asset after three further fresh-store/fresh-worker reconciles, with no capture/ffmpeg/network and unchanged file/manifest. This did not touch the production DB or recording root.
