# RadioFlix Development Status

## Last updated
2026-11-01 00:10:33 JST

## Current task
Diagnose and prevent stale production backend images from omitting the Phase 4 Timefree API.

## Current phase
Isolated validation image, fixture worker socket E2E, and requested regression completed. No production deployment was attempted in this task.

## Status
ready_to_commit

## Completed
- Start HEAD and `origin/main`: `766deeac27bca03bfd5edf5fc66e8ffa7bd79043`. `git ls-remote origin refs/heads/main` was subsequently verified successfully and returned the same SHA. No Git history rewrite occurred.
- Production rollback state is healthy and unchanged during this task: backend container `acf059cb70a3` uses the retained rollback image `sha256:b2eb892390e2f680cc0d02ee1e6ccb1c15a249a4569be74bb18ea9e774e0ba09`; frontend `5480a0de5bfb`, gateway `33d43c8efecb`, and rfriends3 `e346364f5944` remain running with restart count 0. No Timefree worker container is running. Backend GET `/api/programs` returned 200. `RFRIENDS_ENABLE_WRITES=0`; Timefree gate is unset/OFF.
- Root cause: prior production `docker compose up -d --no-deps backend` did not build. Effective Compose uses build context `./backend` and `Dockerfile`; Dockerfile copies `app.py` and the full `radioflix` package; no prior `.dockerignore` excluded the Timefree code. The Oct 6 production image had a different `app.py` hash and lacked `/app/radioflix/timefree`, the Timefree API module, and API routes. This is deployment-command omission/stale tag reuse (F, with D as consequence), not context, COPY, ignore, target, or cache failure.
- Added explicit image selection/build declaration to `docker-compose.yml`, `RADIOFLIX_GIT_SHA` build arg and OCI revision label in `backend/Dockerfile`, and `backend/.dockerignore` for test/cache/local data/env files. Runtime docs now require immutable commit-tagged build, label/package/OpenAPI verification, fixture UDS check, and previous-image retention. Validation docs record the incident and correction.
- Built isolated image `radioflix-backend:phase4-validation-766deeac`, ID `sha256:1a1bb7a7b44cdab28117e37745293c7ba1ca38286080206fd30ac3bd69989a95`, revision label equals the starting HEAD. It contains Timefree package/worker client; app import and `/api/timefree/jobs` OpenAPI route checks passed.
- Isolated network-none Compose E2E passed: backend socket RO, worker socket RW, fixture-only DB and roots, both gates 0, no public ports. Backend reached worker health/status; dispatch was blocked with `writes_disabled`. Fixture DB and publish-root fingerprints stayed unchanged. No production service/container/volume was used for this E2E.
- Backend full discovery: 398 PASS / 0 skipped using Python 3.12 compatible preexisting wheels, PHP CLI, portable local ffmpeg/ffprobe, network none, read-only root and non-root. Initial retries exposed test-environment issues (Python ABI mismatch, missing tmp dirs, slow system ffprobe); they were corrected only in temporary test setup, with no source/timeout relaxation. Focused ffmpeg suite: 14 PASS.
- Frontend: schedule UI 148 PASS using Playwright 1.51.1/Chromium 134; reservation UI scenarios passed at 360px and 1280px; playback/navigation 26 PASS. TypeScript PASS. Lint: 0 errors, 5 existing warnings. Production build PASS after rerun outside the sandbox due Turbopack child-process bind restriction.
- `git diff --check` PASS. Secret-pattern scan on the intended changed files: 0 matches.

## In progress
- Review the focused change list, make one checkpoint commit, then attempt `git push origin main` and verify the remote if network access permits. No production deploy/recreate is authorized or planned.

## Next actions
1. Stage only `backend/Dockerfile`, `backend/.dockerignore`, `docker-compose.yml`, `docs/radioflix-timefree-runtime.md`, `docs/radioflix-timefree-phase4-validation.md`, and `docs/dev-log/latest.md` plus this task's history snapshot.
2. Commit the stale-image prevention checkpoint after final diff review.
3. Attempt push to origin/main; verify HEAD and actual remote if GitHub resolves. Preserve all unrelated source-api edits, untracked history, `.codex/`, and frontend backup files.
4. Stop before any production backend recreate, worker start, gate change, Radiko connection, or recording.

## Blockers / Issues
- The first remote lookup failed DNS; a later explicit retry succeeded and confirmed actual remote main equals the starting HEAD. Push remains to be attempted after checkpoint commit.
- Production was intentionally not deployed. This corrects provenance and validation procedures only.

## Files changed
- `backend/Dockerfile`: OCI revision label/build arg.
- `backend/.dockerignore`: narrow build context exclusions.
- `docker-compose.yml`: explicit selectable backend image and build SHA arg.
- `docs/radioflix-timefree-runtime.md`: stale-image incident, image verification/build/rollback procedure.
- `docs/radioflix-timefree-phase4-validation.md`: incident and isolated image/UDS results.
- `docs/dev-log/latest.md`: current task and verification record.
- Existing `docs/radioflix-timefree-source-api.md`, `.codex/`, prior untracked history, and frontend backup Dockerfiles are pre-existing unrelated changes and remain untouched.

## Git state
- Branch `main`, HEAD `766deeac27bca03bfd5edf5fc66e8ffa7bd79043`; origin tracking ref is same. No commit/push yet. Actual remote lookup failed DNS.
- Intended changes listed above. All unrelated modified/untracked content is preserved. No add-all/reset/restore.

## Tests
- Backend: 398 PASS / 0 skipped; focused ffmpeg: 14 PASS.
- Validation image: import/startup and Timefree OpenAPI route PASS; backend↔fixture-worker Unix socket health/status PASS; disabled dispatch rejected.
- Frontend: schedule 148 PASS; reservations scenarios PASS at 360px and 1280px; playback/navigation 26 PASS; `npx tsc --noEmit` PASS; `npm run lint` 0 errors / 5 warnings; `npm run build` PASS.
- `git diff --check` PASS; changed-file secret-pattern scan PASS (0 matches).
- The first test attempts failed only due mismatched Python wheel ABI, missing temporary directories, outdated slow ffprobe and Playwright/browser test environment. Corrected isolated reruns passed. No test condition or production timeout was relaxed.

## Runtime / Safety
- Production backend image remains old rollback image; no container was built/recreated/started/restarted in this task. Frontend, gateway and rfriends3 unchanged. Worker absent.
- Both gates OFF (`RFRIENDS_ENABLE_WRITES=0`, Timefree OFF/unset). `ready=false` / `bridge_approved=false` remain as fail-closed configuration; no capture path was invoked.
- No Radiko DNS/auth/HTTP/HLS, segment fetch, ffmpeg recording, publisher, DB/root/native write, or rfriends3/native change occurred. Production backend GET smoke was read-only.
- Validation image/build and fixture Compose used test-only execution. Previous production backend image is retained for rollback.

## Important decisions
- `docker compose up` alone is insufficient for a changed backend source tree. Build and prove an immutable SHA-tagged image before any future recreate.
- This work does not authorize deployment. Future disabled worker deployment remains a separate operation and capture remains NotReady / not approved.

## Recovery instructions
- Resume from the focused unstaged changes listed above. Do not include the existing `docs/radioflix-timefree-source-api.md` change or unrelated untracked files.
- Before any future deployment, explicitly build the backend with `RADIOFLIX_GIT_SHA`, inspect its OCI revision label and Timefree package/OpenAPI routes, render the disabled Compose set, then follow the reviewed deployment procedure. Keep the old image available.
