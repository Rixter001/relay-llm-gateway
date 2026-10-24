"""Ollama, the local provider (POST /api/chat). Data sent here never leaves our network."""

from typing import Any

import httpx

from app.providers.base import Provider, ProviderError, ProviderResult
from app.schemas import ChatMessage


class OllamaProvider(Provider):
    name = "ollama"
    is_local = True

    def __init__(self, client: httpx.AsyncClient, model: str, base_url: str) -> None:
        super().__init__(client, model)
        self.base_url = base_url.rstrip("/")

    async def complete(
        self, messages: list[ChatMessage], max_tokens: int, temperature: float | None
    ) -> ProviderResult:
        options: dict[str, Any] = {"num_predict": max_tokens}
        if temperature is not None:
            options["temperature"] = temperature
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": options,
        }
        body = await self._post_json(f"{self.base_url}/api/chat", payload)
        try:
            return ProviderResult(
                text=body["message"]["content"],
                model=body.get("model", self.model),
                prompt_tokens=int(body.get("prompt_eval_count", 0)),
                completion_tokens=int(body.get("eval_count", 0)),
                finish_reason="length" if body.get("done_reason") == "length" else "stop",
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError(self.name, "unexpected response shape") from exc
