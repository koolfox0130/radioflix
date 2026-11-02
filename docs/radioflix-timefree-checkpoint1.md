# Phase 4 checkpoint 1: production capture readiness guard

## 範囲

既存Python source componentsをproduction adapterへ接続し、local readinessとlive承認を分離した。one-job acceptance mode/CLI、本番配備、実Radiko通信は対象外。fixture成功は実サービス互換性や任意長番組の収録成功を保証しない。

## 依存方向と循環importの修正

実import tracebackで確認した旧経路：

`recording_catalog.completed_assets` → `worker.require_capture_start` → `admission.CaptureNotReady` → `capture.errors`のpackage初期化 → `capture.__init__.ProductionCaptureAdapter` → `production.require_capture_start` → 初期化途中の`admission`。

新しい責務：

- `contracts.py`：immutable `CaptureAdmission` / `CaptureReadiness`とsanitized例外。依存はstdlib dataclassesのみ。
- `admission.py`：値だけを受け取るpure policy。環境変数、capture実装、FastAPI、DB、ffmpeg、HTTPを参照しない。
- `runtime_policy.py`：環境設定とcaptureの状態をsnapshotへ変換してpure policyへ渡す。capture実装へのimportなし。
- `capture/errors.py`：既存import pathを維持する例外の再export。同じclass identityを保つ。
- `capture/production.py`：構成・local preflight・stage実行。
- `control.py` / `worker.py`：構成と実行制御。API/catalogの契約変更なし。

TYPE_CHECKINGや遅延importによる循環隠しは使用しない。既存capture packageのexportも維持する。

## readyとbridgeの契約

`refresh_readiness()`が通信なしでローカル検査を実施し、`CaptureReadiness`へ結果を保存する。`ready`はそのsnapshotの読み取りであり、guardやHTTP送信前確認からffmpeg/DB操作を発生させない。

検査対象はsource transport、auth/playlist/media ports、required preflight、managed rootとstagingのcanonical path/書込み権限/同一filesystem、DBの存在・権限・必要schema、既存allowlistによるffmpeg/ffprobe executable/version/空き容量。検査はschemaを作成せず、音声生成・publishもしない。各capture開始時に再検査する。job metadata、期限、重複、native競合は既存Preflightでcapture前と公開前に照合する。

`bridge_approved`はlive external capture境界を越える明示承認。readyとは独立で、`ready=true / bridge_approved=false`も表現する。factoryが実行用storeをROにしても、capture構成の能力を承認の有無で書き換えない。

開始条件はpure policyで一元化する：

`boot_mode == enabled AND RADIOFLIX_TIMEFREE_ENABLE_WRITES == 1 AND ready is True AND bridge_approved is True`

`RFRIENDS_ENABLE_WRITES`は含まない。worker、adapter、HTTP送信直前で同じ判定を用いる。disabled factoryはlocal probeも実行せず、health/statusはcapture未検査のfalse snapshotを返す。通常daemonはbridge承認を付与しない。承認をHTTP/API/env経由で入力する入口は追加していない。

## production component接続と制限

`ProductionAuthenticator` → `TimefreePlaylistSource` → `HlsMediaSource` → `WorkspaceTranscoder` → 既存WAV validator → 既存worker/Publisher。

`WorkspaceTranscoder`はadapterのowned filenameを既存`FfmpegArgvTranscoder`のowned filenameへno-replace hardlinkで接続する。任意argv/URLは受け付けない。allowlist、TLS/host policy、timeout、response上限、no-overwriteを維持。

観測専用`ProductionMediaFetcher`は最大3segmentのprefixであり番組全体の完成を保証しないため、既存のENDLIST必須`HlsMediaSource`を使用する。旧PHP `ProductionBootstrap`は互換・診断用のNotReady実装として保持し、production worker経路はPython adapterへ切り替える。

上限は拡大していない：transcoderは最大60秒、HLS sourceは合計2MiB/ENDLIST必須、実transportのwire budgetは最大8。この範囲を超えるjobはfail-closed。8回の予算はtransport instance単位で、jobごとに暗黙リセットしない。

新NASの`/usr/bin/ffmpeg`はsymlinkのため既存allowlistでは拒否される。fixtureは実体パスを解決し、既存の`preflight_allowlisted_path`を明示注入する。システムpathのsymlinkを自動承認する変更はしていない。

## 前回16失敗の分類

分類はA=循環import、B=ready/bridge semantics、C=fixture setup、D=tool環境。E=その他genuine regression、F=無関係/既存の分類に該当する未解消項目はない。

1. `test_recording_catalog` import error：A。contracts/policy/runtime分離で解消。
2. `test_long_program_rejected_before_auth`：C。symlink ffmpegでreadyが先にfalse。fixtureの明示allowlist設定後、長時間拒否を検証。
3. `test_production_stack_capture_validate_publish`：C。同上。production components + Fake HTTP + 合成AACの完走を検証。
4. `test_ready_is_local_and_not_approval`：C。同上。readyと承認の独立性を検証。
5. `test_unknown_host_stays_rejected`：C。同上。unknown hostでfail-closed、公開なしを検証。
6. `test_start_matrix`：C。同上。4開始条件の拒否と成功を検証。
7. `test_revocation_is_checked_at_http_boundary`：B。source層はguard例外を既存契約どおり`AUTH_FAILED`にsanitizeする。期待例外を訂正し、HTTP送信0を引き続き検証。
8. `test_changed_owned_file_cannot_be_cancelled`：D。
9. `test_create_inspect_cancel_and_idempotency`：D。
10. `test_failed_cancel_keeps_job_and_data`：D。
11. `test_lost_journal_does_not_claim_absence_or_remove_job`：D。
12. `test_lost_submission_receipt_recovers_by_job_ownership`：D。
13. `test_partial_registration_can_be_retried_without_duplication`：D。
14. `test_started_job_cannot_be_cancelled`：D。
15. `test_existing_native_reservation_is_untouched`：D。
16. `test_too_late_never_schedules`：D。

8–16はfake at/atq/atrm内のPATHから/tmpのPHPが消えることが原因。fixtureに選択済みPHP commandをshell-quoteして渡すことで全てPASS。production PHPと本番予約は変更していない。

既存テスト変更の理由：runtimeのlive扱いfixtureにはboot/gate/bridgeを明示する新しい開始契約を適用。source APIテストのclass固定readyチェックはpropertyへの変更を反映し、実際の未構成拒否・ready matrixはproduction/guard testsで確認する。

## 検証

sandbox内では既存TestClientが待ち続けるため、ホストで`unshare -Urn`を使いloだけのnetwork namespaceでテストを実施。本番Dockerは使わない。Python依存とPHP/gitは/tmp隔離環境のみ。

順序：import/collection → pure guard → capture/source/transcoder/preflight → catalog/API → Timefree/worker/recovery/gate/PHP → backend全discovery。

前半結果：15module import PASS、collection errors 0、pure guard 4 PASS、capture関連164 PASS、catalog/API等127 PASS、Timefree等129件中128 PASS/skip1。最終full discovery結果はdev-logを正とする。

skip1は旧hash固定PHP source未配置による互換テストであり、Python adapterのcheckpoint 1完了を妨げる新規regressionではない。PHP bootstrap Python testsとPHP予約driver fixtureは実行済み。

本番image revision unknown、publish root所有者、Unix socket実permission/疎通、NAS上のexecutable設定は別途再同期・配備監査の対象。今回のcommitは本番受入試験の許可ではない。
