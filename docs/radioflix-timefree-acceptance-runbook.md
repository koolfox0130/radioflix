# RadioFlix Timefree dedicated one-job acceptance runbook

実装と検証の手順。これ自体は本番実行の許可ではない。通常worker/controlをenabledにしない。実Radiko通信、本番job作成、本番gate変更、本番container recreateは別途承認がない限り行わない。

## 構成と上限

`docker-compose.timefree-acceptance.yml` は単独projectで `timefree-acceptance` だけを起動する。通常workerは `network_mode: none`、disabled boot、両gate 0のまま。backendのTimefree gate 0、全rfriends gate 0。acceptance processは明示job ID、短命approval、concurrency 1の `accept_one()` で終了し、controller/loopを起動しない。DBと専用publish rootだけRW。normal recordings、native reservations/timefree、approvalはRO。UID:GID 10001:20000、rootfs RO、capabilities全drop、no-new-privileges、port/Docker socket/rfriends dependencyなし。egressはdedicated bridgeだが宛先制限はapplication allowlist/TLS validationで行う。

Acceptance-only closed profile:

- 番組metadata最大300秒。301秒はauth前拒否。
- ADTS/WAV最大302秒。Publisherのscheduled duration許容差±2秒に対応。WAV validatorの通常の厳しい入力比許容差も維持。
- PCM16 WAV最大116,033,536 bytes（302秒×96kHz×stereo×16bit+64KiB RIFF）。normal profileは従来60秒/32MiB。
- segment最大62。根拠は `ceil(300秒/5秒)+2`。final media playlist全体を確認してから最初のsegment requestを行い、超過は拒否。
- wire固定overhead最大7（player JS/auth1/auth2、official area XML、station stream XML、playlist/master/media最大2）+実segment数+共有retry/redirect余裕4。hard maximum 73。retryは各request最大3 attemptで同じbudgetを消費する。manifest判明後はbudgetを縮める。normal transport hard maximum 8のまま。
- areaはauth2の実値をofficial station-area catalogと比較。configured areaは書き換えない。

## 事前条件

候補は終了済み・5分以内・通常の完全episodeで、inventory/native reservation/timefree重複なし、現在配信可能、既知host/area適合をread-onlyで確認する。候補・native inventory・publish rootに不明点があれば中止する。

通常APIのPOSTは従来どおりbackend Timefree gateとdispatcher readinessを要求する。専用 `radioflix.timefree.admission` CLIはexplicit episode ID/revision/dateと10分以内のtarget-bound approvalを必須とし、APIと同じschedule/eligibility/native/duplicate検証を通して1件だけqueuedにする。dispatcherは呼ばず、backend gate=0のまま。approval pathは `RADIOFLIX_TIMEFREE_ADMISSION_APPROVAL_FILE` で指定する。Checkpoint 3のhost fixture rehearsalとbackend regressionはPASSした。admission CLIとone-job host runnerへの統合・そのE2E検証は未完了なので、本番ではまだ使用しない。DB直insert、guard迂回、通常worker enabled化で補わない。

build済みacceptance image `radioflix-timefree-acceptance:<HEAD>` が必要。OCI revision label、backend/worker image revision、HEAD/local origin/mainが全一致し、専用service/runner/test codeがcommit済みであること。Dockerfileはffmpeg/ffprobeを含む。通常backend imageはrebuild/recreateしない。

## 実行順

1. 正式経路で作成された唯一のeligible queued jobのIDを控える。
2. Termiusからrepo rootで `scripts/timefree-onejob-acceptance.sh --dry-run --job <JOB_ID>` を実行する。これはgit/image/gates/socket/mount/revision、exact job、duplicate/native/file conflicts、duration/budget、renderされたservice/command/UID/network/mountを検証する。network-noneのprobeだけで外部HTTP・mutation・approval・capture・publishは行わない。
3. dry-runが成功し、改めて明示許可された場合だけ同じscriptに `--execute` を渡す。runnerはprivate tempに10分approvalを一度作り、dedicated serviceだけを `compose run --rm --no-deps` で起動する。backend/worker/gateway/frontendを起動・再作成しない。
4. terminal state/exit codeを照合。finally/trapでapproval、所有label一致container、所有labelかつ孤立した専用Compose networkを削除し、元のproduction container IDs/start times/gatesを再確認する。frontend/backend/programs/normal audio Range smokeを行う。
5. 成功時はread-only probeでjob/manifest/audio整合・asset countを確認。失敗時はoperator再試行禁止。unknown/intent/stagingは証拠を保持し、read-only recovery reviewへ渡す。

## abort / cleanup

runner/dry-runはHEAD同期不一致、revision不一致、gate不正、通常worker enabled/network有効、socket/mount異常、複数job、job非queued、duplicate/native conflict、inventory不明、publish root既存物、approval/render不整合で停止する。captureはHTTP/segment/wire/duration/validator/no-overwrite/preflight異常で終端し、retryしない。

SIGINT/SIGTERM trapは実行runnerを停止して所有containerとapprovalを片付ける。SIGKILL・host電源断ではtrapは動かない。記録されたjob ID/owner labelだけを使ってread-only確認後、該当containerを停止しapprovalを削除する。job/outputを手作業で変更せず再captureしない。Compose networkはproject/service labelと接続containerなしを確認した場合だけ削除する。cleanup検証に失敗した時は成功扱いにせずtemp owner記録を保持する。

この実装時点で、fixture/network-noneによる5分E2E、異常segment拒否、runner mock、Compose renderは検証済み。Docker daemon不在の環境では実container rehearsalを省略したと明記する。本番1番組の実行は別工程。

Checkpoint 3 host結果・skip理由・warningと残課題は [検証記録](radioflix-timefree-checkpoint3.md) を参照。
