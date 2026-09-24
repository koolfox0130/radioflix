"""Small, secret-free audit trail for weekly cancellation requests."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def append_weekly_cancel_audit(record):
    path = Path(os.getenv("RADIOFLIX_AUDIT_PATH", "/data/weekly-cancel-audit.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def audit_timestamp():
    return datetime.now(timezone.utc).isoformat()
