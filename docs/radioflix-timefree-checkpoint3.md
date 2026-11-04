# Checkpoint 3 host verification

ホスト実行の結果を2026-11-05に確認。build、real Compose render、dedicated fixture topology、5分fixture E2E、boundaries、runner、backend full、catalog/API、cleanupはすべてPASS。script exit 0。本番変更0、実Radiko/runtime外部通信0。build依存のpackage取得通信とは区別する。

## Backend full

457 tests、446 pass、0 fail、0 error、11 skip（33.524秒）。skipは既存のPHP条件に基づくもので、今回の変更で追加したskipはない。

### Skip一覧

- `test_changed_owned_file_cannot_be_cancelled`: PHP CLI未導入
- `test_create_inspect_cancel_and_idempotency`: PHP CLI未導入
- `test_existing_native_reservation_is_untouched`: PHP CLI未導入
- `test_failed_cancel_keeps_job_and_data`: PHP CLI未導入
- `test_invalid_identifier_and_region_do_not_create_files`: PHP CLI未導入
- `test_lost_journal_does_not_claim_absence_or_remove_job`: PHP CLI未導入
- `test_lost_submission_receipt_recovers_by_job_ownership`: PHP CLI未導入
- `test_partial_registration_can_be_retried_without_duplication`: PHP CLI未導入
- `test_started_job_cannot_be_cancelled`: PHP CLI未導入
- `test_too_late_never_schedules`: PHP CLI未導入
- `test_real_downloader_with_offline_boundaries`: 隔離PHP/source未設定

## Warnings

sqlite3 unclosed database ResourceWarningは1,374件。直前のerrors=4のhost runにも1,362件あり、既存のwarning種別。実行完了範囲とGC時点が異なるため件数差だけで新規resource leakとは判定できない。新規明確なリークの証拠はなく、このcommitのblockerとはしない。追跡調査は必要。Starlette/httpxのdeprecation warningもあり。

## 安全契約と検証範囲

- 独立acceptance serviceのみ。通常workerはdisabled/network none、backend/worker Timefree gateとRFRIENDS gateは0を維持する設計。live runtimeの再inspectは今回未実施。
- acceptance metadata 300秒、audio 302秒、segments 62、wire 73。capture attempt 1（retry 0）、job retry 0。HTTP retry/redirectは同一wire budget内。
- normal profile 60秒/8 wireは不変。second job不変を5分fixtureで確認。
- 実approval、本番job/capture/publish、production rebuild/recreate、rfriends3変更は未実施。
- 結果はbase HEAD 4046b6f6020e983e9f84fcf81c2175027e5b22f0上の未commit作業treeに対するhost検証。レビュー後はdocsのみ更新し機能コードは変更していない。
- `.codex` のharness/result/logはcommitしない。backend Dockerfileの既存permission変更、過去source API診断、古いhistory/backup等も今回のcommitから除外する。

## 本番前の残課題

admission CLIとrunnerの接続・target approvalの引き渡しを完成/検証する。runnerは現在既存queued jobを要求し、DB直接insertや通常gate ONで補わない。次turnでrevision整合を保ってbackend/acceptance imageを安全に再同期し、read-only preflightとdry-runを行う。本番1番組acceptanceには別途明示承認が必要。
