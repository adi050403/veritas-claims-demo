#!/usr/bin/env python3
"""Minimal Gemini demo: resolve a few pending_ai names and PATCH BigQuery."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)
os.environ["STORAGE_BACKEND"] = "gcp"

from google import genai
from google.genai import types

from veritas.registry import Registry
from veritas.settings import get_settings
from veritas.storage.db import get_record_store

get_settings.cache_clear()
settings = get_settings()

print("config", {
    "model": settings.gemini_model,
    "has_key": bool(settings.gemini_api_key),
    "dataset": settings.bq_dataset,
}, flush=True)

store = get_record_store(settings)
store.ensure_schema()
t0 = time.time()
pending = store.pending_ai_names(limit=5)
print(f"pending_fetched={len(pending)} in {time.time()-t0:.1f}s -> {pending}", flush=True)

registry = Registry(settings)
candidates = registry.all_canonical_names()[:25]
client = genai.Client(api_key=settings.gemini_api_key)

results = []
for name in pending:
    prompt = (
        "Map this clinical lab test name to a canonical English name. "
        "Prefer one of the candidates when appropriate.\n"
        f"Raw: {name}\n"
        f"Candidates: {json.dumps(candidates)}\n"
        'Return ONLY JSON: {"canonical_name":"...","confidence":0.0,"rationale":"..."}'
    )
    print(f"calling gemini for: {name}", flush=True)
    t1 = time.time()
    try:
        resp = client.models.generate_content(
            model=settings.gemini_model or "gemini-3.7-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                max_output_tokens=200,
            ),
        )
    except Exception as exc:
        print(f"FAIL generate: {exc}", flush=True)
        continue
    print(f"gemini_ok in {time.time()-t1:.1f}s text={resp.text[:180]!r}", flush=True)
    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print("bad json", flush=True)
        continue
    canonical = parsed.get("canonical_name")
    if not canonical:
        continue
    conf = float(parsed.get("confidence") or 0.8)
    patched = store.patch_ai_resolution(name, canonical, conf, "gemini")
    registry.push_learned_alias(name, canonical)
    row = {
        "original": name,
        "canonical": canonical,
        "confidence": conf,
        "rows_patched": patched,
        "model": settings.gemini_model,
        "rationale": parsed.get("rationale"),
    }
    results.append(row)
    print("PATCHED", row, flush=True)

print(json.dumps({"resolved": len(results), "examples": results}, indent=2))
sys.exit(0 if results else 2)
