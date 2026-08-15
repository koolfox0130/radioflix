from typing import Optional

from radioflix.services.local_ai_client import LocalAIClient, LocalAIResult


class AIService:
    """Minimal AI service facade that delegates to LocalAIClient.

    Responsibilities:
    - Hold a `LocalAIClient` instance (injected or created)
    - Expose `health()`, `available()`, and `ask()` that return LocalAIResult
    - Do not raise on communication errors; propagate LocalAIResult as-is
    """

    def __init__(self, client: Optional[LocalAIClient] = None) -> None:
        self.client = client if client is not None else LocalAIClient()

    def health(self) -> LocalAIResult:
        try:
            return self.client.health()
        except Exception:
            # Fail-closed: return unreachable result rather than raising
            return LocalAIResult(ok=False, error="unreachable")

    def available(self) -> bool:
        res = self.health()
        return bool(res.ok)

    def ask(self, prompt: str) -> LocalAIResult:
        try:
            return self.client.ask(prompt)
        except Exception:
            return LocalAIResult(ok=False, error="unreachable")
