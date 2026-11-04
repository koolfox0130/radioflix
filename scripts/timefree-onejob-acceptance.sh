#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$(mktemp -d /tmp/radioflix-onejob.XXXXXXXX)"
chmod 0711 "$RUN_DIR"
RUN_PID=""
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ -n "$RUN_PID" ]] && kill -0 "$RUN_PID" 2>/dev/null; then
    kill -TERM "$RUN_PID"
    wait "$RUN_PID" || true
  fi
  if ! python3 "$ROOT/scripts/timefree_onejob_runner.py" --cleanup "$RUN_DIR"; then
    rm -f -- "$RUN_DIR/approval.json" "$RUN_DIR/admission.json"
    printf 'Cleanup incomplete; preserve %s for read-only recovery\n' "$RUN_DIR" >&2
    exit 1
  fi
  rm -f -- "$RUN_DIR/approval.json" "$RUN_DIR/admission.json" "$RUN_DIR/owner.json"
  rmdir -- "$RUN_DIR" || rc=1
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 "$ROOT/scripts/timefree_onejob_runner.py" --run-dir "$RUN_DIR" "$@" &
RUN_PID=$!
wait "$RUN_PID"
