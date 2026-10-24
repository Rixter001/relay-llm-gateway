"""Builds the providers that are actually configured (a cloud provider without an API key is
simply not registered, so the router never tries it)."""

import httpx

from app.config import Settings
from app.providers.anthropic import AnthropicProvider
from app.providers.base import Provider, ProviderError, ProviderResult
from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider

__all__ = ["Provider", "ProviderError", "ProviderResult", "build_providers"]


def build_providers(settings: Settings, client: httpx.AsyncClient) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    if settings.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(
            client,
            settings.anthropic_model,
            settings.anthropic_api_key.get_secret_value(),
            settings.anthropic_base_url,
        )
    if settings.gemini_api_key:
        providers["gemini"] = GeminiProvider(
            client,
            settings.gemini_model,
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_base_url,
        )
    if settings.ollama_enabled:
        providers["ollama"] = OllamaProvider(
            client, settings.ollama_model, settings.ollama_base_url
        )
    return providers
