import json
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any, Dict, Optional

from urllib import error as urlerror
from urllib import request as urlrequest


@dataclass(frozen=True)
class LocalAIResult:
    ok: bool
    data: Optional[Dict[str, Any]] = None
    status_code: Optional[int] = None
    error: Optional[str] = None


class LocalAIClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        env_url = os.getenv("LOCAL_AI_API_URL")
        self.base_url = (env_url or base_url) if (env_url or base_url) else None
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
        self.logger = logging.getLogger(__name__)

    def _extract_error(self, payload: Any) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        # Common patterns: {"detail": {"error": "..."}} or {"error": "..."}
        detail = payload.get("detail")
        if isinstance(detail, dict):
            err = detail.get("error") or detail.get("message")
            if isinstance(err, str):
                return err
        err = payload.get("error") or payload.get("message")
        if isinstance(err, str):
            return err
        return None

    def health(self, timeout: float = 5.0) -> LocalAIResult:
        if not self.base_url:
            return LocalAIResult(ok=False, error="disabled")

        url = f"{self.base_url}/health"
        req = urlrequest.Request(url, method="GET")
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(body) if body else None
                except Exception:
                    return LocalAIResult(ok=False, status_code=status, error="invalid_json")

                if 200 <= status < 300:
                    return LocalAIResult(ok=True, data=data, status_code=status)

                err = self._extract_error(data)
                return LocalAIResult(ok=False, data=data, status_code=status, error=err or f"http_{status}")

        except urlerror.HTTPError as e:
            status = getattr(e, "code", None)
            try:
                body = e.read().decode("utf-8", errors="replace")
                data = json.loads(body) if body else None
            except Exception:
                data = None
            err = self._extract_error(data) if data is not None else None
            return LocalAIResult(ok=False, data=data, status_code=status, error=err or f"http_{status}")

        except urlerror.URLError as e:
            # urllib may wrap a socket.timeout or TimeoutError in URLError.reason
            reason = getattr(e, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return LocalAIResult(ok=False, error="timeout")
            # Could be DNS failure / connection refused
            self.logger.debug("LocalAI health URLError: %s", e)
            return LocalAIResult(ok=False, error="unreachable")

        except socket.timeout:
            return LocalAIResult(ok=False, error="timeout")

        except Exception:
            self.logger.exception("Unexpected error in LocalAIClient.health")
            return LocalAIResult(ok=False, error="unreachable")

    def ask(self, prompt: str, timeout: float = 120.0) -> LocalAIResult:
        # Validate prompt first to avoid contacting network for invalid input
        if not prompt or not prompt.strip():
            return LocalAIResult(ok=False, error="invalid_prompt")

        if not self.base_url:
            return LocalAIResult(ok=False, error="disabled")

        url = f"{self.base_url}/ask"
        payload = json.dumps({"prompt": prompt}).encode("utf-8")
        req = urlrequest.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        # Avoid logging the full prompt; log only its length
        self.logger.debug("Calling LocalAI ask (prompt_length=%d)", len(prompt))

        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(body) if body else None
                except Exception:
                    return LocalAIResult(ok=False, status_code=status, error="invalid_json")

                if 200 <= status < 300:
                    return LocalAIResult(ok=True, data=data, status_code=status)

                err = self._extract_error(data)
                return LocalAIResult(ok=False, data=data, status_code=status, error=err or f"http_{status}")

        except urlerror.HTTPError as e:
            status = getattr(e, "code", None)
            try:
                body = e.read().decode("utf-8", errors="replace")
                data = json.loads(body) if body else None
            except Exception:
                data = None
            err = self._extract_error(data) if data is not None else None
            return LocalAIResult(ok=False, data=data, status_code=status, error=err or f"http_{status}")

        except urlerror.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return LocalAIResult(ok=False, error="timeout")
            self.logger.debug("LocalAI ask URLError: %s", e)
            return LocalAIResult(ok=False, error="unreachable")

        except socket.timeout:
            return LocalAIResult(ok=False, error="timeout")

        except Exception:
            self.logger.exception("Unexpected error in LocalAIClient.ask")
            return LocalAIResult(ok=False, error="unreachable")
