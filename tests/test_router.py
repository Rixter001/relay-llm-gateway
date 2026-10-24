import httpx
import pytest
import respx
from fakes import ANTHROPIC_URL, GEMINI_URL, OLLAMA_URL, gemini_body, ollama_body
from fastapi.testclient import TestClient

from app.providers.base import Provider, ProviderError, ProviderResult
from app.router import Policy, Router, RoutingError
from app.schemas import ChatMessage

MESSAGES = [ChatMessage(role="user", content="Hi")]


class FakeProvider(Provider):
    """In-memory provider: either answers or raises, and records how often it was called."""

    def __init__(self, name: str, model: str, is_local: bool = False, fail: bool = False) -> None:
        super().__init__(client=None, model=model)  # type: ignore[arg-type]
        self.name = name
        self.is_local = is_local
        self.fail = fail
        self.calls = 0

    async def complete(
        self, messages: list[ChatMessage], max_tokens: int, temperature: float | None
    ) -> ProviderResult:
        self.calls += 1
        if self.fail:
            raise ProviderError(self.name, "HTTP 503")
        return ProviderResult(f"answer from {self.name}", self.model, 1, 1, "stop")


def make_router(**fail: bool) -> tuple[Router, dict[str, FakeProvider]]:
    providers = {
        "anthropic": FakeProvider(
            "anthropic", "claude-opus-5-5", fail=fail.get("anthropic", False)
        ),
        "gemini": FakeProvider("gemini", "gemini-2.5-flash", fail=fail.get("gemini", False)),
        "ollama": FakeProvider("ollama", "llama3", is_local=True, fail=fail.get("ollama", False)),
    }
    return Router(dict(providers), Policy.COST, failure_penalty_ms=60_000), providers


def names(router: Router, model: str = "auto", **metadata: str) -> list[str]:
    return [p.name for p in router.plan(model, metadata).candidates]


def test_cost_policy_orders_cheapest_first() -> None:
    router, _ = make_router()
    assert names(router, policy="cost") == ["ollama", "gemini", "anthropic"]


def test_data_policy_puts_local_first() -> None:
    router, _ = make_router()
    assert names(router, policy="data_policy")[0] == "ollama"


def test_high_sensitivity_only_allows_local_whatever_the_policy() -> None:
    router, _ = make_router()
    for policy in ("cost", "latency", "data_policy"):
        assert names(router, policy=policy, sensitivity="high") == ["ollama"]


def test_pinned_cloud_model_is_refused_for_high_sensitivity() -> None:
    router, _ = make_router()
    with pytest.raises(RoutingError) as excinfo:
        router.plan("claude-opus-5-5", {"sensitivity": "high"})
    assert excinfo.value.status_code == 403


def test_pinned_model_goes_first_then_others_as_fallback() -> None:
    router, _ = make_router()
    assert names(router, "claude-opus-5-5") == ["anthropic", "ollama", "gemini"]


def test_unknown_model_and_bad_hints_are_rejected() -> None:
    router, _ = make_router()
    for model, metadata, status in [
        ("gpt-9", {}, 404),
        ("auto", {"policy": "fastest"}, 400),
        ("auto", {"sensitivity": "secret"}, 400),
    ]:
        with pytest.raises(RoutingError) as excinfo:
            router.plan(model, metadata)
        assert excinfo.value.status_code == status


async def test_latency_policy_learns_from_measurements() -> None:
    router, _ = make_router()
    router.latency_ms = {"anthropic": 900.0, "gemini": 200.0, "ollama": 1500.0}
    assert names(router, policy="latency") == ["gemini", "anthropic", "ollama"]


async def test_fallback_tries_next_provider_once_each() -> None:
    router, providers = make_router(ollama=True)
    plan = router.plan("auto", {"policy": "cost"})
    outcome = await router.execute(plan, MESSAGES, 10, None)

    assert outcome.provider.name == "gemini"
    assert outcome.fallback_used
    assert [p.calls for p in providers.values()] == [0, 1, 1]  # anthropic never called
    # The failure is remembered as a large latency sample.
    assert router.latency_ms["ollama"] == 60_000


async def test_no_fallback_outside_allowed_providers() -> None:
    router, providers = make_router(ollama=True)
    plan = router.plan("auto", {"sensitivity": "high"})
    with pytest.raises(Exception, match="ollama"):
        await router.execute(plan, MESSAGES, 10, None)
    assert providers["anthropic"].calls == providers["gemini"].calls == 0


@respx.mock
def test_api_falls_back_on_timeout(client: TestClient) -> None:
    respx.post(OLLAMA_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=gemini_body("from gemini")))
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Hi"}], "metadata": {"policy": "cost"}},
    )
    assert response.status_code == 200
    assert response.json()["relay"] == {
        "provider": "gemini",
        "fallback_used": True,
        "masked_entities": 0,
        "cost_usd": 0.0,
        "masked_messages": None,
    }


@respx.mock
def test_api_returns_502_when_every_allowed_provider_fails(client: TestClient) -> None:
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(500))
    cloud = respx.post(ANTHROPIC_URL)
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hi"}],
            "metadata": {"sensitivity": "high"},
        },
    )
    assert response.status_code == 502
    assert not cloud.called


@respx.mock
def test_api_high_sensitivity_goes_to_ollama(client: TestClient) -> None:
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=ollama_body("local")))
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hi"}],
            "metadata": {"policy": "cost", "sensitivity": "high"},
        },
    )
    assert response.json()["relay"]["provider"] == "ollama"
