# RadioFlix Development Status

## Last updated
2026-10-31 15:36:46 JST

## Current task
Design and validate a gate-OFF Timefree Worker deployment architecture without changing production containers or data.

## Current phase
Disabled read-only boot mode and isolated deployment topology validation. Production deployment was not attempted.

## Status
ready_to_commit

## Completed
- Re-read `AGENTS.md`, this progress log, Phase 4 runtime/validation docs, current Git state, and the actual active Compose definitions.
- Start HEAD/origin/main: `34a21c5faebf0d4cfd0d84bc809b78bcb79611ed`; branch `main`.
- Confirmed active production Compose is `docker-compose.yml` + `docker-compose.rfriends.yml`; services are backend, frontend, and rfriends-gateway. No Timefree worker is deployed.
- Read-only production inspection confirmed backend `295f0e2a9096…`, frontend `5480a0de5bfb…`, gateway `33d43c8efecb…`, and rfriends3 `e346364f5944…` were running with restart count 0. Backend `RFRIENDS_ENABLE_WRITES=0`; Timefree write gate unset/OFF. No production service was changed.
- Found `/data` is an existing shared named volume but cannot safely serve as a worker-writable socket-only mount: worker RW would also grant DB write; worker RO cannot create the socket. Existing recording/native mounts are RO; `/run` and `/tmp` are container-local. Dedicated UDS volume is the safe design and requires backend recreation/configuration in a future authorized deployment.
- Added explicit disabled boot behavior: Timefree store transaction refuses before path creation/SQLite open; worker skips reconcile/run; controller startup/tick skip mutation; dispatch/cancel reject while gates are OFF; disabled worker uses a read-only store and filesystem mounts.
- Added fixed UDS lifecycle checks: socket directory owner/group/mode 10001:20000/0770, socket 0660, no permission broadening, owned stale socket cleanup with connect and inode recheck, refusal of foreign/active/regular/symlink paths, and inode-safe cleanup.
- Backend mounts the shared socket volume read-only and joins group 20000; isolated test proved the backend can connect over that RO mount.
- Added disabled production candidate, separate future enabled override, and network-none isolated Compose test. Config render verified disabled worker has no public ports, Docker socket, or network; DB/publish/native source mounts are RO and only its UDS volume is RW.
- The future enabled override is separate and undeployed. It sets `RFRIENDS_ENABLE_WRITES=1` on the backend/gateway as well as the Timefree gate, so it also enables native reservation writes and needs separate review.
- Read-only host stat found the proposed production Timefree publish bind source `/volume1/@home/kool-fox/radiko_public/radioflix-timefree` is missing. It was not created. Production deploy is blocked until that root is separately provisioned/reviewed.
- Isolated test topology used only `/tmp/radioflix-timefree-disabled-test` fixtures, `network_mode: none`, read-only root/data/source mounts, non-root worker, `cap_drop: ALL`, `no-new-privileges`, and no ports/Docker socket.
- Worker healthy and running, socket smoke passed (`0660`, owner 10001:20000); dispatch returned `writes_disabled`. Three worker restarts, backend restart-equivalent, and owned stale-socket recovery all passed against the isolated project. Fixture DB/root inode, size, mtime, hash, SQLite schema, and file count remained unchanged. Isolated test containers/socket volume were removed after validation.

## In progress
- None. Architecture and isolated validation are complete; production path provisioning and backend recreation remain future, separately authorized work.

## Next actions
1. Review and commit only the gate-OFF architecture/test/docs files listed below; do not stage the pre-existing `docs/radioflix-timefree-source-api.md` change or unrelated untracked files.
2. Push the architecture checkpoint and verify `HEAD == origin/main`.
3. In a separately authorized task, provision the dedicated production publish root with reviewed ownership/permissions, then recreate backend only to attach the RO UDS volume/config and run the disabled worker deployment test. Do not enable capture.
4. Keep production capture blocked until the source bridge is ready/approved and enablement has separate review.

## Blockers / Issues
- Current backend lacks a Timefree socket mount/configuration, and no safe existing path gives the worker a writable socket directory while preserving DB read-only. Backend recreation is required for future backend/worker communication.
- The proposed production publish-root bind source is missing; `create_host_path: false` deliberately prevents accidental directory creation.
- Capture remains `ready=false` / `bridge_approved=false`. No production Timefree worker deployment or recording is authorized by this validation.

## Files changed
- `backend/radioflix/timefree/store.py`: strict read-only transaction mode.
- `backend/radioflix/timefree/worker.py`: disabled read-only no-op reconcile/run path.
- `backend/radioflix/timefree/control.py`: explicit disabled boot, health/status, dispatch gate, bounded UDS setup/cleanup.
- `backend/radioflix/timefree/service.py`: cancel checks gates before DB access/mutation.
- `backend/app.py`: backend Timefree store is read-only while gates are off.
- `backend/Dockerfile`: seeds restricted shared socket directory owner/group/mode.
- `backend/radioflix/timefree/healthcheck.py`: UDS disabled-state health probe.
- `backend/tests/test_timefree_runtime.py`, `backend/tests/timefree_disabled_smoke.py`: read-only and isolated UDS coverage.
- `docker-compose.timefree.yml`, `docker-compose.timefree-disabled-test.yml`, `docker-compose.timefree-enabled.yml`: disabled/isolated/future-enabled layouts.
- `docs/radioflix-timefree-runtime.md`, `docs/radioflix-timefree-phase4-validation.md`: architecture, mount matrix, socket, recreate plan, and missing-path blocker.
- Existing modified `docs/radioflix-timefree-source-api.md`, unrelated history, `.codex/`, and frontend Dockerfile backups are preserved and excluded from this task's stage set.

## Git state
- Branch `main`; HEAD and `origin/main` remain `34a21c5faebf0d4cfd0d84bc809b78bcb79611ed` before checkpoint.
- No commit/push yet; explicit file-by-file staging will follow final checks.
- Existing unrelated modified/untracked files are preserved; no reset/restore/add-all used.

## Tests
- Backend full discovery in a Python 3.14 / PHP / ffmpeg test-only image: **343 PASS, 0 skipped**. First run had one synthetic ffprobe timeout; that test passed standalone, then full discovery passed on rerun without changing timeout/assertions.
- Focused read-only boot/runtime tests: PASS.
- Isolated Compose: network none, backend+worker started; backend RO socket connection, health/status, `writes_disabled` negative dispatch, worker restart ×3, backend restart, stale-socket recovery: PASS.
- Test DB and publish fixture hashes/inodes/size/mtime/schema/count unchanged: PASS.
- Python syntax compile: 74 files PASS. PHP syntax: 3 files PASS.
- Frontend schedule UI: 148 PASS; reservation UI: 24 scenarios PASS; playback/navigation: 26 PASS.
- `npx tsc --noEmit`: PASS.
- `npm run lint`: 0 errors, 5 warnings (existing warnings).
- `npm run build`: PASS.
- Disabled and enabled production Compose config rendering: PASS; no production `up`, `build`, restart, or recreate.
- `git diff --check`: PASS. Secret-pattern scan: PASS (17 changed/new files scanned; no credential-pattern findings).
- Test worker runtime had `network_mode:none`; no Radiko request, segment, ffmpeg capture, job, publish, or production DB access occurred. The temporary test image build fetched system packages from Debian repositories only.

## Runtime / Safety
- `RFRIENDS_ENABLE_WRITES=0` in live backend; Timefree write gate unset/OFF. No gate changed.
- Source capture `ready=false`, `bridge_approved=false` (production bootstrap remains NotReady).
- No production Timefree job, Radiko request, segment fetch, capture ffmpeg, publish, DB/root write, or worker deployment.
- No production backend/frontend/gateway/rfriends3 restart/recreate. Production container identities/restart counts were inspected read-only and remained the same as the starting snapshot.
- No native dat/sh/at or rfriends3 operation/change. Isolated test mounted only fixture native paths RO.
- Disabled test worker process was `10001:20000`, UDS only, no public TCP/Docker socket; DB/publish/native sources RO.
- Production publish root is currently missing, so deployment is not ready even with both gates OFF.

## Important decisions
- Reuse of existing `/data` for a socket is rejected: file-level RO and socket RW cannot be separated safely on the current broad volume mount.
- Use a dedicated named UDS volume, worker RW and backend RO, group 20000, socket 0660; this requires backend recreation.
- Disabled boot is enforced both in code and by read-only worker mounts. Gate OFF means no schema migration/reconcile/staging/publish/network/ffmpeg path.
- Do not deploy the enabled override; its shared `RFRIENDS_ENABLE_WRITES` setting also enables gateway/native reservation writes.
- Do not create the missing production Timefree path during this task.

## Recovery instructions
Resume on branch `main` at `34a21c5faebf0d4cfd0d84bc809b78bcb79611ed` plus this worktree diff. Preserve the pre-existing `docs/radioflix-timefree-source-api.md` diff, `.codex/`, all pre-existing untracked history, and frontend Dockerfile backups. Run the final secret scan and review the explicit stage set; commit/push only the current gate-OFF architecture. Production backend recreation, worker deployment, publish-root creation, and gate changes require a separate authorized task.
