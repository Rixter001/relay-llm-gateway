import sqlite3
from decimal import Decimal

import httpx
import respx
from fakes import ANTHROPIC_URL, GEMINI_URL, OLLAMA_URL, anthropic_body, ollama_body
from fastapi.testclient import TestClient

from app.config import get_settings
from app.pricing import UNKNOWN_CLOUD_PRICE, cost_usd


def usage_rows() -> list[sqlite3.Row]:
    path = get_settings().database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        return db.execute("SELECT * FROM usage_log ORDER BY id").fetchall()


def test_cost_calculation() -> None:
    # 1000 input tokens x $4/M + 500 output tokens x $20/M = $0.004 + $0.01
    assert cost_usd("claude-opus-5-5", False, 1000, 500) == Decimal("0.014")
    assert cost_usd("llama3", True, 1000, 500) == 0
    # Unknown cloud models are priced like the most expensive known one (safe for budgets).
    assert cost_usd("some-new-model", False, 1_000_000, 0) == UNKNOWN_CLOUD_PRICE.input_per_mtok


@respx.mock
def test_success_is_logged_with_metadata_but_no_content(client: TestClient) -> None:
    respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=anthropic_body("Bonjour <PERSON_1>", 1000, 500))
    )
    client.post(
        "/v1/chat/completions",
        json={
            "model": "claude-opus-5-5",
            "messages": [{"role": "user", "content": "Say hi to Jean Dupont"}],
        },
    )
    (row,) = usage_rows()
    assert row["team"] == "default"
    assert row["status_code"] == 200
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-opus-5-5"
    assert (row["prompt_tokens"], row["completion_tokens"]) == (1000, 500)
    assert Decimal(str(row["cost_usd"])) == Decimal("0.014")
    assert row["masked_entities"] == 1
    assert row["fallback_used"] == 0
    assert row["latency_ms"] >= 0
    # Neither the prompt, the answer, nor the PII appear anywhere in the row.
    for value in dict(row).values():
        assert "Jean" not in str(value)
        assert "Bonjour" not in str(value)
        assert "hi to" not in str(value)


@respx.mock
def test_fallback_and_failures_are_logged(client: TestClient) -> None:
    respx.post(OLLAMA_URL).mock(side_effect=httpx.ConnectError("down"))
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(503))
    respx.post(ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=anthropic_body("ok")))
    chat = {"messages": [{"role": "user", "content": "Hi"}], "metadata": {"policy": "cost"}}
    assert client.post("/v1/chat/completions", json=chat).status_code == 200

    high = {**chat, "metadata": {"sensitivity": "high"}}
    assert client.post("/v1/chat/completions", json=high).status_code == 502

    ok, failed = usage_rows()
    assert (ok["provider"], ok["fallback_used"], ok["policy"]) == ("anthropic", 1, "cost")
    assert failed["status_code"] == 502
    assert failed["provider"] is None
    assert "ollama: connection error" in failed["error"]


@respx.mock
def test_refused_requests_are_logged(client: TestClient) -> None:
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=ollama_body("ok")))
    chat = {"messages": [{"role": "user", "content": "Hi"}], "metadata": {"sensitivity": "high"}}
    client.post("/v1/chat/completions", json=chat, headers={"Authorization": "Bearer broke-key"})
    (row,) = usage_rows()
    assert (row["team"], row["status_code"]) == ("broke", 402)
