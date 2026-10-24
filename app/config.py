"""Application settings, read from environment variables (prefix RELAY_) or a .env file.

pydantic-settings validates types at startup, so a typo such as RELAY_PROVIDER_TIMEOUT_S=abc
crashes immediately instead of failing on the first request.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_", env_file=".env", extra="ignore")

    environment: str = "dev"


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process; tests clear the cache to override them."""
    return Settings()
