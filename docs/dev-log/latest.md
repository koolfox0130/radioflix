# RadioFlix Development Status

## Last updated
2026-10-29 22:34:04 JST

## Current task
Complete isolated Phase 4 integration of verified timefree recordings into the existing RadioFlix recording catalogue, episodes, and shared audio player.

## Current phase
Completed the read-only catalogue integration against a copy of the retained CRK fixture DB/WAV, verified API Range behavior, frontend shared-player playback, and three additional recovery passes. Final regression passed; reviewing the exact diff and preparing the user-authorized logical checkpoint.

## Status
ready_to_commit

## Completed
- Start HEAD: `196fae15afa57b0443482136473557f33d22e7cf`; branch `main`.
- Added a shared `RecordingCatalog` facade below existing API routes. Normal recordings preserve their legacy IDs/order/files; verified completed timefree recordings are additive. Timefree fixtures remain hidden by default and require explicit test opt-in.
- Timefree program ID is URL-safe and deterministic from station/title. Episode ID uses `broadcast_episode_id` under a `timefree-` namespace; generated filename is stable from broadcast interval and episode ID.
- Catalogue visibility validates completed DB row, publication intent, manifest, WAV/hash/size, and managed-root path. An incomplete/unknown ordinary recording scan fails closed for timefree visibility. An overlapping normal recording takes display priority; files are never removed.
- Reused the retained `CRK / 心に光を` completed asset only. The test DB/publish tree was copied under `/tmp/radioflix-timefree-catalog-final`; no new Radiko request, capture, segment download, or recording occurred.
- On the isolated artifact copy: `/api/programs` returned one timefree program; `/episodes` returned one stable episode; `/audio` returned the WAV (`audio/wav`, 57,598,030 bytes). Valid Range returned 206, invalid Range 416, traversal 404, and HEAD remained 405.
- Frontend exercised the existing shared player with the fixture: route navigation kept the player alive; rate/seek controls worked; the existing stable localStorage progress key and Media Session metadata/state (where exposed) were verified. No separate player or favorite system was added.
- Three more test-only fresh-store/fresh-worker reconciliation passes kept one completed DB row, one audio file, one manifest, unchanged hashes/metadata, no staging, and zero capture/ffmpeg/Radiko calls.
- A synthetic 590-file ordinary recording regression preserved all 590 filenames and parsed station/start/end intervals, legacy program IDs, and normal M4A `audio/mp4` serving. The actual production recording volume was not mounted or touched.

## In progress
- Final diff/security review, final safety snapshot, and the requested logical commit/push if the reviewed scope remains clean.

## Next actions
1. Finish secret scan, `git diff --check`, and confirm only the intended integration files are staged.
2. Commit the catalogue/API/player integration and relevant validation docs as one logical unit.
3. Push `main`, verify local HEAD equals `origin/main` and the actual remote main ref.
4. Update this log and a matching history snapshot with commit/push result; leave unrelated existing changes untouched.

## Blockers / Issues
- No functional blocker for the isolated catalogue/API/player integration.
- This validates the retained fixture asset through the ordinary API and shared player, not a production deployment. The production capture bridge remains fail-closed; deployment and real production recording remain unauthorized/not ready.
- HEAD requests to the audio endpoint return 405, matching the existing route behavior; no HEAD feature was added.

## Files changed
- `backend/radioflix/services/recording_catalog.py` (new): merged read-only catalogue, stable timefree IDs, duplicate policy, strict visibility/path checks.
- `backend/app.py`: route existing programs/episodes/audio handlers through the catalogue; additive source marker for normal episodes; timefree WAV uses the existing FileResponse/Range path.
- `backend/radioflix/timefree/worker.py`: expose verified completed-row metadata to the catalogue.
- `backend/tests/test_recording_catalog.py` (new): API/Range/security/state/duplicate/stability/recovery and 590-file synthetic normal-catalog regressions.
- `frontend/tests/playback-navigation-ui.mjs`: mock timefree program/episode exercises the existing persistent player, seek/rate controls, progress key, and Media Session.
- `docs/radioflix-timefree-runtime.md`, `docs/radioflix-timefree-phase4-validation.md`, `docs/dev-log/latest.md`, plus this history snapshot.
- Other pre-existing diffs such as `docs/radioflix-timefree-source-api.md`, unrelated untracked history, `.codex/`, and Dockerfile backups are preserved and excluded from this checkpoint unless later review finds they are necessary.

## Git state
Branch `main`; HEAD=`196fae15afa57b0443482136473557f33d22e7cf`. No commit/push yet in this task. Existing source/docs diffs and unrelated untracked files are preserved; no reset/restore used. Only named integration files are intended for staging.

## Tests
- Backend full discovery including PHP/bootstrap/worker: **337 PASS / 0 skipped**. Used Python 3.11 test dependencies from `/tmp` and a dedicated PHP test container with network none, read-only root/source, UID 1000, cap-drop ALL, no-new-privileges; test-only temp roots only.
- New recording catalogue/API tests: **7 PASS** in the final backend discovery.
- Existing CRK artifact API integration on an isolated `/tmp` copy: PASS; program/episode/audio mapping, WAV headers, Range 206, invalid Range 416, traversal 404.
- Recovery on isolated test copy: **3/3 PASS**, capture 0, ffmpeg 0, Radiko requests 0, duplicates 0, file/manifest unchanged.
- Python syntax: 4 changed Python files parsed successfully. PHP syntax: worker, fixture bindings, and rfriends driver PASS. `git diff --check` PASS before final doc update; will run again after.
- Frontend: schedule **148 checks PASS** at 360/390/412/1280; reservation UI **24 scenarios PASS** at 360/1280; playback/navigation **26 checks PASS** at 360.
- `npx tsc --noEmit`: PASS. `npm run lint`: 0 errors / 5 existing warnings. `npm run build`: PASS. The initial sandbox build failed only because Turbopack child-process port binding was denied; the same command passed with command-only approval.
- Secret scan and final `git diff --check` remain to be run after documentation updates.

## Runtime / Safety
- Production backend gate was read-only checked: `RFRIENDS_ENABLE_WRITES=0`; `RADIOFLIX_TIMEFREE_ENABLE_WRITES` unset/OFF. Source still fixes `ready=false`, `bridge_approved=false`; no timefree worker is deployed.
- All new API/recovery integration ran against the copied `/tmp` fixture DB and publish root in network-none, read-only-root, non-root containers. Backend/source/dependencies were read-only. Production DB/recording volumes, native rsv/dat/sh/at, Docker socket, and rfriends3 writable mounts were absent.
- No production DB or recording-root write, no native mutation, no rfriends3 or production container restart/recreate, no Radiko communication, no new recording, and no publisher use outside `/tmp` occurred.
- Backend test container used both gates `0`; production gate remained OFF.

## Important decisions
- Integrate below the existing API route layer; do not create timefree-only endpoints or a second frontend player.
- Ordinary recordings win duplicates. If ordinary audio inventory is unresolved, suppress timefree assets rather than risk a duplicate.
- Existing read/progress behavior is keyed by stable `(program ID, filename)` in localStorage. Favorite handling remains the existing title-based static list; no separate timefree favorite feature was introduced.
- The isolated artifact proves the user-facing API/player path for a completed fixture-enabled test asset only. It does not change production defaults or readiness.

## Recovery instructions
Continue from HEAD `196fae15afa57b0443482136473557f33d22e7cf`. The original retained E2E artifact remains under `/tmp/radioflix-timefree-e2e-20261029/run-0545`; the test copy is under `/tmp/radioflix-timefree-catalog-final`. Do not issue Radiko requests or access production output/DB to repeat this validation. Preserve all pre-existing unrelated docs/history/`.codex`/Dockerfile changes. Before checkpoint, stage only the explicitly reviewed catalogue/API/worker/test/frontend/docs files.
