"""Routing policy and fallback.

Two steps:
1. plan(): decide WHICH providers may serve the request and in WHAT ORDER.
   - Data rule first (always applied, whatever the policy): sensitivity=high means only local
     providers are allowed. This is a hard filter, not a preference.
   - Then the policy orders the remaining providers:
       cost        cheapest price per token first
       latency     lowest observed latency first
       data_policy local providers first, then cheapest
   - A pinned model (anything other than "auto") moves its provider to the front.
2. execute(): try the providers in that order, each at most once, one after the other.
   The first success wins; on ProviderError we fall back to the next one.
"""

import time
from dataclasses import dataclass, field
from enum import StrEnum

from opentelemetry import trace

from app.pricing import price_for
from app.providers import Provider, ProviderError, ProviderResult
from app.schemas import ChatMessage
from app.telemetry import tracer


class Policy(StrEnum):
    COST = "cost"
    LATENCY = "latency"
    DATA_POLICY = "data_policy"


class Sensitivity(StrEnum):
    LOW = "low"
    HIGH = "high"


class RoutingError(Exception):
    """The request cannot be routed at all (bad hint, forbidden model, nothing available)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class AllProvidersFailed(Exception):
    def __init__(self, errors: list[ProviderError]) -> None:
        super().__init__("; ".join(str(e) for e in errors))
        self.errors = errors


@dataclass
class RoutePlan:
    policy: Policy
    sensitivity: Sensitivity
    candidates: list[Provider]


@dataclass
class RouteOutcome:
    result: ProviderResult
    provider: Provider
    latency_ms: float
    failed: list[ProviderError] = field(default_factory=list)

    @property
    def fallback_used(self) -> bool:
        return bool(self.failed)


class Router:
    # Weight of the newest sample in the moving average of latency (0..1).
    LATENCY_ALPHA = 0.3

    def __init__(
        self, providers: dict[str, Provider], default_policy: Policy, failure_penalty_ms: float
    ) -> None:
        self.providers = providers
        self.default_policy = default_policy
        self.failure_penalty_ms = failure_penalty_ms
        # Exponentially weighted moving average per provider, in milliseconds. In-memory and
        # per process: each replica learns on its own, which is good enough for ordering.
        self.latency_ms: dict[str, float] = {}

    def plan(self, model: str, metadata: dict[str, str]) -> RoutePlan:
        policy = self._parse(Policy, metadata.get("policy"), self.default_policy, "policy")
        sensitivity = self._parse(
            Sensitivity, metadata.get("sensitivity"), Sensitivity.LOW, "sensitivity"
        )

        allowed = list(self.providers.values())
        if sensitivity is Sensitivity.HIGH:
            allowed = [p for p in allowed if p.is_local]
        if not allowed:
            raise RoutingError(503, "no provider is allowed for this request")

        ordered = sorted(allowed, key=lambda p: self._sort_key(policy, p))

        if model != "auto":
            pinned = [p for p in ordered if p.model == model]
            if not pinned:
                if any(p.model == model for p in self.providers.values()):
                    raise RoutingError(403, f"model {model!r} is not allowed for this request")
                raise RoutingError(404, f"unknown model {model!r}")
            ordered = pinned + [p for p in ordered if p not in pinned]

        return RoutePlan(policy=policy, sensitivity=sensitivity, candidates=ordered)

    async def execute(
        self,
        plan: RoutePlan,
        messages: list[ChatMessage],
        max_tokens: int,
        temperature: float | None,
    ) -> RouteOutcome:
        # Sequential, never parallel ("hedged") calls: only one provider is working on the
        # request at any time, so we never pay two providers for the same answer on purpose.
        failed: list[ProviderError] = []
        for attempt, provider in enumerate(plan.candidates, start=1):
            started = time.perf_counter()
            with tracer.start_as_current_span("relay.provider_call") as span:
                span.set_attribute("relay.provider", provider.name)
                span.set_attribute("relay.model", provider.model)
                span.set_attribute("relay.attempt", attempt)
                try:
                    result = await provider.complete(messages, max_tokens, temperature)
                except ProviderError as exc:
                    span.set_attribute("relay.outcome", "error")
                    span.set_attribute("relay.error", exc.reason)
                    span.set_status(trace.StatusCode.ERROR, exc.reason)
                    failed.append(exc)
                    # A failing provider gets a big latency sample so the latency policy stops
                    # preferring it until it recovers.
                    self._record_latency(provider.name, self.failure_penalty_ms)
                    continue  # leaving the `with` block also ends the span
                span.set_attribute("relay.outcome", "success")
                span.set_attribute("relay.prompt_tokens", result.prompt_tokens)
                span.set_attribute("relay.completion_tokens", result.completion_tokens)
            latency_ms = (time.perf_counter() - started) * 1000
            self._record_latency(provider.name, latency_ms)
            return RouteOutcome(result, provider, latency_ms, failed)
        raise AllProvidersFailed(failed)

    def _sort_key(self, policy: Policy, provider: Provider) -> tuple[float, ...]:
        cost = float(price_for(provider.model, provider.is_local).blended)
        if policy is Policy.COST:
            return (cost,)
        if policy is Policy.LATENCY:
            # A provider with no sample yet sorts first, so it gets measured once.
            return (self.latency_ms.get(provider.name, 0.0),)
        return (0 if provider.is_local else 1, cost)  # DATA_POLICY

    def _record_latency(self, name: str, sample_ms: float) -> None:
        previous = self.latency_ms.get(name)
        if previous is None:
            self.latency_ms[name] = sample_ms
        else:
            self.latency_ms[name] = (
                self.LATENCY_ALPHA * sample_ms + (1 - self.LATENCY_ALPHA) * previous
            )

    @staticmethod
    def _parse[E: StrEnum](enum: type[E], raw: str | None, default: E, field_name: str) -> E:
        if raw is None:
            return default
        try:
            return enum(raw)
        except ValueError:
            allowed = ", ".join(e.value for e in enum)
            raise RoutingError(
                400, f"invalid {field_name} {raw!r}; use one of: {allowed}"
            ) from None
