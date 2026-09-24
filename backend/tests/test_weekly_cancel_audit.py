import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, Response

from radioflix.api.reservations import reservation_router
from radioflix.schemas.reservations import RecordingError


class FakeService:
    def __init__(self, fail=False):
        self.fail = fail

    def cancel_subscription(self, subscription_id, audit):
        audit("subscription_found", success=True)
        audit("reservation_cancel_start", success=True, reservation_id="reservation-safe-id")
        if self.fail:
            audit("gateway_cancel_result", success=False, error_code="timeout")
            raise RecordingError("unconfirmed", "解除結果を確認できません。", True)
        audit("gateway_cancel_result", success=True, gateway_state="cancelled")
        audit("db_update_result", success=True, subscription_state="cancelled", reservation_state="cancelled")
        return {"id": subscription_id, "state": "cancelled", "schedule_state": "cancelled"}


class WeeklyCancelAuditTests(unittest.TestCase):
    def exercise(self, fail):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = str(Path(temporary.name) / "weekly-cancel-audit.jsonl")
        route = next(route for route in reservation_router(FakeService(fail), object()).routes
                     if getattr(route, "path", None) == "/api/subscriptions/{subscription_id}")
        response = Response()
        with patch.dict(os.environ, {"RADIOFLIX_AUDIT_PATH": path}):
            try:
                result = route.endpoint("subscription-safe-id", response)
            except HTTPException as error:
                result = error
        rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
        return response, result, rows

    def test_success_audit_is_durable_and_secret_free(self):
        response, result, rows = self.exercise(False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(response.headers["X-Request-ID"], rows[0]["request_id"])
        self.assertEqual([row["stage"] for row in rows], [
            "request_received", "subscription_found", "reservation_cancel_start",
            "gateway_cancel_result", "db_update_result", "request_completed",
        ])
        self.assertEqual(rows[-1]["http_status"], 200)
        self.assertTrue(rows[-1]["success"])
        self.assertTrue(all(row["subscription_id"] == "subscription-safe-id" for row in rows))
        self.assertTrue(all(row["timestamp_utc"].endswith("+00:00") for row in rows))
        self.assertTrue(all("authorization" not in json.dumps(row).lower() for row in rows))

    def test_failure_audit_records_http_status_and_outcome(self):
        response, result, rows = self.exercise(True)
        self.assertEqual(response.status_code, 503)
        self.assertIsInstance(result, HTTPException)
        self.assertEqual([row["stage"] for row in rows][-1], "request_failed")
        self.assertEqual(rows[-1]["http_status"], 503)
        self.assertFalse(rows[-1]["success"])
        self.assertFalse(next(row for row in rows if row["stage"] == "gateway_cancel_result")["success"])
