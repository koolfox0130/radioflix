# Phase 4 checkpoint 2: one-job acceptance

Checkpoint 2 separates a manually approved, process-scoped acceptance run from the daemon controller loop. It accepts only an existing 32-character lowercase hexadecimal job ID and exits after one attempt or proof-based recovery. It never creates jobs, starts discovery/scheduling, or starts a server/controller.

## Invocation and approval

```sh
python -m radioflix.timefree.acceptance --accept-job <JOB_ID>
```

`--accept-job` is required by argparse. The operator also supplies `RADIOFLIX_TIMEFREE_ACCEPT_APPROVAL_FILE`, which must name an absolute, non-symlink JSON file owned by the executing UID, mode 0400 or 0600, at most 2 KiB, and expiring within 30 minutes. Its exact schema binds `approved: true` to that job ID. It grants only the bridge approval for this invocation. It cannot override boot mode, the Timefree write gate, local readiness, native conflict checks, duplicate checks, or publication checks. No secrets belong in this file.

Unknown IDs reject without constructing the capture stack. Existing `completed`, `failed`, `cancelled`, and `expired` jobs return a terminal result without capture or mutation; `completed` is a read-only no-op. A running/unknown job is reconciled only from durable publication intent, manifest, and audio proof; absent proof it stays `unknown` and is never recaptured.

## Capture guard and single-job scope

Capture still requires all four conditions in the shared runtime policy:

```text
boot mode enabled
AND RADIOFLIX_TIMEFREE_ENABLE_WRITES=1
AND ready=true
AND bridge_approved=true
```

`RFRIENDS_ENABLE_WRITES` is intentionally absent. The acceptance adapter calls `accept_one(job_id)`, which acquires the existing exclusive worker lock, rereads only the requested row, and passes that ID to target-filtered recovery and dispatch. Other queued rows are not reconciled, selected, or dispatched. Concurrency is one; no background tasks or polling loop are created.

There is no acceptance-level recapture retry: the target gets at most one capture attempt. Known capture/transcode/validation failures become `failed` without publication. Uncertain state is handled by the existing recovery contract and never retried automatically. Existing transport-level retries remain bounded at up to three attempts per request and eight wire requests per process; those do not restart a job capture.

The ordinary `run_once()` remains the daemon's one-tick operation. It may be called repeatedly by `Controller` and, with no ID, reconciles/selects among jobs. It does not provide the mandatory-ID, target-only, process-exit contract of this CLI.

## Fixture evidence

`backend/tests/test_timefree_acceptance.py` uses two queued fixture jobs, fake capture ports, a temporary SQLite store and publish root. Its checks cover the normal `queued → running → completed` path, exact target-only operation, bounded/no retry, terminal no-op, process exit, guard failures, failures before publish, native conflict at start and pre-publish, no-overwrite, and recovery from pre-capture through atomic publish. Run it in a network namespace. It does not use production transport or contact Radiko/Smartstream.

Checkpoint 2 verification completed with backend discovery at 436 tests: 435 passed, 0 failures, 0 errors, 1 skip. The skip is the existing legacy PHP Timefree integration requiring an absent pinned PHP source fixture. Capture/guard/acceptance tests passed 180; catalog/API/reservation/schedule/Timefree/runtime/gate tests passed 246 with the same skip. The acceptance module passed 16 tests, including process exit and recovery.

## Production boundary

The [acceptance runbook](radioflix-timefree-acceptance-runbook.md) is documentation only and was not executed for this checkpoint. A fixture pass does not approve a live job. Image revision, worker/root/socket permissions, backend-to-worker health, and production gates must be re-audited separately; a compatible candidate must fit the unchanged capture duration and transport budgets. No production Docker change, gate change, job, capture, or publication is part of checkpoint 2.
