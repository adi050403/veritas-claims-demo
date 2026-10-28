from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from veritas.registry import Registry
from veritas.settings import Settings, get_settings
from veritas.storage.db import RecordStore

log = logging.getLogger("veritas.gemini")

# Prefer configured model first; fall back when Vertex/API has capacity issues.
_MODEL_FALLBACKS = (
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
)


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


def _client(settings: Settings):
    """Prefer Gemini Developer API (API key); fall back to Vertex AI."""
    from google import genai

    api_key = (settings.gemini_api_key or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if api_key and not settings.gemini_use_vertex:
        return genai.Client(api_key=api_key), "developer_api"

    if settings.gcp_project_id:
        return (
            genai.Client(
                vertexai=True,
                project=settings.gcp_project_id,
                location=settings.vertex_location or "global",
            ),
            "vertex",
        )

    if api_key:
        return genai.Client(api_key=api_key), "developer_api"

    raise RuntimeError(
        "No Gemini credentials: set GEMINI_API_KEY (AI Studio) or GCP_PROJECT_ID for Vertex"
    )


def resolve_with_gemini(
    raw_name: str,
    canonical_candidates: list[str],
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Call Gemini with temperature=0 and JSON schema response."""
    settings = settings or get_settings()
    if not settings.gemini_enabled:
        log.info("Gemini disabled; skipping resolution for %s", raw_name)
        return None

    try:
        from google.genai import types
    except ImportError:
        log.warning("google-genai not installed")
        return None

    try:
        client, mode = _client(settings)
    except Exception as exc:
        log.error("Gemini client init failed: %s", exc)
        return None

    # Keep prompt small — only top candidates by fuzzy hint would be ideal;
    # for demo we send a capped list.
    candidates = canonical_candidates[:40]
    prompt = (
        "You are a clinical laboratory terminology normaliser. "
        "Map the raw test name to the best canonical name from the candidate list. "
        "If none fit, propose a new canonical name in Title Case medical English.\n\n"
        f"Raw test name: {raw_name}\n"
        f"Candidates: {json.dumps(candidates)}\n"
        "Return JSON only with keys canonical_name, confidence (0-1), rationale, is_new_canonical."
    )

    models: list[str] = []
    for m in [settings.gemini_model, *_MODEL_FALLBACKS]:
        if m and m not in models:
            models.append(m)

    config_kwargs: dict[str, Any] = {
        "temperature": 0,
        "response_mime_type": "application/json",
        "max_output_tokens": 1024,
    }
    try:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass

    last_exc: Exception | None = None
    for model in models:
        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
                text = getattr(response, "text", None) or ""
                parsed = _parse_json_payload(text)
                if not parsed:
                    log.error("Gemini returned non-JSON (%s): %s", model, text[:300])
                    break
                parsed["_gemini_mode"] = mode
                parsed["_gemini_model"] = model
                return parsed
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                transient = any(x in msg for x in ("503", "UNAVAILABLE", "429", "high demand", "RESOURCE_EXHAUSTED"))
                log.warning(
                    "Gemini attempt failed (%s / %s attempt %s): %s",
                    mode,
                    model,
                    attempt,
                    msg[:300],
                )
                if transient and attempt < 3:
                    time.sleep(2 * attempt)
                    continue
                if transient:
                    break  # try next model
                raise

    if last_exc:
        raise last_exc
    return None


def _parse_json_payload(text: str) -> dict[str, Any] | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        # Extract first {...} block if model added prose
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(cleaned[start : end + 1])
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def run_ai_worker(
    store: RecordStore,
    registry: Registry,
    settings: Settings | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Async enrichment: PATCH BigQuery/SQLite + push aliases to registry."""
    settings = settings or get_settings()
    pending = store.pending_ai_names(limit=limit)
    stats: dict[str, Any] = {
        "seen": len(pending),
        "resolved": 0,
        "failed": 0,
        "errors": [],
        "examples": [],
    }

    if not settings.gemini_enabled:
        stats["errors"].append("GEMINI_ENABLED=false — set true to call the model")
        return stats

    candidates = registry.all_canonical_names()
    for name in pending:
        try:
            result = resolve_with_gemini(name, candidates, settings)
        except Exception as exc:
            stats["failed"] += 1
            stats["errors"].append({"test_name": name, "error": str(exc)[:400]})
            # Stop early on billing/auth class errors so the demo sees one clear message
            err_l = str(exc).lower()
            if any(
                x in err_l
                for x in ("402", "resource_exhausted", "prepayment", "permission", "401", "403")
            ):
                stats["errors"].append(
                    {
                        "fatal": True,
                        "hint": (
                            "Gemini API prepaid credits are depleted or billing is not enabled. "
                            "Open https://aistudio.google.com/ → project veritas-claims-512706 → "
                            "enable Pay-as-you-go / add credits, then re-run POST /ai-worker/run"
                        ),
                    }
                )
                break
            continue

        if not result or not result.get("canonical_name"):
            stats["failed"] += 1
            stats["errors"].append({"test_name": name, "error": "empty_response"})
            continue

        canonical = result["canonical_name"]
        confidence = float(result.get("confidence") or 0.7)
        patched = store.patch_ai_resolution(name, canonical, confidence, "gemini")
        try:
            registry.push_learned_alias(name, canonical)
        except Exception as exc:
            log.warning("Could not persist learned alias: %s", exc)

        stats["resolved"] += patched
        stats["examples"].append(
            {
                "original": name,
                "canonical": canonical,
                "confidence": confidence,
                "rows_patched": patched,
                "model": result.get("_gemini_model"),
                "mode": result.get("_gemini_mode"),
                "rationale": result.get("rationale"),
            }
        )
        log.info(
            "Resolved AI name %s -> %s (patched=%s)",
            name,
            canonical,
            patched,
        )
    return stats
