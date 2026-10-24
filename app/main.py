"""FastAPI application: routes and startup/shutdown (lifespan)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request

from app.config import get_settings
from app.providers import Provider, ProviderError, build_providers
from app.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ModelCard,
    ModelList,
    RelayInfo,
    Usage,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # One shared HTTP client for the whole process: it keeps TCP/TLS connections to the
    # providers open between requests (connection pooling).
    timeout = httpx.Timeout(
        settings.provider_timeout_s, connect=settings.provider_connect_timeout_s
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        app.state.providers = build_providers(settings, client)
        yield


app = FastAPI(title="Relay", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe used by Docker and Kubernetes."""
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(request: Request) -> ModelList:
    providers: dict[str, Provider] = request.app.state.providers
    cards = [ModelCard(id="auto", owned_by="relay")]
    cards += [ModelCard(id=p.model, owned_by=p.name) for p in providers.values()]
    return ModelList(data=cards)


@app.post("/v1/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request) -> ChatCompletionResponse:
    if body.stream:
        raise HTTPException(400, "stream=true is not supported; Relay is non-streaming")
    providers: dict[str, Provider] = request.app.state.providers
    if not providers:
        raise HTTPException(503, "no provider is configured")

    # Phase 2: a pinned model goes to its provider, "auto" goes to the first configured one.
    provider = next((p for p in providers.values() if p.model == body.model), None)
    provider = provider or next(iter(providers.values()))
    try:
        result = await provider.complete(body.messages, body.max_tokens, body.temperature)
    except ProviderError as exc:
        raise HTTPException(502, f"provider failed: {exc.reason}") from exc

    return ChatCompletionResponse(
        model=result.model,
        choices=[
            Choice(
                message=ChatMessage(role="assistant", content=result.text),
                finish_reason=result.finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
        relay=RelayInfo(provider=provider.name, fallback_used=False),
    )
