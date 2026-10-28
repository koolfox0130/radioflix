# RadioFlix Development Status

## Last updated
2026-10-29 05:37:38 JST

## Current task
Phase 4: select and validate one short timefree episode inside the authenticated normal area.

## Current phase
A fail-closed station→area metadata source and normal-area candidate selector are implemented and regression-tested. `CONFIGURED_AREA=JP13` remains unchanged. Full backend/frontend regressions passed; preparing the focused selector checkpoint before the authorized isolated E2E.

## Status
ready_to_commit

## Completed
- Current pushed HEAD: `b31960307c3ee132e22b12f0b62489e86dbd9294`; origin/main matched at task start. Existing source-api doc diff, unrelated history and untracked files are preserved.
- Prior inventory remains 590/590 known, 0 unresolved; prior 589 station/start/end parses unchanged.
- Added `StationAreaSource` for the official `radiko.jp/v3/station/region/full.xml` station `id`→`area_id` mapping and a pure normal-auth-area selection policy. Unknown/malformed mappings fail closed.
- `CONFIGURED_AREA` is kept separate from `AUTHENTICATED_NORMAL_AREA`; mismatch is diagnostic only. Candidates require exact station-area match, areafree=0, 180–600 seconds, ended, and within timefree expiry; sort order is duration ascending.
- Area-policy + inventory tests: 28 PASS. Backend full discovery: **328 PASS / 0 skipped** in isolated network-none/PHP test container.
- Frontend schedule 148, reservations 24 scenarios, playback/navigation 21 PASS; typecheck/build PASS; lint 0 errors / 5 warnings. Python compile, diff check and secret-pattern scan PASS.

## In progress
Preparing the explicit area-policy code/test checkpoint. After push/remote verification, a single fresh ordinary auth will supply `AUTHENTICATED_NORMAL_AREA`; the isolated harness will fetch official station-region metadata and the guide in that area, then select only a non-overlapping areafree=0 candidate.

## Next actions
1. Commit/push only the new station-area source, area policy, tests, and this checkpoint log/history; verify HEAD equals origin/main.
2. Take fresh gate/active-job/native/container snapshots. In the isolated harness, authenticate once, record only area ID, fetch `region/full.xml`, and search 3–10 minute guide entries in that authenticated area.
3. Select the shortest candidate that passes official station-area match, timefree/areafree checks, ordinary/native inventory, and active-job conflicts. If none exists or mapping is ambiguous, stop.
4. Recheck safety immediately before one <=10-minute test-only E2E; publish/DB/recovery only in dedicated test roots.
5. Verify post-run safety, update latest/history, and report.

## Blockers / Issues
- Prior configured-area candidate (LFR, JP13) stopped because normal auth produced a different area; this correction removes the configured-area equality requirement without changing or spoofing either area. No new auth request has been made in this task yet.
- Actual selection remains conditional on the official station metadata mapping and candidate/conflict checks in the authenticated area.

## Files changed
- New: `backend/radioflix/timefree/capture/area_policy.py`, `backend/radioflix/timefree/capture/source/station_area.py`, `backend/tests/test_timefree_area_policy.py`.
- `docs/dev-log/latest.md` updated for this test checkpoint. Existing modified `docs/radioflix-timefree-source-api.md`, runtime/validation log diffs, unrelated untracked history, `.codex/`, and frontend Docker backups are preserved and not included unless specifically reviewed later.

## Git state
Branch `main`; HEAD `b31960307c3ee132e22b12f0b62489e86dbd9294`. New area-source/policy/test files are untracked; latest/runtime/validation/source-api docs have preexisting uncommitted changes. No commit/push has been made for the area policy yet; no reset/restore.

## Tests
- New area policy + inventory tests: **28 PASS** in network-none isolated PHP/Python test container.
- Backend full discovery after implementation: **328 PASS / 0 skipped**.
- Frontend: schedule 148 PASS (360/390/412/1280), reservations 24 scenarios PASS (360/1280), playback/navigation 21 PASS; `npx tsc --noEmit` PASS; lint 0 errors/5 warnings; production build PASS.
- `py_compile`, `git diff --check`, secret-pattern scan (0 added-file matches) PASS.
- No Radiko authentication/guide/source/media request has been made in this task yet.

## Runtime / Safety
Prior confirmed production settings: `RFRIENDS_ENABLE_WRITES=0`, timefree gate unset/OFF, `ready=false`, `bridge_approved=false`; `RFRIENDS_AREA=JP13` is the read-only configured value and has not been changed. The prior isolated E2E used test-only writes and stopped before playlist; no live capture. Before the next E2E, recheck current DB states, native fingerprints and container identities. No production publish/DB write, worker deploy, native write, or rfriends3 mutation is authorized.

## Important decisions
- The station-region mapping uses Radiko’s official `v3/station/region/full.xml` metadata, consistent with upstream `rec_radiko_ts` source. No hand-maintained station→area guesses.
- A configured/authenticated area mismatch is reported but not itself a failure. Only stations whose official `area_id` exactly equals the actual normal-auth area are eligible.
- Normal auth never receives an overridden area. Premium/session and areafree=1 paths remain excluded.

## Recovery instructions
Resume from pushed HEAD `b319603`. The new area policy and tests passed 328 backend tests and the full frontend suite. Commit/push these explicit files, then run one fresh auth once inside the isolated E2E harness; use the returned area and official station mapping to select candidates. Do not log token/partial key, change `RFRIENDS_AREA`, or use any area/premium bypass. If no safe candidate exists, stop with gates OFF.
