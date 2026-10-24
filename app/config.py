"""Application settings, read from environment variables (prefix RELAY_) or a .env file.

pydantic-settings validates types at startup, so a typo such as RELAY_PROVIDER_TIMEOUT_S=abc
crashes immediately instead of failing on the first request.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_", env_file=".env", extra="ignore")

    environment: str = "dev"

    # --- Providers -------------------------------------------------------------------------
    # SecretStr hides the value in repr() and logs; .get_secret_value() is needed to read it.
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"

    ollama_enabled: bool = True
    ollama_model: str = "llama3.2:3b"
    ollama_base_url: str = "http://localhost:11434"

    # Total time allowed for one provider call, and the (short) time allowed to open the
    # TCP connection. See docs/DECISIONS.md for why the two are separate.
    provider_timeout_s: float = 60.0
    provider_connect_timeout_s: float = 3.0


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process; tests clear the cache to override them."""
    return Settings()
