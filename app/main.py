"""FastAPI application: routes and startup/shutdown (lifespan)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request

from app.config import get_settings
from app.providers import Provider, build_providers
from app.router import AllProvidersFailed, Policy, Router, RoutingError
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
        providers = build_providers(settings, client)
        app.state.providers = providers
        app.state.router = Router(
            providers,
            default_policy=Policy(settings.default_policy),
            failure_penalty_ms=settings.provider_timeout_s * 1000,
        )
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
    router: Router = request.app.state.router

    try:
        plan = router.plan(body.model, body.metadata)
        outcome = await router.execute(plan, body.messages, body.max_tokens, body.temperature)
    except RoutingError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except AllProvidersFailed as exc:
        raise HTTPException(502, f"all providers failed: {exc}") from exc

    result = outcome.result
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
        relay=RelayInfo(provider=outcome.provider.name, fallback_used=outcome.fallback_used),
    )
