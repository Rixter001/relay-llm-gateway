"""Synchronous client for Relay's OpenAI-compatible API."""

import os
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

import httpx


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class ChatResult:
    content: str
    model: str
    provider: str
    fallback_used: bool
    masked_entities: int
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    # The prompt exactly as the provider saw it (placeholders instead of PII). Only filled
    # when the Relay server runs with RELAY_DEBUG_SHOW_MASKED_PROMPT=true.
    masked_messages: list[Message] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class RelayError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Relay returned {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class RelayClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        base_url = base_url or os.environ.get("RELAY_BASE_URL", "http://localhost:8000")
        api_key = api_key or os.environ.get("RELAY_API_KEY")
        if not api_key:
            raise ValueError("an API key is required (argument or RELAY_API_KEY)")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    def chat(
        self,
        messages: str | list[Message],
        *,
        model: str = "auto",
        policy: Literal["cost", "latency", "data_policy"] | None = None,
        sensitivity: Literal["low", "high"] | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> ChatResult:
        """Send a chat request. A plain string is sent as a single user message."""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        metadata: dict[str, str] = {}
        if policy:
            metadata["policy"] = policy
        if sensitivity:
            metadata["sensitivity"] = sensitivity
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "metadata": metadata,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        body = self._request("POST", "/v1/chat/completions", json=payload)
        relay = body.get("relay", {})
        usage = body.get("usage", {})
        return ChatResult(
            content=body["choices"][0]["message"]["content"],
            model=body["model"],
            provider=relay.get("provider", ""),
            fallback_used=relay.get("fallback_used", False),
            masked_entities=relay.get("masked_entities", 0),
            cost_usd=relay.get("cost_usd", 0.0),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            masked_messages=relay.get("masked_messages"),
            raw=body,
        )

    def models(self) -> list[str]:
        return [m["id"] for m in self._request("GET", "/v1/models")["data"]]

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                message = response.json().get("detail", response.text)
            except ValueError:
                message = response.text
            raise RelayError(response.status_code, str(message))
        data: dict[str, Any] = response.json()
        return data

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "RelayClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
