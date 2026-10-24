# RadioFlix Development Status

## Last updated
2026-10-24 17:28:21 JST

## Current task
BLOCK 1: checkpoint review and push for observation docs + schedule UI wait stabilization; next investigate auth2 401 using the three requested evidence tracks.

## Current phase
Phase 4 Radiko observation checkpoint being committed; no additional Radiko request during checkpoint work.

## Status
ready_to_commit

## Completed
- Reviewed full diffs for `docs/dev-log/latest.md`, runtime/source-api/validation docs, and `frontend/tests/schedule-ui.mjs`; changes match the previous observation and schedule test stabilization.
- Prior live observation and complete offline regression results are recorded below; current safety remains fail-closed.

## In progress
- Explicitly stage the reviewed docs/test and the matching 2026-10-24 observation history snapshot, run staged diff/secret checks, then create and push one checkpoint. Preserve unrelated untracked files.

## Next actions
1. Commit the reviewed observation/docs + schedule test checkpoint and push `origin/main`.
2. Verify HEAD, origin/main, and remote ref match.
3. Continue BLOCK 2 source-only comparison of endpoint/session, partial-key generation, and auth profile; run at most 2–3 evidence-based auth candidates only if no safer resolution exists.

## Blockers / Issues
- Previous auth2 response was 401; body and sensitive header values were not inspected. No retry/playlist request occurred after that response.
- Effective station-specific `rf_premium_mode()` remains unknown. Production HTTP is still unsafe to implement.

## Files changed
- Reviewed tracked files: `docs/dev-log/latest.md`, `docs/radioflix-timefree-phase4-validation.md`, `docs/radioflix-timefree-runtime.md`, `docs/radioflix-timefree-source-api.md`, `frontend/tests/schedule-ui.mjs`.
- Matching observation history: `docs/dev-log/history/2026-10-24_1511_radiko-observation-stopped.md`.
- All other untracked history, `.codex/`, and Dockerfile backups remain excluded and untouched.

## Git state
branch main; HEAD `7a5eae1ef83d3827fcfc0bab268d0c926f4d9350` = origin/main before checkpoint. Reviewed changes are not committed yet. Only explicit target files will be staged; no reset/restore/add -A.

## Tests
Previously completed for this reviewed set: backend 257 PASS / 0 skipped; Python compileall PASS; PHP syntax 5 files PASS; schedule UI 148 checks x3 PASS after wait stabilization; reservation 24 PASS; playback/navigation 21 PASS; typecheck PASS; lint 0 errors/5 warnings; build PASS. `git diff --check` PASS. Rerun staged diff check and secret scan before commit.

## Runtime / Safety
- Last observed: `RFRIENDS_ENABLE_WRITES=0`, `RADIOFLIX_TIMEFREE_ENABLE_WRITES` unset/OFF; active RadioFlix reservation=0, weekly=0, timefree jobs=0/table absent. rfriends3 running/no healthcheck. Native dat/sh and atq fingerprints were unchanged before/after.
- Previous live traffic was limited to DNS/TLS and playerCommon/auth1/auth2. auth2=401. No playlist/HLS/segment, ffmpeg, recording, gate change, deploy/restart, native write, or publisher operation.
- `ready=false`, `bridge_approved=false`; no credential/token/cookie/header values were emitted or persisted.

## Important decisions
- Commit only the reviewed observation docs, schedule test stabilization, and matching history snapshot; exclude unrelated untracked files.
- During BLOCK 2 keep to the three evidence tracks and no arbitrary credential/profile brute force. Never display/persist secrets.

## Recovery instructions
After push, continue auth2 401 diagnosis from endpoint/session, partial key, and auth profile evidence. Preserve fail-closed flags and all unrelated worktree files. No audio segments, ffmpeg, recording, gate ON, deploy, or rfriends3/native modifications.

## at spool調査（2026-10-14、read-only）
- 10/12 before/after atjobs hash差は、17:25のrfriends3定時cronを挟んでおり、通常cronによるnative予約at job再生成が最有力。dat/sh aggregate hashと中身はbefore/after/currentで同一。
- RadioFlix隔離試験はproduction queue/mount非接続。at spool差分はRadioFlix操作由来ではないと判断。前後のjob ID別一覧がなく旧ID単位の削除/追加/変更は未確定。放送時刻自然消化よりcron再生成と整合。
- 過去の詳細atq情報は2026-10-14 read-only調査記録と既存history snapshotを参照。今回at/native queue操作なし。
