# RadioFlix Development Status

## Last updated
2026-10-24 19:58:42 JST

## Current task
Focused diagnosis and correction of the normal pc_html5 auth2=401 path; no audio retrieval or recording.

## Current phase
Safe Source API ordinary-auth contract confirmed against current upstream and bounded Radiko observations. Authenticator code is fixture-tested; live HTTP transport and capture remain fail-closed.

## Status
completed

## Completed
- Read `AGENTS.md`, latest log, runtime/source-api/validation docs, and `frontend/AGENTS.md`; compared the real worktree with the previous log. The log was stale: source changes and an auth-success observation already existed, while it still said auth was blocked before retry.
- Compared current read-only rfriends3 behavior with current yt-dlp and rec_radiko_ts. yt-dlp extracts the `pc_html5` key from the `RadikoJSPlayer` call with a bounded pattern and falls back to its static key; rec_radiko_ts uses the same upstream fallback. Both slice the extracted full key using the offset/length from the same auth1 response, then base64-encode the slice. Normal auth does not use a Premium session/cookie.
- Identified the previous probe's partial-key error: it applied auth1 offset/length to raw `playerCommon.js` bytes rather than to the extracted full key. The old rfriends3 slash-split parser also fails against the observed current JS shape.
- Implemented bounded full-key extraction and ordinary `ProductionAuthenticator`; Premium/session/cookie inputs and metadata-selected URLs are absent. `ProductionHttpTransport` remains NotReady.
- One corrected ordinary pc_html5 auth candidate succeeded: player JS=200, auth1=200, auth2=200, no redirects. Auth1 offset=3, length=16; extracted full-key length=40; partial-key base64 length=24. Fresh auth1 token was paired with that auth2. Extra headers differed from the prior probe, so partial-key generation is the strongest/main cause but not experimentally isolated as the only changed factor.
- Using ordinary auth only, observed an in-area (`areafree=0`) five-minute timefree item: playlist/master HTTP 200, 195 bytes; child media manifest HTTP 200, 665 bytes; same final Smartstream host and no redirects. No segment request was made; segment tags were not retained/validated.
- No Premium login/session/cookie, area-free bypass, or alternate auth candidate was used. The observed in-area item did not require Premium/area-free access.

## In progress
- Production HTTP transport, playlist provider, media fetch, ffmpeg and capture readiness remain unimplemented/disabled. This focused task only confirms normal auth and manifest-level contract evidence.

## Next actions
1. Keep both Production HTTP transport and capture path NotReady until a separate reviewed implementation and security test stage.
2. If continuing Phase 4, implement only against the confirmed normal-auth fixture contract first; request separate authorization before audio segment retrieval or any real recording.
3. Preserve the auth source tests and redacted observation notes; do not persist credential-bearing response data.

## Blockers / Issues
- The earlier 401 is best explained by the raw-JavaScript partial-key construction. Earlier and corrected probes also differed in extra headers, so the key issue is the primary cause, not a strictly isolated causal proof.
- Manifest child was fetched, but segment-level behavior remains unobserved by design. No conclusion about audio compatibility or recording readiness follows from manifest success.
- No commit or push was performed in this task. Do not stage unrelated existing untracked history, `.codex/`, or frontend Dockerfile backups.

## Files changed
- `backend/radioflix/timefree/capture/source/full_key.py`: bounded current pc_html5 key parser and upstream fallback.
- `backend/radioflix/timefree/capture/source/production_auth.py`: ordinary auth1/auth2 request contract over injected transport; `ready=false`.
- `backend/radioflix/timefree/capture/source/__init__.py`: export authenticator.
- `backend/tests/test_timefree_sources.py`: full-key/fallback, request structure, credential redaction, bounds, and NotReady regression tests.
- `docs/radioflix-timefree-source-api.md`: upstream comparison and redacted auth/manifest observations.
- `docs/dev-log/latest.md`: corrected from stale blocked-before-auth state.
- `docs/dev-log/history/2026-10-24_1958_auth-correction.md`: matching snapshot.
- All unrelated pre-existing untracked files are preserved and excluded.

## Git state
branch `main`; starting and current HEAD `c1e7dbed48d02b376ff7114346ff32f6469b1a92`. Previous latest recorded origin/main equal at that checkpoint; remote was not re-queried in this task. No commit/push. Relevant worktree changes are the five code/test/docs files above plus this log/snapshot; unrelated untracked files remain untouched. No reset/restore or broad staging.

## Tests
- Source API tests: 37 PASS (rerun after source change).
- Backend full isolated discovery: 263 PASS / 0 skipped (completed after implementation in the interrupted run; network none, read-only root, non-root, dedicated test volumes). PHP/bootstrap/worker coverage included.
- Python compileall: PASS.
- PHP syntax: 5 files PASS in the isolated PHP test image; host PHP CLI is unavailable.
- Schedule UI: 148 checks PASS (rerun, 360/390/412/1280px).
- Reservation UI: 24 scenarios PASS (rerun, 360/1280px).
- Playback/navigation UI: 21 checks PASS (rerun, 360px).
- `npx tsc --noEmit`: PASS.
- `npm run lint`: 0 errors, 5 existing warnings.
- `npm run build`: PASS after retry with permission for Turbopack's local process bind; sandbox-only attempt failed with `Operation not permitted` while creating a worker.
- `git diff --check` and secret-pattern scan: final run pending after this log update.

## Runtime / Safety
- The explicitly authorized observation made ordinary auth and manifest HTTP requests. No audio segment was requested; no ffmpeg, audio save, publisher or recording ran.
- `RFRIENDS_ENABLE_WRITES` and `RADIOFLIX_TIMEFREE_ENABLE_WRITES` remain unset/OFF; neither was enabled.
- `ProductionAuthenticator.ready=false`, `ProductionHttpTransport.ready=false`, `ProductionCaptureAdapter.ready=false`, `bridge_approved=false`.
- No worker deploy, rfriends3 modification, native dat/sh/at modification, gate change, or normal recording-area write occurred.
- No credential, auth token, partial key, cookie, session, Authorization value, or response body was logged or persisted. The code/tests contain only synthetic auth fixtures; the upstream fallback is public implementation data and is never logged.

## Important decisions
- Use the current upstream full-key extraction contract, then apply auth1 offset/length to those key bytes. Never slice raw JavaScript with auth offsets.
- Ordinary auth is the only successful route established. Do not add Premium/session/area-free behavior based on this result.
- Keep live networking disabled in application code. The successful observation used a bounded external probe; it does not make `ProductionHttpTransport` ready.
- The current evidence supports the earlier partial-key construction as the primary 401 cause; header differences prevent claiming a one-variable experiment.

## Recovery instructions
Start at current HEAD and preserve the current changes and unrelated untracked files. Run final diff/secret checks after the completed log snapshot. Continue only with fixture-backed production contract implementation. Keep all capture readiness flags false; do not download segments, run ffmpeg, enable gates, deploy, or record without a separately authorized safe transition.
