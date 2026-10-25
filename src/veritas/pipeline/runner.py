from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from veritas.pipeline.ingest import discover_files, ingest_file
from veritas.pipeline.load import stream_load
from veritas.pipeline.map import map_file
from veritas.pipeline.standardise import standardise_rows
from veritas.pipeline.validate import validate_rows
from veritas.registry import Registry
from veritas.resolution.cascade import TestNameResolver
from veritas.settings import Settings, get_settings
from veritas.storage.db import SQLiteRecordStore, get_record_store
from veritas.storage.object_store import get_object_store
from veritas.storage.progress import ProgressTracker
from veritas.utils.logging import setup_logging

log = logging.getLogger("veritas.runner")


def run_pipeline(
    prefix: str = "",
    settings: Settings | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """End-to-end: Ingest → Map → Standardise → Validate → Stream Load."""
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    store = get_object_store(settings)
    db = get_record_store(settings)
    db.ensure_schema()
    progress = ProgressTracker(store)
    registry = Registry(settings)
    resolver = TestNameResolver(registry, settings)

    started = datetime.now(timezone.utc).isoformat()
    files = discover_files(store, prefix)
    if limit is not None:
        files = files[:limit]

    stats: dict[str, Any] = {
        "started_at": started,
        "files_total": len(files),
        "files_ok": 0,
        "files_failed": 0,
        "files_dup": 0,
        "rows_written": 0,
        "errors": [],
    }

    for path in files:
        file_id = path
        try:
            ingested = ingest_file(store, progress, path)
            if ingested is None:
                # completed earlier or duplicate
                entry = progress.get(file_id) or {}
                if entry.get("status") == "skipped_duplicate":
                    stats["files_dup"] += 1
                continue

            progress.update(file_id, stage="map", status="in_progress", content_hash=ingested.content_hash)
            mapped = map_file(ingested)

            progress.update(file_id, stage="standardise", status="in_progress")
            standardised = standardise_rows(mapped, registry, resolver)

            progress.update(file_id, stage="validate", status="in_progress")
            validated = validate_rows(standardised)

            progress.update(file_id, stage="stream_load", status="in_progress")
            n = stream_load(db, validated)
            stats["rows_written"] += n
            stats["files_ok"] += 1

            progress.update(
                file_id,
                stage="stream_load",
                status="completed",
                content_hash=ingested.content_hash,
                offsets={"rows": n},
            )
            log.info(
                "File processed",
                extra={
                    "file_id": file_id,
                    "stage": "stream_load",
                    "correlation_id": ingested.meta.get("claim_no"),
                    "document_id": ingested.payload.get("data", {}).get("documentId"),
                },
            )
        except Exception as exc:
            stats["files_failed"] += 1
            stats["errors"].append({"file": path, "error": str(exc)})
            progress.update(file_id, stage="failed", status="failed", error=str(exc))
            try:
                db.insert_dead_letter(
                    {"file_path": path, "reason": str(exc), "correlation_id": None, "payload": {}}
                )
            except Exception:
                pass
            log.exception("File failed", extra={"file_id": file_id, "stage": "failed"})

    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    if isinstance(db, SQLiteRecordStore):
        db.record_run(stats)
    return stats
