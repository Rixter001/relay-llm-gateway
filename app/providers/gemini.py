"""Gemini through the Google Generative Language API (models/{model}:generateContent)."""

from typing import Any

import httpx

from app.providers.base import Provider, ProviderError, ProviderResult
from app.schemas import ChatMessage

_FINISH_REASONS = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter"}


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, client: httpx.AsyncClient, model: str, api_key: str, base_url: str) -> None:
        super().__init__(client, model)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def complete(
        self, messages: list[ChatMessage], max_tokens: int, temperature: float | None
    ) -> ProviderResult:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        generation_config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            generation_config["temperature"] = temperature
        payload: dict[str, Any] = {
            # Gemini calls the assistant role "model".
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in messages
                if m.role != "system"
            ],
            "generationConfig": generation_config,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        # The key goes in a header, not in the ?key= query string, so it never shows up
        # in access logs or traces that record URLs.
        body = await self._post_json(
            f"{self.base_url}/v1beta/models/{self.model}:generateContent",
            payload,
            headers={"x-goog-api-key": self.api_key},
        )
        try:
            candidate = body["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
            usage = body.get("usageMetadata", {})
            return ProviderResult(
                text="".join(p.get("text", "") for p in parts),
                model=self.model,
                prompt_tokens=int(usage.get("promptTokenCount", 0)),
                # "Thinking" tokens are billed as output tokens, so count them too.
                completion_tokens=int(usage.get("candidatesTokenCount", 0))
                + int(usage.get("thoughtsTokenCount", 0)),
                finish_reason=_FINISH_REASONS.get(candidate.get("finishReason", ""), "stop"),
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, "unexpected response shape") from exc
