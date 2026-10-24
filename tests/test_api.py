import httpx
import respx
from fakes import ANTHROPIC_URL, anthropic_body
from fastapi.testclient import TestClient


def test_models_lists_auto_and_configured_providers(client: TestClient) -> None:
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids == ["auto", "claude-opus-5-5", "gemini-2.5-flash", "llama-test"]


@respx.mock
def test_chat_completion_openai_shape(client: TestClient) -> None:
    respx.post(ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=anthropic_body("Hello!")))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "claude-opus-5-5", "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "Hello!"}
    assert body["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert body["relay"]["provider"] == "anthropic"


def test_streaming_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"stream": True, "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert response.status_code == 400


def test_empty_messages_rejected(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={"messages": []})
    assert response.status_code == 422
