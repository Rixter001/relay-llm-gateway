"""FastAPI application: routes and startup/shutdown (lifespan)."""

from fastapi import FastAPI

app = FastAPI(title="Relay", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe used by Docker and Kubernetes."""
    return {"status": "ok"}
