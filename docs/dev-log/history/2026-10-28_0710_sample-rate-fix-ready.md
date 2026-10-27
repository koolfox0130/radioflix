# RadioFlix Development Status

## Last updated
2026-10-28 07:10:25 JST

## Current task
Resolve the live AAC sample-rate validator mismatch using the saved segment only, then complete isolated regressions.

## Current phase
The sample-rate mismatch is fixed; all isolated backend/frontend and static checks pass. Pre-commit review is complete.

## Status
ready_to_commit

## Completed
- Start HEAD: `736c7b6e4951c611e23cda1b7a08a757619049d3`, branch `main`. Existing tracked differences and unrelated untracked files were retained; no reset/restore.
- No background test/dev server was running at inspection. The isolated PHP test container was available.
- Reused the dedicated test image with an explicit Python entrypoint, network none, read-only root, non-root UID, dropped capabilities, no-new-privileges; mounts were backend read-only, test dependencies/source fixtures read-only, and tmpfs only. The image's default entrypoint was tried once and failed closed on read-only filesystem before tests; it was stopped. The proper test entrypoint then ran tests only.
- Backend discovery: **300 passed, 0 skipped**. First proper run exposed six PHP fixture subtests missing their expected tmpfs directory; after creating that disposable directory in tmpfs, the complete rerun passed.
- The host Python TestClient attempt stalled due the local harness; no code change was made for it. The isolated Python 3.12/PHP container is the authoritative full run.
- Saved live input used for local rerun: one AAC/ADTS segment, 31,707 bytes, HTTP content type previously observed as `application/octet-stream`. ADTS core=24,000 Hz, 118 frames, parsed duration 5.034667 s. Input ffprobe: AAC-LC, decoded rate=48,000 Hz, stereo, duration 4.894063 s.
- Cause: expected rate previously came from ADTS core sampling-frequency index via `_adts_duration()`; validator correctly read WAV fmt=48,000 Hz and rejected expected=24,000. The sample-rate contract was using the wrong input rate representation (classification E); ADTS parser core-rate extraction was correct, ffmpeg had no resample option and output 48,000 Hz, WAV parser was correct, and this was a single segment (no duration/concat interaction).
- Fix: bounded local ffprobe input before transcoding, allowlisted sibling executable, `shell=False`, file-only protocol, AAC/mono-or-stereo/rate consistency checks; output validator remains strict and uses decoded input sample rate. Preflight checks ffprobe version.
- Saved-segment rerun: ffmpeg 7.1.1-Jellyfin exit 0; output WAV 966,734 bytes; ffprobe WAV/pcm_s16le/s16/48,000 Hz/stereo/5.034667 s. RIFF chunks `fmt `/`LIST`/`data`; declared and actual payload 966,656 bytes; block align 4; 241,664 frames. Internal diagnostic reason=None; validator PASS at expected=actual 48,000 Hz.
- Synthetic matrix: 44.1/48 kHz, mono/stereo, 1/2/3 segment cases PASS, including explicit 24 kHz ADTS core→48 kHz decoder output case.

## In progress
- No test or diagnostic remains. The documented sample-rate fix and full isolated regression are ready for the conditional checkpoint commit/push. No further Radiko request is needed.

## Next actions
1. Stage only the reviewed Phase 4 capture/transcoder tests and relevant runtime/source/validation/dev-log files; preserve unrelated untracked files.
2. Commit the sample-rate contract correction and related completed Phase 4 changes, then push only if the staged diff and remote checks remain as reviewed.
3. Record final commit/push state in latest/history.

## Blockers / Issues
- The first container attempt used the image's default rfriends entrypoint and its setup failed on read-only root; no production/native mount was present. The successful test container explicitly bypassed that entrypoint.
- `compileall` initially attempted cache writes into the read-only backend bind mount; rerun directed bytecode cache to tmpfs and passed. One PHP syntax command first named a nonexistent file; it was corrected to the three actual PHP files, all of which passed.
- The initial unapproved Playwright invocation could not start localhost and then could not find the browser at the default cache. Using the existing `/tmp` browser cache and approved localhost test execution passed all UI suites. Initial build sandbox could not bind Turbopack's local port; approved retry passed.
- One-off observation wrapper threw before the original validator callback because its copied-WAV probe used an incorrect path. The retained WAV was independently inspected; the saved original segment was then transcoded through corrected production code and passed validation. All task-owned audio, probe script and build panic log were subsequently deleted; the isolated PHP test container was removed.

## Files changed
- Existing Phase 4 changes remain in capture adapter/transcoder/source modules, backend tests, and runtime/source/validation docs.
- This turn updates expected sample-rate derivation in `backend/radioflix/timefree/capture/argv.py`, adds focused tests, and records the diagnosis in the three Phase 4 docs and this dev-log.
- Unrelated `.codex/`, frontend Docker backups, and preexisting history files remain untouched/un-staged.

## Git state
Branch `main`; HEAD `736c7b6e4951c611e23cda1b7a08a757619049d3`. No commit/push yet. Existing diffs and unrelated untracked files preserved.

## Tests
- Backend full discovery in network-none Python 3.12/PHP isolated container: **300 PASS / 0 skipped**.
- Timefree/capture/Source API/ffmpeg tests are included in that run; synthetic ffmpeg matrix PASS.
- `compileall`: PASS using tmpfs pycache. PHP syntax: `worker.php`, `fixture-bindings.php`, and `rfriends_driver.php` PASS.
- Schedule UI: 148 PASS, widths 360/390/412/1280. Reservation UI: 12 scenarios each at 360/1280 PASS. Playback/navigation: 21 PASS at 360px.
- `npx tsc --noEmit`: PASS. `npm run lint`: 0 errors, 5 preexisting warnings. `npm run build`: PASS after approved rerun for local Turbopack bind restriction.
- `git diff --check`: PASS after docs updates. Secret-pattern scan: 59 candidate files, 0 matches; values are never printed.

## Runtime / Safety
No worker deploy/restart/recreate, publisher, full-program capture, or native write. Production `RFRIENDS_ENABLE_WRITES=0`; Timefree gate is unset/OFF. Readiness and bridge approval remain false. The live diagnostic used one previously downloaded segment in `/tmp`; one short local ffmpeg conversion ran, with no recording or publisher call. The isolated test container had no native/recording mounts. Read-only DB recheck: active-like reservation, weekly, and recording-job counts 0; no `timefree_jobs` table. Production backend/frontend/gateway/`rfriends3` remained Up. The test/probe performed no native-path write; native fingerprints were not fully comparable to the prior log because recorded path/count methods differed, so no claim is made about unrelated scheduled `rfriends3` cron activity.

## Important decisions
- Preserve strict WAV format, payload, RIFF bounds, block alignment, and exact expected sample rate validation. Correct the expected rate source to the local AAC decoder output rate rather than accepting arbitrary mismatches.
- ADTS sampling-frequency index describes the AAC core rate. For the observed file, the decoder reports an effective 48 kHz output rate. All bounded inputs must have consistent decoded rates and valid relationship to their ADTS core rates.
- No Radiko request, segment refetch, ffmpeg whole-program assembly, publisher, or production readiness change is part of the remaining work.

## Recovery instructions
Continue from the current `main` worktree at HEAD `736c7b6e4951c611e23cda1b7a08a757619049d3`. The saved segment/WAV, one-off probe script, panic log, and dedicated PHP test container have been cleaned up. Preserve existing diffs and unrelated untracked files; never reset/restore or use `git add -A`. Both gates remain OFF; `ready=false`, `bridge_approved=false`. No further network request is needed.
