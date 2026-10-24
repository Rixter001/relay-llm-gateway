import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make `fakes` importable from every test module (pytest runs in importlib mode).
sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings  # noqa: E402

TEST_ENV = {
    "RELAY_ANTHROPIC_API_KEY": "test-anthropic-key",
    "RELAY_ANTHROPIC_MODEL": "claude-test",
    "RELAY_ANTHROPIC_BASE_URL": "https://api.anthropic.test",
    "RELAY_GEMINI_API_KEY": "test-gemini-key",
    "RELAY_GEMINI_MODEL": "gemini-test",
    "RELAY_GEMINI_BASE_URL": "https://gemini.test",
    "RELAY_OLLAMA_MODEL": "llama-test",
    "RELAY_OLLAMA_BASE_URL": "http://ollama.test",
}


@pytest.fixture(autouse=True)
def relay_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point every provider at a fake URL and reset the cached settings around each test."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    # Using TestClient as a context manager runs the lifespan (startup/shutdown).
    with TestClient(app) as test_client:
        yield test_client
