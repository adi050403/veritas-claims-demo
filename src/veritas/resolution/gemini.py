from __future__ import annotations

import json
import logging
from typing import Any

from veritas.registry import Registry
from veritas.settings import Settings, get_settings
from veritas.storage.db import RecordStore

log = logging.getLogger("veritas.gemini")


RESOLUTION_SCHEMA = {
    "type": "object",
    "properties": {
        "canonical_name": {"type": "string"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "is_new_canonical": {"type": "boolean"},
    },
    "required": ["canonical_name", "confidence"],
}


def resolve_with_gemini(
    raw_name: str,
    canonical_candidates: list[str],
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Call Gemini Flash with temperature=0 and JSON schema response."""
    settings = settings or get_settings()
    if not settings.gemini_enabled:
        log.info("Gemini disabled; skipping resolution for %s", raw_name)
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log.warning("google-genai not installed")
        return None

    client_kwargs: dict[str, Any] = {}
    if settings.gcp_project_id:
        client_kwargs = {
            "vertexai": True,
            "project": settings.gcp_project_id,
            "location": settings.vertex_location,
        }
    client = genai.Client(**client_kwargs)

    prompt = (
        "You are a clinical laboratory terminology normaliser. "
        "Map the raw test name to the best canonical name from the candidate list. "
        "If none fit, propose a new canonical name in Title Case.\n\n"
        f"Raw test name: {raw_name}\n"
        f"Candidates: {json.dumps(canonical_candidates)}\n"
        "Return JSON only."
    )

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=RESOLUTION_SCHEMA,
        ),
    )
    text = getattr(response, "text", None) or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.error("Gemini returned non-JSON: %s", text[:500])
        return None


def run_ai_worker(
    store: RecordStore,
    registry: Registry,
    settings: Settings | None = None,
    limit: int = 50,
) -> dict[str, int]:
    """Async enrichment: PATCH BigQuery/SQLite + push aliases to registry."""
    settings = settings or get_settings()
    pending = store.pending_ai_names(limit=limit)
    stats = {"seen": len(pending), "resolved": 0, "failed": 0}

    candidates = registry.all_canonical_names()
    for name in pending:
        result = resolve_with_gemini(name, candidates, settings)
        if not result or not result.get("canonical_name"):
            # Offline / disabled fallback: keep pending
            stats["failed"] += 1
            continue
        canonical = result["canonical_name"]
        confidence = float(result.get("confidence") or 0.7)
        patched = store.patch_ai_resolution(name, canonical, confidence, "gemini")
        registry.push_learned_alias(name, canonical)
        stats["resolved"] += patched
        log.info(
            "Resolved AI name",
            extra={"test_name": name, "canonical": canonical, "patched": patched},
        )
    return stats
