"""Request and response shapes of the OpenAI-compatible API.

Only the fields Relay actually uses are modelled. Unknown OpenAI parameters (top_p,
presence_penalty, ...) are accepted and ignored so that existing OpenAI clients keep working.
"""

import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: Role
    # Plain text only. OpenAI's multi-part content (images, audio) is out of scope.
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # "auto" lets the routing policy pick the provider; a concrete model id pins it.
    model: str = "auto"
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int = Field(default=1024, ge=1, le=32_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    stream: bool = False
    # OpenAI's standard free-form metadata map. Relay reads two keys from it:
    #   policy:      "cost" | "latency" | "data_policy"
    #   sensitivity: "low" | "high"   (high = local provider only)
    metadata: dict[str, str] = Field(default_factory=dict)


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str


class RelayInfo(BaseModel):
    """Relay-specific extension of the response, so callers can see what happened."""

    provider: str
    fallback_used: bool
    masked_entities: int = 0
    cost_usd: float = 0.0
    # Only filled when RELAY_DEBUG_SHOW_MASKED_PROMPT=true (used by `make demo`).
    masked_messages: list[ChatMessage] | None = None


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[Choice]
    usage: Usage
    relay: RelayInfo


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    owned_by: str


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]
