# RadioFlix Development Status

## Last updated
2026-10-28 22:56:47 JST

## Current task
Phase 4: complete `[SHT]` inventory checkpoint, then one short-program isolated E2E.

## Current phase
The exact `[SHT]` recording marker is parsed; the latest complete backend and frontend regressions passed. Proceeding to the explicitly authorized guide-only candidate selection, followed by one <=10-minute isolated test capture only if all conflict checks pass.

## Status
testing

## Completed
- Current task start HEAD: `83b204dccaf89a6c4117ae8d1f87469dfad3a02f`, branch `main`. Only the existing post-push latest/history log differences and unrelated untracked files were present; no reset/restore.
- No background test/dev server was running at inspection. The isolated PHP test container was available.
- Reused the dedicated test image with an explicit Python entrypoint, network none, read-only root, non-root UID, dropped capabilities, no-new-privileges; mounts were backend read-only, test dependencies/source fixtures read-only, and tmpfs only. The image's default entrypoint was tried once and failed closed on read-only filesystem before tests; it was stopped. The proper test entrypoint then ran tests only.
- Backend discovery: **300 passed, 0 skipped**. First proper run exposed six PHP fixture subtests missing their expected tmpfs directory; after creating that disposable directory in tmpfs, the complete rerun passed.
- The host Python TestClient attempt stalled due the local harness; no code change was made for it. The isolated Python 3.12/PHP container is the authoritative full run.
- Saved live input used for local rerun: one AAC/ADTS segment, 31,707 bytes, HTTP content type previously observed as `application/octet-stream`. ADTS core=24,000 Hz, 118 frames, parsed duration 5.034667 s. Input ffprobe: decoded rate=48,000 Hz, stereo, duration 4.894063 s; the fresh profile query explicitly reported HE-AAC (correcting the earlier AAC-LC label).
- The earlier multi-segment `UNEXPECTED_SAMPLE_RATE` run remains cause-unconfirmed: input ffprobe, expected-rate provenance, and RIFF diagnostics were not preserved. A later separate one-segment run passed at 48 kHz (classification E for that run only); it did not reproduce or identify the earlier failure. Do not record the old failure as fixed.
- Prior JP13 scan: 271 eligible 180–300 second ended entries were found across seven guide dates. Their per-program details were not persisted, so no item can be selected again offline.
- Current code uses bounded local ffprobe input before transcoding, an allowlisted sibling executable, `shell=False`, file-only protocol, AAC/channel/rate checks; output validator remains strict. This current behavior is not proof of the older failure cause.
- Saved-segment rerun: ffmpeg 7.1.1-Jellyfin exit 0; output WAV 966,734 bytes; ffprobe WAV/pcm_s16le/s16/48,000 Hz/stereo/5.034667 s. RIFF chunks `fmt `/`LIST`/`data`; declared and actual payload 966,656 bytes; block align 4; 241,664 frames. Internal diagnostic reason=None; validator PASS at expected=actual 48,000 Hz.
- Synthetic matrix: 44.1/48 kHz, mono/stereo, 1/2/3 segment cases PASS, including explicit 24 kHz ADTS core→48 kHz decoder output case.
- Final checks: `git diff --check` PASS; secret scan 0 matches. Production `RFRIENDS_ENABLE_WRITES=0`, Timefree gate unset/OFF; active-like reservations/weekly/recording jobs 0; no `timefree_jobs` table. `ready=false`, `bridge_approved=false`; backend/frontend/gateway/`rfriends3` all Up.
- Commit/push: `83b204dccaf89a6c4117ae8d1f87469dfad3a02f` (`Fix RadioFlix timefree sample-rate validation`), 14 explicitly staged Phase 4 files. Push succeeded and actual remote HEAD matches. No reset/restore.
- The task-owned temporary segment/WAV/probe script and isolated PHP test container were removed. No background test/dev server remains. The isolated tests had no native or recording volume mount; no native path write, publisher, recording, deploy, or service restart occurred.
- Fresh segment result: 7 bounded HTTPS requests, all 200/no redirect; one segment (31,707 bytes) from the approved host. ffprobe: HE-AAC, decoded INPUT=48,000 Hz, stereo; ADTS core=24,000 Hz. EXPECTED=48,000 Hz was recorded before ffmpeg and matched INPUT. ffmpeg shell=False exit 0 / 0.191 s. Output WAV=48,000 Hz PCM16 stereo, 5.034667 s, 966,734 bytes. WAV header=48,000 Hz; validator actual=48,000 Hz; reason=None; PASS. Native fingerprints exactly match before/after; no temporary audio remains.
- Targeted `test_timefree_ffmpeg.py`: 14 PASS. No code changes or new commit were needed; prior full regression remains valid at the same source HEAD.
- New live-probe preflight: `RFRIENDS_ENABLE_WRITES=0`; Timefree gate unset/OFF; production readiness and bridge flags false; active-like reservation/weekly/recording counts zero; no `timefree_jobs` table; native target overlap zero; target window eligible through 2026-11-01 05:00 JST; no timefree worker container. Native read-only fingerprints: rsv 10 / `7f77ec31c929ea9de09d6e93a4ec5d2acb0a291dfef55968070dc0e41feab0e3`; dat/sh 76 / `c1c69d438ecbf92421c2e018e03883fe36a721f0cce40904153588f0c3dd0e91`; atjobs 7 / `cbe44af605e4e38dd0bb51b5b935987bfc567fdf2c1e3e2741a0b4f6c1da7a92`; atspool 2 / `b9362d0a2ddd5b9dcf22603e5ab7aa9892d974b83b2533884f56fa607174ef52`; `atq` 6 / `a3c26828e3337b4ddf24300d539a52f5639f30a4a1bf6f83e0761897237ec312`.
- This task: inspected the sole unmatched recording read-only. `[SHT]LFR_霜降り明星のオールナイトニッポン_20261010_0102_0300.m4a` is regular, not a symlink, 344,411 bytes, mtime 2026-10-10 01:10:09 JST. Parser failure was solely the documented `[SHT]` prefix before station `LFR`; date/time tokens are valid. No sidecar exists. Read-only ffprobe: MP4/M4A, AAC HE-AAC 48 kHz stereo, 29.781333 s, plus MJPEG cover-art stream. The filename schedule interval (2026-10-10 01:02–03:00 JST) is used conservatively; mtime and media duration are not treated as schedule bounds.
- `RecordingInventory` now accepts exactly the canonical filename form and the exact `[SHT]` marker. It still blocks on the full named interval even for incomplete/zero-byte/corrupt media; unknown markers and malformed dates remain unresolved. No filename is ignored.
- Read-only full inventory scan: 590 audio files; prior 589 accepted filenames retained exactly the same parsed station/start/end values; the one `[SHT]` item became known; 590 known, 0 unresolved, 0 parser errors, 0 symlinks, 0 walk errors.
- New inventory suite: 14 PASS. Relevant backend/runtime/Timefree/bootstrap suite: 78 PASS. Full backend discovery before the final added inventory case: 313 tests, 311 PASS, 2 `ffprobe_timeout` errors in synthetic AAC integration under the recovery PHP test image, 0 skipped. After the final parser guard and 14th inventory case, the inventory/runtime/timefree/bootstrap targeted suite passed 78 tests; full discovery was not repeated.
- Frontend regression: schedule 148 PASS; reservations UI 24 scenarios PASS at 360/1280px; playback/navigation 21 PASS at 360px. Typecheck PASS; lint 0 errors / 5 existing warnings; build PASS on approved rerun after sandbox port-bind denial.
- Python syntax across backend PASS; PHP syntax for `worker.php`, `fixture-bindings.php`, and `rfriends_driver.php` PASS. Secret-pattern scan 0 matches; `git diff --check` PASS.
- No guide item was reselected: prior guide scan details were not saved, and this task prohibited Radiko requests. The parsed inventory is complete, but current eligible nonduplicate candidate count is unverified; no E2E candidate was chosen.

## In progress
Inventory code/test/docs are ready for a narrow checkpoint commit and push. After remote verification, acquire current guide metadata, select the shortest eligible safe candidate, recheck all gates and snapshots, then run one isolated end-to-end capture/publish/recovery.

## Next actions
1. Review and stage only `[SHT]` parser, its tests, relevant runtime/validation documentation, and the development log/history. Commit and push the inventory checkpoint.
2. Fetch guide entries only, evaluate the full eligible candidate set against all recordings/native reservations/active jobs, and choose one shortest safe item or stop.
3. Before capture, recheck gates, readiness, active jobs, native fingerprints, and container identity; then run one bounded <=10-minute isolated E2E in test DB/work/publish roots.
4. Verify isolation/recovery, rerun only regressions required by any code changes, update latest/history, and report.

## Blockers / Issues
- No blocker remains for the inventory checkpoint: complete backend discovery passed with 0 skips after fixing only the isolated tmpfs execution mode.
- Candidate selection still requires a fresh guide-only request, which is explicitly allowed by the current task. Capture remains conditional on exact metadata conflict checks.

## Files changed
- `backend/radioflix/timefree/preflight.py`: accept exactly the canonical recording name and exact `[SHT]` marker.
- `backend/tests/test_timefree_inventory.py`: focused parser/inventory regression tests.
- `docs/radioflix-timefree-runtime.md`, `docs/radioflix-timefree-phase4-validation.md`, `docs/dev-log/latest.md`: inventory behavior and validation history.
- Existing `docs/radioflix-timefree-source-api.md` changes and unrelated untracked files are preserved and excluded from the inventory checkpoint.

## Git state
Branch `main`; start/current HEAD `83b204dccaf89a6c4117ae8d1f87469dfad3a02f`. Inventory parser/test/docs changes are uncommitted. No commit/push in this resumed turn yet. Existing unrelated `.codex/`, prior history files, frontend Docker backups, and source-api doc diff remain untouched.

## Tests
- Isolated network-none backend full discovery, Python 3.12 + PHP: **314 tests PASS, 0 skipped**. The first attempt had 9 PHP driver failures because `/tmp` was mounted without exec; rerun with test-only `tmpfs /tmp:exec` passed. This is a test-container mount issue; product code/timeouts were unchanged. The earlier two ffprobe timeout cases did not recur with the existing portable Jellyfin ffprobe wrapper.
- Schedule UI: **148 PASS** at 360/390/412/1280 px. Reservation UI: all **24 scenarios PASS** at 360/1280 px. Playback/navigation: **21 PASS** at 360 px.
- `npx tsc --noEmit`: PASS. `npm run lint`: 0 errors, 5 warnings. `npm run build`: PASS.
- Read-only recording inventory from the immediately preceding inventory task: 590 total, 590 known, 0 unresolved/parser errors; old 589 results unchanged. The full backend run includes the final `[SHT]` test suite.
- Diff check, source review, secret scan, and final inventory test artifacts are being completed before commit. No Radiko guide request has been made in this resumed turn yet.

## Runtime / Safety
This resumed turn has so far used only a disposable backend test container with `--network=none`, read-only root/mounts, non-root UID, dropped capabilities, no-new-privileges, and test tmpfs; frontend Playwright apps used mocked APIs on localhost. No Radiko requests, publisher, recording, production DB/native writes, deploy, or service restart occurred in this turn. Prior confirmed configuration: `RFRIENDS_ENABLE_WRITES=0`, Timefree gate OFF/unset, `ready=false`, `bridge_approved=false`; these must be rechecked before the allowed guide/capture steps. Production/native recording volumes were not mounted in tests.

## Important decisions
- The `[SHT]` marker is accepted only as the exact documented prefix. It uses the filename’s complete named broadcast interval for duplicate prevention; unknown markers remain fail-closed.
- Backend failures were environmental: first full rerun exposed noexec for fake `at` helpers; the successful rerun set tmpfs `exec` without changing application code or test assertions. The full successful run also did not reproduce the prior ffprobe timeout.
- Keep the old multi-segment `UNEXPECTED_SAMPLE_RATE` classified as cause unconfirmed/not reproduced; do not mark it fixed.

## Recovery instructions
Resume from HEAD `83b204d`. Backend full discovery (314/314, skip 0) and frontend regression/build/typecheck/lint are now complete. Stage only inventory-related files and relevant documentation/log files for the authorized checkpoint. After verifying origin, perform only the guide GET first; do not authenticate/capture unless a specific <=10-minute candidate is proven nonoverlapping. Both production write gates must remain OFF, production readiness/bridge approval false, and all audio/publish/DB artifacts confined to the dedicated test workspace.
