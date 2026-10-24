from datetime import UTC, datetime
from decimal import Decimal

import fakeredis
import httpx
import pytest
import respx
from fakes import OLLAMA_URL, ollama_body
from fastapi import HTTPException
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.auth import Team, TeamDirectory, hash_key
from app.limits import Limiter, budget_key


def team(**overrides: object) -> Team:
    fields: dict[str, object] = {"name": "t", "api_key_sha256": hash_key("k")} | overrides
    return Team.model_validate(fields)


@pytest.fixture
def redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


def test_team_directory_finds_by_key_hash() -> None:
    directory = TeamDirectory([team(name="finance", api_key_sha256=hash_key("secret-1"))])
    found = directory.find("secret-1")
    assert found is not None and found.name == "finance"
    assert directory.find("secret-2") is None


async def test_rate_limit_blocks_after_n_requests(redis: fakeredis.aioredis.FakeRedis) -> None:
    limiter = Limiter(redis)
    t = team(rate_limit_per_minute=3)
    for _ in range(3):
        await limiter.check_rate_limit(t)
    with pytest.raises(HTTPException) as excinfo:
        await limiter.check_rate_limit(t)
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers is not None and "Retry-After" in excinfo.value.headers


async def test_budget_is_enforced_once_spent(redis: fakeredis.aioredis.FakeRedis) -> None:
    limiter = Limiter(redis)
    t = team(monthly_budget_usd=1.0)
    await limiter.check_budget(t)
    await limiter.record_spend(t, Decimal("0.6"))
    await limiter.check_budget(t)  # 0.60 < 1.00: still allowed
    await limiter.record_spend(t, Decimal("0.4"))
    with pytest.raises(HTTPException) as excinfo:
        await limiter.check_budget(t)
    assert excinfo.value.status_code == 402
    assert await limiter.spent_usd(t) == Decimal("1")


async def test_spend_is_stored_as_integer_micro_dollars_per_month(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    limiter = Limiter(redis)
    await limiter.record_spend(team(), Decimal("0.0000101"))  # rounded UP to 11 micro-dollars
    assert await redis.get(budget_key("t", datetime.now(UTC))) == b"11"


async def test_no_budget_means_unlimited(redis: fakeredis.aioredis.FakeRedis) -> None:
    limiter = Limiter(redis)
    await limiter.record_spend(team(), Decimal("1000"))
    await limiter.check_budget(team(monthly_budget_usd=None))


async def test_redis_down_fails_closed() -> None:
    class BrokenRedis(fakeredis.aioredis.FakeRedis):
        async def get(self, *args: object, **kwargs: object) -> None:
            raise RedisConnectionError("down")

    limiter = Limiter(BrokenRedis())
    with pytest.raises(HTTPException) as excinfo:
        await limiter.check_budget(team(monthly_budget_usd=5.0))
    assert excinfo.value.status_code == 503


# --- Through the API -------------------------------------------------------------------------

CHAT = {"messages": [{"role": "user", "content": "Hi"}], "metadata": {"sensitivity": "high"}}


def test_missing_or_wrong_key_is_rejected(client: TestClient) -> None:
    client.headers.pop("Authorization")
    assert client.post("/v1/chat/completions", json=CHAT).status_code == 401
    assert client.get("/v1/models").status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.post("/v1/chat/completions", json=CHAT, headers=bad).status_code == 401


@respx.mock
def test_rate_limit_through_api(client: TestClient) -> None:
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=ollama_body("ok")))
    limited = {"Authorization": "Bearer limited-key"}  # 2 requests/minute in conftest
    statuses = [
        client.post("/v1/chat/completions", json=CHAT, headers=limited).status_code
        for _ in range(3)
    ]
    assert statuses == [200, 200, 429]


@respx.mock
def test_budget_through_api(client: TestClient) -> None:
    provider = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=ollama_body("ok")))
    broke = {"Authorization": "Bearer broke-key"}  # budget of $0 in conftest
    response = client.post("/v1/chat/completions", json=CHAT, headers=broke)
    assert response.status_code == 402
    assert not provider.called  # refused before anything left Relay
