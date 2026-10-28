from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

from veritas.pipeline.runner import run_pipeline
from veritas.registry import Registry
from veritas.resolution.gemini import run_ai_worker
from veritas.settings import get_settings
from veritas.storage.db import get_record_store

app = FastAPI(title="Veritas Claims Pipeline", version="0.1.0")


class RunRequest(BaseModel):
    """Accepts pipeline options; ignores unknown keys (e.g. Console Test ``name``)."""

    model_config = ConfigDict(extra="ignore")

    prefix: str = ""
    limit: int | None = None
    # Cloud Run Console "Test" panel sends {"name": "Developer"} by default
    name: str | None = Field(default=None, description="Ignored; Console Test compatibility")


def _execute_run(req: RunRequest | None = None) -> dict[str, Any]:
    req = req or RunRequest()
    return run_pipeline(prefix=req.prefix, limit=req.limit)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run(req: RunRequest = RunRequest()) -> dict[str, Any]:
    return _execute_run(req)


@app.post("/")
def run_root(req: RunRequest = RunRequest()) -> dict[str, Any]:
    """Same as POST /run — so Cloud Run Console Test (POST /) works."""
    return _execute_run(req)


@app.post("/ai-worker/run")
def ai_worker(limit: int = 10, req: RunRequest | None = None) -> dict[str, Any]:
    """Resolve pending_ai names via Gemini. Body optional (Console-safe)."""
    _ = req  # ignore Console {"name":"Developer"} payload
    settings = get_settings()
    store = get_record_store(settings)
    store.ensure_schema()
    registry = Registry(settings)
    return run_ai_worker(store, registry, settings, limit=limit)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "veritas-pipeline",
        "docs": "/docs",
        "health": "/health",
        "run": "POST / or POST /run with JSON body {} (or Console default)",
    }
