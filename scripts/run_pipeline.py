#!/usr/bin/env python3
"""CLI entrypoint for the Veritas Claims pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from veritas.pipeline.runner import run_pipeline  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Veritas Claims standardisation pipeline")
    parser.add_argument("--prefix", default="", help="Optional clinic/date prefix under raw root")
    parser.add_argument("--limit", type=int, default=None, help="Max files to process")
    args = parser.parse_args()
    stats = run_pipeline(prefix=args.prefix, limit=args.limit)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
