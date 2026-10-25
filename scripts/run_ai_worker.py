#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from veritas.registry import Registry  # noqa: E402
from veritas.resolution.gemini import run_ai_worker  # noqa: E402
from veritas.settings import get_settings  # noqa: E402
from veritas.storage.db import get_record_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve pending_ai test names via Gemini")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    settings = get_settings()
    store = get_record_store(settings)
    store.ensure_schema()
    registry = Registry(settings)
    stats = run_ai_worker(store, registry, settings, limit=args.limit)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
