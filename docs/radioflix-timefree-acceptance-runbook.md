# RadioFlix Timefree one-job acceptance runbook（未実行）

本書は本番での別途承認後にのみ使う。checkpoint 2のfixture検証では本書の手順を実行しない。現行capture上限は60秒、HTTP wire budgetはprocessあたり8、公開rootの所有者・Unix socketの実権限/backend→worker疎通は別途確認待ちである。候補番組が現行上限を超える場合は試験しない。上限・allowlist・timeoutを広げずに適合candidateが存在しない場合は中止し、先に別レビューを行う。

## Preflightと候補選定

1. 作業ticketとoperatorを記録。録音中番組、既存予約を変更する必要がある状態、未知のinventory、socket不整合があればabort。
2. `docker image inspect radioflix-backend --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'` とworker image inspectを読み取り専用で実施。revisionを承認対象Git HEADと一致させる。`unknown`・不一致はabort。
3. `/volume1/@home/kool-fox/radiko_public/radioflix-timefree` が存在し、実際のworker UID 10001:GID 20000が必要なstaging/publish操作を行えるowner/modeであることを確認。worker mount RW、backend mount ROもinspect。変更はしない。所有者/mode不一致ならabort。
4. `radioflix_radioflix-timefree-control` volume、worker側0770 directory/RW、socket 0660 owner 10001:20000、backend側ROをinspectし、backendからworker `/health` と `/status` をGET。接続失敗・異常payloadならabort。
5. backend/workerの`RFRIENDS_ENABLE_WRITES=0`、`RADIOFLIX_TIMEFREE_ENABLE_WRITES=0`、worker boot disabledをinspectで確認。値が違えばabort。
6. 放送局/開始終了/対象episodeをread-only schedule/catalogとnative予約・通常録音inventoryから選び、同一episode/局時間重複なし、native競合なし、inventory完全判明を記録。特殊・延長・再放送・不確かな番組は選ばない。おおむね5分の通常番組が望ましいが、現行60秒transcode制限に適合しないため、現状はその長さを受け入れられない。現行上限内で正式Timefree eligibilityにも適合する候補がなければ中止する。
7. 通常予約/native reservationには触れない。Timefree job作成にはTimefree専用gateが必要な構成の場合、gate変更とjob作成は別途明示承認を得る。job作成後にDB/APIから32桁lowercase job IDを1回だけ取得し、operatorと二者確認する。IDを再選択/探索するループは禁止。

## Approvalとone-job実行

8. `RADIOFLIX_TIMEFREE_BOOT_MODE=enabled`、承認対象image revision一致、job ID、publish root/socket/preflight根拠を再確認する。gateはまだOFF。readyはこの時点では未確認と記録する。
9. Timefree gateをONにできる別途明示承認を得た場合だけ、隔離workerの実行環境へ`RADIOFLIX_TIMEFREE_ENABLE_WRITES=1`を反映する。`RFRIENDS_ENABLE_WRITES=0`は維持する。設定反映は承認済みの運用手順で行い、このrunbook実施時もDocker recreate/restartを独断で行わない。
10. acceptance moduleと同じproduction image、DB/root mount、boot mode、gate設定で次のread-only local readiness probeを実行する。probeは`bridge_approved=false`のままで外部HTTPを呼ばず、readyだけを表示する。`ready=false`、probe error、revision不一致ならcaptureへ進まずTimefree gateをOFFに戻す。

```sh
python -c 'import json; from radioflix.timefree.control import production_worker; w=production_worker(); print(json.dumps({"ready": w.transport.ready, "bridge_approved": w.transport.bridge_approved, "read_only": w.read_only}))'
```

11. local readyがtrueであることを確認後、operatorが個別にbridge approvalする。対象job IDと期限を含むapproval JSONを安全なoperator専用pathに作る：`{"job_id":"<ID>","approved":true,"expires_at":"<UTC ISO timestamp>"}`。ownerは実行UID、mode 0600（または0400）、expiryは30分以内。token/credentialは含めず、既存secret/configファイルを流用しない。
12. 同一UID・同一production image・上記DB/root/approval envで**ただ1回**起動：

```sh
python -m radioflix.timefree.acceptance --accept-job <確認済み32桁JOB_ID>
```

`RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE`はapproval JSON pathを指す。job ID省略、別ID、再試行は不可。CLIはcontroller/server/loopを起動せず、指定job以外を選ばない。completed/failed/cancelled/expiredは終端で停止、既存completedは読み取りのみ。unknown/runningはproof-based reconcileだけ行い、再captureしない。実行中のabortはprocessへSIGINTし、自動再実行せずunknown recoveryを調査する。

13. stdoutのjob ID/state、process exit code、DB stateを照合。API/UIで他jobをdispatchしない。2件目を確認するためのpoll loopを開始しない。
14. terminalに達したら直ちにTimefree gateを0へ戻し、実際のruntime値を再inspect。bridge approval fileを安全に削除し、実データやcredentialを含まないaudit結果だけを記録。

## 成果物確認・停止条件・復旧

15. read-only DB/manifest/audioで同一jobのpublication intent、manifest hash/size/duration、atomic outputを照合。重複・余剰file・manifest不一致は成功にしない。
16. 別途承認されたread-only backend API GETとHTTP Rangeでassetを確認。Range 206、Content-Rangeとbyte countが一致しない場合はabort。今回のrunbookを使ったplayback requestは別の承認がなければ行わない。
17. `running`/`unknown`、intentのみ、outputのみ、hash不一致の場合は再録音しない。`reconcile`/`Publisher.verify`で所有intent・manifest・音声が全て一致する時だけcompleted recoveryを許す。確証がなければunknownのまま停止し、staging/outputを手作業で昇格/削除しない。
18. Abort条件：revision不一致/unknown、gate不明/ON、approval期限/ID違い、ready false、bridge未確認、native/file conflict、socket/health異常、未承認host、HTTP上限/timeout/60秒超過、duplicate/no-overwrite拒否、processが他jobへ進む兆候。gate OFFを確認して直ちに停止。
19. Rollbackはgate OFF、approval撤去、状態/intent/manifestをread-only確認すること。container recreate/restart、job削除、予約変更、publish手動修正をrollback手順へ含めない。状態不明なら保持して運用レビューへ渡す。

Docker確認は`docker ps/inspect/image inspect/compose config/compose ps/logs --tail`等のREAD ONLYに限る。runbook実施時にもdocker restart/recreate/up/down/buildは禁止。checkpoint 2完了や本書は実施許可ではない。
