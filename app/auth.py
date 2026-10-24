"""Team API keys.

Each team has its own key, sent as `Authorization: Bearer <key>` (what OpenAI clients send).
Teams are declared in a JSON file (RELAY_TEAMS_FILE) that stores only the SHA-256 hash of
each key, so a leaked config file or Kubernetes Secret does not leak usable keys.

A plain SHA-256 is enough here (unlike passwords, which need bcrypt/argon2) because keys are
long random tokens: there is no dictionary to brute-force.

Generate a key for a new team:
    python -m app.auth new-key <team-name>
"""

import hashlib
import json
import secrets
import sys
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, TypeAdapter


class Team(BaseModel):
    name: str
    api_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rate_limit_per_minute: int = Field(default=60, ge=1)
    # None means no monthly cap.
    monthly_budget_usd: float | None = Field(default=None, ge=0)


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


class TeamDirectory:
    def __init__(self, teams: list[Team]) -> None:
        # Indexed by key hash: looking up the hash of the presented key is a dictionary lookup,
        # so there is no character-by-character comparison of secrets to time.
        self._by_hash = {team.api_key_sha256: team for team in teams}

    @classmethod
    def from_file(cls, path: Path) -> "TeamDirectory":
        teams = TypeAdapter(list[Team]).validate_python(json.loads(path.read_text("utf-8")))
        return cls(teams)

    def find(self, api_key: str) -> Team | None:
        return self._by_hash.get(hash_key(api_key))


def authenticate(request: Request) -> Team:
    """FastAPI dependency: returns the calling team or answers 401."""
    header = request.headers.get("authorization", "")
    scheme, _, api_key = header.partition(" ")
    if scheme.lower() != "bearer" or not api_key:
        raise HTTPException(401, "missing API key (expected 'Authorization: Bearer <key>')")
    directory: TeamDirectory = request.app.state.teams
    team = directory.find(api_key.strip())
    if team is None:
        raise HTTPException(401, "invalid API key")
    return team


def _new_key_command(team_name: str) -> None:
    api_key = "rk_" + secrets.token_urlsafe(32)
    entry = {
        "name": team_name,
        "api_key_sha256": hash_key(api_key),
        "rate_limit_per_minute": 60,
        "monthly_budget_usd": 100.0,
    }
    print(f"API key for {team_name} (shown once, give it to the team):\n  {api_key}\n")
    print("Add this entry to your teams file:")
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "new-key":
        sys.exit("usage: python -m app.auth new-key <team-name>")
    _new_key_command(sys.argv[2])
