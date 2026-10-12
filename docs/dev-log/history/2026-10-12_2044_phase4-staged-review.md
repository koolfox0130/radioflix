# RadioFlix Development Status

## Last updated
2026-10-12 20:43:46 JST

## Current task
Phase 4安全基盤の最終レビュー・検証と、指定範囲を1 commitにまとめてorigin/mainへpushする。実取得bootstrap実装は開始しない。

## Current phase
Phase 4の安全基盤完成。実radiko音声取得bootstrapは未接続。本番workerは未deploy。

## Status
ready_to_commit

## Completed
- Phase 1〜3正式リリース済み。今回のGit実状態を確認し、Phase 4差分は保持。.codex/config.tomlとfrontend/Dockerfile.dev-backup、frontend/Dockerfile.productionはcommit対象外。
- Unix socket専用worker transport、検証済みjob_idのみ通知、workerでDB正式metadata再取得、専用の二重gateを実装。
- 開始前/公開前にnative、通常録音、RadioFlix job、timefree job、正式metadataをread-only再照合。
- hidden stagingで音声検証・manifest/fsync・DB intent保存後、RENAME_NOREPLACEで公開し、証拠の揃った実ファイルだけcompleted扱いにする。
- backend/workerの再起動・中断を実ファイルとDB intentからreconcile。曖昧な状態を自動再録音/完了扱いしない。
- 番組表過去録音状態、重複送信防止、offline拒否、pollingと専用候補Composeを実装。mock/PHP隔離テストを維持。
- 今回指定の検証を再実行してPASS。指定commit messageで1 commit、その後origin mainへpushする。これは今回のユーザー明示指示による。

## In progress
- commit直前。stage済みallowlistのdiff/list/secret scanは確認済み。これからcommitする。
- commit成功後、同一HEADをorigin/mainへpushして検証する。

## Next actions
1. 完了: 明示allowlistの30ファイルをstage。excluded 3ファイルはunstaged保持。
2. `Add isolated RadioFlix timefree recording runtime` として1 commitを作成する。
3. `git push origin main` を実行し、HEADとorigin/mainの一致を確認する。
4. latest.mdをcommit/push済み最終状態へ更新し、最終history snapshotを保存する（1 commit制約のためログ最終checkpointはcommit後の作業差分として残す）。

## Blockers / Issues
- 実radiko audio bootstrap未接続。`capture_ready=false`。今回のコードは実録音を起動できない。本番隔離worker反映も未実施。
- 実形式WAV以外は未対応。NAS本番パスのowner/permission/fsync受入は未確認。
- native worker間で共通lockなし。照合直後の外部同時native開始を完全排除する仕組みではない。
- 今回native予約dat/shの指紋と本番4コンテナは不変。at spoolは前後の集約指紋が変化した。隔離試験はnetwork noneで本番mount/at queueへ接続せず、当作業からat操作していない。変化元はこの観測だけでは特定できない。
- lintに既存warning 5件。実録音・本番DB E2E・Android実機確認は未実施。

## Files changed
commit候補はbackend API/service/store/timefree worker一式、backend既存app/schedule接続とtest dependency、backend tests、timefree test/deploy-candidate Compose、番組表UI/API rewrite/UI test、Phase 4 validation/runtime docsと既存history、latest.md。明示的なstaged allowlistで確定する。
除外: `.codex/config.toml`、`frontend/Dockerfile.dev-backup`、`frontend/Dockerfile.production`、secret/.env/credential、`/tmp`。値・内容を取得していない。

## Git state
main / precommit HEAD d46babe85db84b4ee08ff1ccf3d14fe97ed4fa0f。origin/mainもprecommit時点で同一。30件を明示stage済み。cached diff check PASS、staged一覧にcredential/除外fileなし。commit/pushは未実施。除外ファイルは未stageで保持。

## Tests
今回実行済み:
- backend/PHP/worker全188件成功、skip 0（network none、read-only、UID1000、cap-drop ALL。code/source/依存ro、専用test volumeのみ書込）。
- Python `py_compile`: 43 files PASS。PHP `-l` worker.php/fixture-bindings.php PASS。
- schedule UI 148 checks PASS（360/390/412/1280px）。reservation UI 24 scenarios PASS（360/1280px）。playback/navigation 21 checks PASS（360px）。全て隔離mock。
- `npx tsc --noEmit` PASS。`npm run lint` error 0、既存warning 5。`npm run build` PASS。
- test volumeでatomic publish/no-replace、collision、SIGKILL中断/復旧、unknownと再録音防止などruntime testsを実行。
- Compose config `--quiet` PASS。PHP source-manifest hash PASS。
- `git diff --check` PASS。secret pattern scan 29 changed/new files、findings 0（内容を出さず）。
- 初回sandbox制限でNext local serverのport bindが失敗したため、同じ隔離mock UIテストとbuildを許可付きで再実行し成功。Host PHPは未導入だがPHP test/syntaxは専用既存imageで実行。
- 本番公開先E2E、実radiko認証/HLS/録音、実機Androidは未実施。禁止/未接続のため。

## Runtime / Safety
- `RFRIENDS_ENABLE_WRITES=0`（backend実効環境）。timefree gateはproduction backendに未設定＝既定OFF。test containerでは両gateを明示0。
- RadioFlix SQLite読み取り集計: active reservation 0、active weekly 0、timefree table absent（active/running job 0）。recording_jobsもactiveなし。列挙は状態別件数だけで秘密/番組情報は出力していない。
- 本番4コンテナのID/state/StartedAt/RestartCount/gate前後比較一致。全てrunning、RestartCount 0。rfriends3 running、healthcheck未定義。本番worker containerなし。
- native reservation dat/sh files: 18件、集約指紋は前後一致。at spoolは各11/2件、集約指紋が前後で変化。作業はnative dat/sh/atを書き込む処理を含まない。変化元は未確認であり、不変と断定しない。
- 本番timefree録音なし: YES。実録音なし、両gateを1にしていない。backend/PHP/worker試験はmock/合成音声、network none。
- 本番worker deploy/restart/recreateなし。本番録音volumeへのwriteなし。今回専用test volumeを削除済み。専用review imageは過去build状態で残る。
- 本番隔離worker反映試験: まだ実施せず。両gate OFFの候補はあるが、NAS mount permission/fsync受入・個別反映許可が必要。実タイムフリー1本試験: NO、bootstrap未接続のため進行不可。

## Important decisions
- commit対象は明示allowlist。未追跡一括addを使わない。.env/secrets/token/cookie/Authorization/.codex/指定Dockerfile/tmpは除外。
- commitは指定メッセージで1個。commit後latest/history最終更新はその1 commitに含めず、working treeに残す。push後HEAD == origin/mainを確認する。
- 二重gate、CaptureUnavailable、network-none testで実録音経路が閉じている。今回の検証PASSを実録音・本番deploy許可として扱わない。

## Recovery instructions
次はstaged filename/diff/secret scanを確認し、明示許可された1 commitとpushを完了する。ログとコードを戻す目的のreset/restoreは使わない。push後はHEADとorigin/mainを比較し、latest.mdとhistoryへ結果を記録する。続く作業は実radiko bootstrapの隔離開発だけで、実録音は別途許可と本番受入が必要。
