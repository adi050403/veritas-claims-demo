from __future__ import annotations

import hashlib
import json
from typing import Any


def content_hash(payload: Any) -> str:
    """Stable SHA-256 over canonical JSON for duplicate detection."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def row_id(*parts: str) -> str:
    joined = "|".join(p or "" for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]
