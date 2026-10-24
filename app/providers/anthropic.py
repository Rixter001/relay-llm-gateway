"""Claude through the Anthropic Messages API (POST /v1/messages)."""

from typing import Any

import httpx

from app.providers.base import Provider, ProviderError, ProviderResult
from app.schemas import ChatMessage

ANTHROPIC_VERSION = "2023-06-01"

_FINISH_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "refusal": "content_filter",
}


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, client: httpx.AsyncClient, model: str, api_key: str, base_url: str) -> None:
        super().__init__(client, model)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def complete(
        self, messages: list[ChatMessage], max_tokens: int, temperature: float | None
    ) -> ProviderResult:
        # Anthropic takes the system prompt as a separate field, not as a message.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages if m.role != "system"
            ],
            # Gateway traffic is mostly chat-style, so ask for low reasoning effort to keep
            # latency and output-token cost down.
            "output_config": {"effort": "low"},
        }
        if system:
            payload["system"] = system
        # `temperature` is intentionally not forwarded: the Messages API rejects sampling
        # parameters on current models.

        body = await self._post_json(
            f"{self.base_url}/v1/messages",
            payload,
            headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
        )
        try:
            # The response is a list of content blocks; only "text" blocks are the answer
            # (current models can also return "thinking" blocks, which we skip).
            text = "".join(b["text"] for b in body["content"] if b.get("type") == "text")
            usage = body["usage"]
            return ProviderResult(
                text=text,
                model=body.get("model", self.model),
                prompt_tokens=int(usage["input_tokens"]),
                completion_tokens=int(usage["output_tokens"]),
                finish_reason=_FINISH_REASONS.get(body.get("stop_reason", ""), "stop"),
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError(self.name, "unexpected response shape") from exc
