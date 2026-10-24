"""Common interface for every LLM provider.

Each adapter translates Relay's OpenAI-style messages into the provider's own HTTP format and
translates the answer back into a ProviderResult. The rest of Relay only sees this interface,
so adding a provider means adding one file.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.schemas import ChatMessage


@dataclass
class ProviderResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str  # normalised to OpenAI values: stop, length, content_filter


class ProviderError(Exception):
    """Any failure talking to a provider. The router reacts to it by trying the next provider."""

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(f"{provider}: {reason}")
        self.provider = provider
        self.reason = reason


class Provider(ABC):
    name: str
    # True when the provider runs inside our own infrastructure (data never leaves it).
    is_local: bool = False

    def __init__(self, client: httpx.AsyncClient, model: str) -> None:
        self.client = client
        self.model = model

    @abstractmethod
    async def complete(
        self, messages: list[ChatMessage], max_tokens: int, temperature: float | None
    ) -> ProviderResult:
        """Send one non-streaming chat request and return the normalised result."""

    async def _post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """POST and return the JSON body, converting every failure into a ProviderError.

        The error message deliberately never includes the request body, because the body
        contains the (masked) prompt and errors end up in logs.
        """
        try:
            response = await self.client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"timeout ({type(exc).__name__})") from exc
        except httpx.TransportError as exc:
            raise ProviderError(self.name, f"connection error ({type(exc).__name__})") from exc

        if response.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {response.status_code}")
        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderError(self.name, "invalid JSON in response") from exc
        return body
