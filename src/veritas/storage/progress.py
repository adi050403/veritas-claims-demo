from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from veritas.storage.object_store import ObjectStore

PROGRESS_PATH = "state/progress.json"


class ProgressTracker:
    """Crash/OOM recovery via checkpointed progress.json (GCS or local)."""

    def __init__(self, store: ObjectStore):
        self.store = store
        self._data: dict[str, Any] = {"files": {}, "updated_at": None}
        if store.exists(PROGRESS_PATH):
            try:
                self._data = store.read_json(PROGRESS_PATH)
            except Exception:
                self._data = {"files": {}, "updated_at": None}

    def get(self, file_id: str) -> dict[str, Any] | None:
        return self._data.get("files", {}).get(file_id)

    def is_done(self, file_id: str) -> bool:
        entry = self.get(file_id)
        return bool(entry and entry.get("status") == "completed")

    def is_duplicate_hash(self, content_hash: str) -> bool:
        for entry in self._data.get("files", {}).values():
            if entry.get("content_hash") == content_hash and entry.get("status") == "completed":
                return True
        return False

    def update(
        self,
        file_id: str,
        *,
        stage: str,
        status: str,
        content_hash: str | None = None,
        offsets: dict | None = None,
        error: str | None = None,
        extras: dict | None = None,
    ) -> None:
        files = self._data.setdefault("files", {})
        entry = files.get(file_id, {})
        entry.update(
            {
                "file_id": file_id,
                "stage": stage,
                "status": status,
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            }
        )
        if content_hash:
            entry["content_hash"] = content_hash
        if offsets is not None:
            entry["offsets"] = offsets
        if error is not None:
            entry["error"] = error
        if extras:
            entry.update(extras)
        files[file_id] = entry
        self._data["updated_at"] = entry["last_heartbeat"]
        self.persist()

    def persist(self) -> None:
        self.store.write_json(PROGRESS_PATH, self._data)

    def summary(self) -> dict[str, int]:
        counts = {"completed": 0, "failed": 0, "in_progress": 0, "skipped_duplicate": 0, "other": 0}
        for entry in self._data.get("files", {}).values():
            status = entry.get("status", "other")
            counts[status] = counts.get(status, 0) + 1 if status in counts else counts["other"] + 1
        counts["total"] = len(self._data.get("files", {}))
        return counts

    @property
    def raw(self) -> dict[str, Any]:
        return self._data
