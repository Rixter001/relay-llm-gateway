import json
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
    "RELAY_ANTHROPIC_MODEL": "claude-opus-5-5",
    "RELAY_ANTHROPIC_BASE_URL": "https://api.anthropic.test",
    "RELAY_GEMINI_API_KEY": "test-gemini-key",
    "RELAY_GEMINI_MODEL": "gemini-2.5-flash",
    "RELAY_GEMINI_BASE_URL": "https://gemini.test",
    "RELAY_OLLAMA_MODEL": "llama-test",
    "RELAY_OLLAMA_BASE_URL": "http://ollama.test",
}


# Three test teams: a normal one, one with a tiny rate limit, one with a $0 budget.
TEST_TEAMS = [
    ("default", "test-key", 1000, 100.0),
    ("limited", "limited-key", 2, 100.0),
    ("broke", "broke-key", 1000, 0.0),
]


@pytest.fixture(autouse=True)
def relay_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Point every provider at a fake URL and reset the cached settings around each test."""
    from app.auth import hash_key

    teams_file = tmp_path / "teams.json"
    teams_file.write_text(
        json.dumps(
            [
                {
                    "name": name,
                    "api_key_sha256": hash_key(key),
                    "rate_limit_per_minute": rate,
                    "monthly_budget_usd": budget,
                }
                for name, key, rate, budget in TEST_TEAMS
            ]
        )
    )
    monkeypatch.setenv("RELAY_TEAMS_FILE", str(teams_file))
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    import fakeredis
    from fakes import FakeAnalyzer

    from app import main
    from app.main import app
    from app.masking import Masker

    monkeypatch.setattr(main, "build_masker", lambda settings: Masker(FakeAnalyzer(), ["en"]))
    monkeypatch.setattr(main, "create_redis", lambda settings: fakeredis.aioredis.FakeRedis())

    # Using TestClient as a context manager runs the lifespan (startup/shutdown).
    with TestClient(app, headers={"Authorization": "Bearer test-key"}) as test_client:
        yield test_client
