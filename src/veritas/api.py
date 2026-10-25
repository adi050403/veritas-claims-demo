from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from veritas.pipeline.runner import run_pipeline
from veritas.registry import Registry
from veritas.resolution.gemini import run_ai_worker
from veritas.settings import get_settings
from veritas.storage.db import get_record_store

app = FastAPI(title="Veritas Claims Pipeline", version="0.1.0")


class RunRequest(BaseModel):
    prefix: str = ""
    limit: int | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run(req: RunRequest) -> dict[str, Any]:
    return run_pipeline(prefix=req.prefix, limit=req.limit)


@app.post("/ai-worker/run")
def ai_worker(limit: int = 50) -> dict[str, Any]:
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
        "run": "POST /run",
    }
