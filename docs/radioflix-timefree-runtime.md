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
