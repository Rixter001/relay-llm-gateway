"""FastAPI application: routes and startup/shutdown (lifespan)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from redis.asyncio import Redis
from starlette.concurrency import run_in_threadpool

from app.auth import Team, TeamDirectory, authenticate
from app.config import Settings, get_settings
from app.limits import Limiter
from app.masking import Masker, build_presidio_masker, unmask
from app.pricing import cost_usd
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


def build_masker(settings: Settings) -> Masker:
    """Separate function so tests can replace it with a masker that needs no spaCy model."""
    return build_presidio_masker(settings.masking_languages, None, settings.masking_score_threshold)


def create_redis(settings: Settings) -> Redis:
    """Separate function so tests can swap in an in-memory fake Redis."""
    return Redis.from_url(settings.redis_url, socket_timeout=2)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.teams = TeamDirectory.from_file(settings.teams_file)
    redis = create_redis(settings)
    app.state.limiter = Limiter(redis)
    # Loading the spaCy models takes a while, so it happens once, before serving traffic.
    app.state.masker = build_masker(settings)
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
    await redis.aclose()


app = FastAPI(title="Relay", version="0.1.0", lifespan=lifespan)

# Every /v1 endpoint needs a valid team API key.
CurrentTeam = Annotated[Team, Depends(authenticate)]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe used by Docker and Kubernetes."""
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(request: Request, team: CurrentTeam) -> ModelList:
    providers: dict[str, Provider] = request.app.state.providers
    cards = [ModelCard(id="auto", owned_by="relay")]
    cards += [ModelCard(id=p.model, owned_by=p.name) for p in providers.values()]
    return ModelList(data=cards)


@app.post("/v1/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest, request: Request, team: CurrentTeam
) -> ChatCompletionResponse:
    """The request lifecycle: auth -> limits -> masking -> routing -> provider -> unmasking.

    (Authentication already happened in the `CurrentTeam` dependency.)
    """
    if body.stream:
        raise HTTPException(400, "stream=true is not supported; Relay is non-streaming")
    settings = get_settings()
    router: Router = request.app.state.router
    masker: Masker = request.app.state.masker
    limiter: Limiter = request.app.state.limiter

    # 0. Limits: refused requests cost nothing, because nothing has been sent yet.
    await limiter.check_rate_limit(team)
    await limiter.check_budget(team)

    # 1. Mask PII in every message (system, user and assistant history) with one mapping.
    #    Presidio is CPU-bound and synchronous, so it runs in a worker thread instead of
    #    blocking the event loop (which would stall every other request).
    masked = await run_in_threadpool(masker.mask, [m.content for m in body.messages])
    masked_messages = [
        ChatMessage(role=m.role, content=text)
        for m, text in zip(body.messages, masked.texts, strict=True)
    ]

    # 2. Route and call the provider (with fallback). Only masked text leaves Relay.
    try:
        plan = router.plan(body.model, body.metadata)
        outcome = await router.execute(plan, masked_messages, body.max_tokens, body.temperature)
    except RoutingError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except AllProvidersFailed as exc:
        raise HTTPException(502, f"all providers failed: {exc}") from exc

    # 3. Put the original values back into the answer. The mapping is then dropped with the
    #    request; it is never stored anywhere.
    result = outcome.result
    answer = unmask(result.text, masked.mapping)

    # 4. Charge the team for the ONE call that produced the answer (failed attempts during
    #    fallback returned no usage, so there is nothing to charge for them).
    cost = cost_usd(
        outcome.provider.model,
        outcome.provider.is_local,
        result.prompt_tokens,
        result.completion_tokens,
    )
    await limiter.record_spend(team, cost)

    return ChatCompletionResponse(
        model=result.model,
        choices=[
            Choice(
                message=ChatMessage(role="assistant", content=answer),
                finish_reason=result.finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
        ),
        relay=RelayInfo(
            provider=outcome.provider.name,
            fallback_used=outcome.fallback_used,
            masked_entities=masked.count,
            cost_usd=float(cost),
            masked_messages=masked_messages if settings.debug_show_masked_prompt else None,
        ),
    )
