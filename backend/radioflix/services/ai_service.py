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

    def recommendation_reason(
        self,
        title: str,
        network: str,
        existing_reason: str,
        favorite_titles: list[str],
    ) -> LocalAIResult:
        """Generate a short recommendation reason for a candidate program.

        Returns a LocalAIResult. Does not raise.
        """
        # Input validation
        if not title or not title.strip():
            return LocalAIResult(ok=False, error="invalid_title")

        # Prepare favorite titles: filter empties and limit to 6
        favs = [t for t in (favorite_titles or []) if isinstance(t, str) and t.strip()]
        if len(favs) > 6:
            favs = favs[:6]

        # Build Japanese prompt according to spec
        prompt_lines = [
            "あなたはRadioFlixのおすすめ理由作成係です。",
            "",
            "ユーザーが好きな番組:",
        ]

        if favs:
            for f in favs:
                prompt_lines.append(f"- {f}")
        else:
            prompt_lines.append("- （なし）")

        prompt_lines += [
            "",
            "おすすめ候補:",
            f"番組名: {title}",
            f"放送局: {network}",
            f"参考理由: {existing_reason}",
            "",
            "与えられた情報だけを使い、このユーザー向けのおすすめ理由を40～80文字程度の自然な日本語1文で書いてください。",
            "知らない番組内容は推測しないでください。理由文だけを返してください。共通点を1つだけ示してください。",
        ]

        prompt = "\n".join(prompt_lines)

        try:
            res = self.client.ask(prompt)
        except Exception:
            return LocalAIResult(ok=False, error="unreachable")

        # Propagate failures from client unchanged
        if not res.ok:
            return res

        data = res.data

        # Validate success response
        if not isinstance(data, dict):
            return LocalAIResult(ok=False, status_code=res.status_code, error="invalid_ai_response")

        answer = data.get("answer")

        if not isinstance(answer, str) or not answer.strip():
            return LocalAIResult(ok=False, status_code=res.status_code, error="invalid_ai_response")

        reason_text = answer.strip()

        return LocalAIResult(
            ok=True,
            status_code=res.status_code,
            data={
                "reason": reason_text,
                "model": data.get("model") if isinstance(data.get("model"), str) else data.get("model"),
                "mode": data.get("mode") if isinstance(data.get("mode"), str) else data.get("mode"),
            },
        )
