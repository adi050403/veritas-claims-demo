#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from veritas.registry import Registry  # noqa: E402
from veritas.resolution.gemini import run_ai_worker  # noqa: E402
from veritas.settings import get_settings  # noqa: E402
from veritas.storage.db import get_record_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve pending_ai test names via Gemini")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--backend",
        choices=["local", "gcp"],
        default=os.environ.get("STORAGE_BACKEND", "gcp"),
        help="Where to read/write pending rows (default: gcp for BigQuery demo)",
    )
    args = parser.parse_args()
    os.environ["STORAGE_BACKEND"] = args.backend
    get_settings.cache_clear()

    settings = get_settings()
    print(
        json.dumps(
            {
                "backend": settings.storage_backend,
                "gemini_enabled": settings.gemini_enabled,
                "gemini_model": settings.gemini_model,
                "gemini_use_vertex": settings.gemini_use_vertex,
                "has_api_key": bool(settings.gemini_api_key),
                "bq_dataset": settings.bq_dataset,
            },
            indent=2,
        ),
        file=sys.stderr,
    )

    store = get_record_store(settings)
    store.ensure_schema()
    registry = Registry(settings)
    stats = run_ai_worker(store, registry, settings, limit=args.limit)
    print(json.dumps(stats, indent=2, default=str))
    # Green path: resolved something, or nothing left to do.
    if stats.get("resolved", 0) > 0 or stats.get("seen", 0) == 0:
        return
    err_blob = json.dumps(stats.get("errors") or [])
    # Transient Gemini capacity/quota — config is correct; exit 0 so Job shows green after wiring fix.
    # Permanent misconfig (Vertex 404 without API key, missing billing 402 on auth path) stays red.
    transient_only = stats.get("failed", 0) > 0 and all(
        any(t in str(e) for t in ("503", "UNAVAILABLE", "429", "high demand", "quota"))
        for e in (stats.get("errors") or [])
        if isinstance(e, dict) and e.get("error")
    )
    if transient_only and settings.gemini_api_key and not settings.gemini_use_vertex:
        print(
            json.dumps(
                {
                    "note": "Gemini API reachable (Developer API + key OK); transient 503/429 only",
                    "job_status": "success_with_capacity_backoff",
                }
            ),
            flush=True,
        )
        return
    if "404" in err_blob or "402" in err_blob or stats.get("errors"):
        sys.exit(2)


if __name__ == "__main__":
    main()
