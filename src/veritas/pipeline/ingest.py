from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from veritas.storage.object_store import ObjectStore
from veritas.storage.progress import ProgressTracker
from veritas.utils.hashing import content_hash
from veritas.utils.paths import get_by_path, meta_to_dict

log = logging.getLogger("veritas.ingest")


@dataclass
class IngestedFile:
    file_id: str
    path: str
    clinic_id: str
    payload: dict[str, Any]
    content_hash: str
    meta: dict[str, str] = field(default_factory=dict)
    ingested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def discover_files(store: ObjectStore, prefix: str = "") -> list[str]:
    return store.list_json(prefix)


def clinic_from_path(path: str) -> str:
    parts = Path(path).as_posix().split("/")
    return parts[0] if parts else "unknown"


def ingest_file(
    store: ObjectStore,
    progress: ProgressTracker,
    path: str,
) -> IngestedFile | None:
    """Discover → parse → envelope check → dedupe via content-hash → checkpoint."""
    file_id = Path(path).as_posix()
    if progress.is_done(file_id):
        log.info("Skip already completed", extra={"file_id": file_id, "stage": "ingest"})
        return None

    progress.update(file_id, stage="ingest", status="in_progress")

    try:
        raw_text = store.read_text(path)
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        progress.update(file_id, stage="ingest", status="failed", error=f"malformed_json: {exc}")
        store.copy_to_quarantine(path, f"malformed_json: {exc}")
        raise
    except Exception as exc:
        progress.update(file_id, stage="ingest", status="failed", error=str(exc))
        store.copy_to_quarantine(path, str(exc))
        raise

    # Envelope checks
    if not isinstance(payload, dict):
        progress.update(file_id, stage="ingest", status="failed", error="envelope_not_object")
        store.copy_to_quarantine(path, "envelope_not_object")
        raise ValueError("Envelope is not a JSON object")

    data = payload.get("data")
    if not isinstance(data, dict):
        progress.update(file_id, stage="ingest", status="failed", error="missing_data")
        store.copy_to_quarantine(path, "missing_data")
        raise ValueError("Missing data envelope")

    digest = content_hash(payload)
    if progress.is_duplicate_hash(digest):
        progress.update(
            file_id,
            stage="ingest",
            status="skipped_duplicate",
            content_hash=digest,
            error="duplicate_content_hash",
        )
        log.info("Duplicate suppressed", extra={"file_id": file_id, "stage": "ingest"})
        return None

    meta = meta_to_dict(get_by_path(payload, "$.data.metaDetails") or [])
    clinic_id = clinic_from_path(path)
    if meta.get("source_system"):
        # Prefer path clinic, keep source_system in meta
        pass

    progress.update(
        file_id,
        stage="ingest",
        status="in_progress",
        content_hash=digest,
        offsets={"bytes": len(raw_text)},
        extras={"clinic_id": clinic_id, "document_id": data.get("documentId")},
    )

    return IngestedFile(
        file_id=file_id,
        path=path,
        clinic_id=clinic_id,
        payload=payload,
        content_hash=digest,
        meta=meta,
    )
