import json

import httpx
import pytest
import respx
from fakes import ANTHROPIC_URL, GEMINI_URL, OLLAMA_URL, anthropic_body, gemini_body, ollama_body

from app.providers.anthropic import AnthropicProvider
from app.providers.base import ProviderError
from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider
from app.schemas import ChatMessage

MESSAGES = [
    ChatMessage(role="system", content="Be brief."),
    ChatMessage(role="user", content="Hello"),
]


@respx.mock
async def test_anthropic_request_and_response_mapping() -> None:
    route = respx.post(ANTHROPIC_URL).mock(
        return_value=httpx.Response(200, json=anthropic_body("Hi"))
    )
    async with httpx.AsyncClient() as client:
        provider = AnthropicProvider(client, "claude-test", "secret", "https://api.anthropic.test")
        result = await provider.complete(MESSAGES, max_tokens=50, temperature=0.2)

    sent = json.loads(route.calls.last.request.content)
    assert sent["system"] == "Be brief."
    assert sent["messages"] == [{"role": "user", "content": "Hello"}]
    assert "temperature" not in sent
    assert route.calls.last.request.headers["x-api-key"] == "secret"
    assert (result.text, result.prompt_tokens, result.completion_tokens) == ("Hi", 10, 5)
    assert result.finish_reason == "stop"


@respx.mock
async def test_gemini_request_and_response_mapping() -> None:
    route = respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=gemini_body("Hi")))
    async with httpx.AsyncClient() as client:
        provider = GeminiProvider(client, "gemini-2.5-flash", "secret", "https://gemini.test")
        result = await provider.complete(MESSAGES, max_tokens=50, temperature=None)

    request = route.calls.last.request
    sent = json.loads(request.content)
    assert sent["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert sent["contents"] == [{"role": "user", "parts": [{"text": "Hello"}]}]
    assert request.headers["x-goog-api-key"] == "secret"
    assert "key=" not in str(request.url)
    assert result.text == "Hi"


@respx.mock
async def test_ollama_request_and_response_mapping() -> None:
    route = respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=ollama_body("Hi")))
    async with httpx.AsyncClient() as client:
        provider = OllamaProvider(client, "llama-test", "http://ollama.test")
        result = await provider.complete(MESSAGES, max_tokens=50, temperature=None)

    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is False
    assert sent["options"] == {"num_predict": 50}
    assert result.text == "Hi"
    assert provider.is_local


@pytest.mark.parametrize(
    "side_effect, reason",
    [
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(429), "HTTP 429"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "connection error"),
        (httpx.Response(200, json={"unexpected": True}), "unexpected response shape"),
    ],
)
@respx.mock
async def test_failures_become_provider_errors(side_effect: object, reason: str) -> None:
    respx.post(OLLAMA_URL).mock(side_effect=[side_effect])
    async with httpx.AsyncClient() as client:
        provider = OllamaProvider(client, "llama-test", "http://ollama.test")
        with pytest.raises(ProviderError) as excinfo:
            await provider.complete(MESSAGES, max_tokens=50, temperature=None)
    assert reason in excinfo.value.reason
    # The prompt must never leak into error messages (they end up in logs).
    assert "Hello" not in str(excinfo.value)
