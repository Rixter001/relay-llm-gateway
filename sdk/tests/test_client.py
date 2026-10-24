import json

import httpx
import pytest
import respx
from relay_client import RelayClient, RelayError

BASE = "http://relay.test"
RESPONSE = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 0,
    "model": "llama3.2:3b",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hi Jean"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    "relay": {
        "provider": "ollama",
        "fallback_used": False,
        "masked_entities": 1,
        "cost_usd": 0.0,
        "masked_messages": None,
    },
}


@respx.mock
def test_chat_sends_hints_and_parses_relay_info() -> None:
    route = respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=RESPONSE)
    )
    with RelayClient(BASE, api_key="rk_test") as relay:
        result = relay.chat("Say hi to Jean", policy="data_policy", sensitivity="high")

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer rk_test"
    sent = json.loads(request.content)
    assert sent["messages"] == [{"role": "user", "content": "Say hi to Jean"}]
    assert sent["metadata"] == {"policy": "data_policy", "sensitivity": "high"}
    assert (result.content, result.provider, result.masked_entities) == ("Hi Jean", "ollama", 1)
    assert result.prompt_tokens == 12


@respx.mock
def test_errors_raise_relay_error() -> None:
    respx.post(f"{BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(402, json={"detail": "monthly budget reached"})
    )
    with RelayClient(BASE, api_key="rk_test") as relay, pytest.raises(RelayError) as excinfo:
        relay.chat("hi")
    assert excinfo.value.status_code == 402
    assert "budget" in excinfo.value.message


def test_api_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RELAY_API_KEY", raising=False)
    with pytest.raises(ValueError):
        RelayClient(BASE)


@respx.mock
def test_models() -> None:
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(
            200, json={"object": "list", "data": [{"id": "auto"}, {"id": "llama3.2:3b"}]}
        )
    )
    with RelayClient(BASE, api_key="rk_test") as relay:
        assert relay.models() == ["auto", "llama3.2:3b"]
