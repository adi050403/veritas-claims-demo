from __future__ import annotations

import json
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable

from veritas.settings import Settings, get_settings


class ObjectStore(ABC):
    @abstractmethod
    def list_json(self, prefix: str = "") -> list[str]:
        ...

    @abstractmethod
    def read_text(self, path: str) -> str:
        ...

    @abstractmethod
    def read_json(self, path: str) -> Any:
        ...

    @abstractmethod
    def write_text(self, path: str, content: str) -> None:
        ...

    @abstractmethod
    def write_json(self, path: str, payload: Any) -> None:
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        ...

    @abstractmethod
    def copy_to_quarantine(self, source_path: str, reason: str) -> str:
        ...


class LocalObjectStore(ObjectStore):
    """Local filesystem stand-in for GCS (on-prem / laptop mode)."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.raw_root = Path(self.settings.local_raw_root)
        self.state_root = Path(self.settings.local_state_root)
        self.quarantine_root = Path(self.settings.local_quarantine_root)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        # state/ and quarantine/ live outside raw root
        if path.startswith("state/"):
            return self.state_root / path[len("state/") :]
        if path.startswith("quarantine/"):
            return self.quarantine_root / path[len("quarantine/") :]
        return self.raw_root / path

    def list_json(self, prefix: str = "") -> list[str]:
        root = self.raw_root / prefix if prefix else self.raw_root
        if not root.exists():
            return []
        files = sorted(root.rglob("*.json"))
        out: list[str] = []
        for f in files:
            rel = f.relative_to(self.raw_root).as_posix()
            if "/state/" in rel or rel.startswith("state/"):
                continue
            out.append(rel)
        return out

    def read_text(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def read_json(self, path: str) -> Any:
        return json.loads(self.read_text(path))

    def write_text(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def write_json(self, path: str, payload: Any) -> None:
        self.write_text(path, json.dumps(payload, indent=2, default=str))

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def copy_to_quarantine(self, source_path: str, reason: str) -> str:
        src = self._resolve(source_path)
        dest_rel = f"quarantine/{Path(source_path).name}"
        dest = self._resolve(dest_rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dest)
        meta = {"source": source_path, "reason": reason}
        dest.with_suffix(dest.suffix + ".meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        return dest_rel


class GCSObjectStore(ObjectStore):
    """GCS-backed object store for cloud deployment."""

    def __init__(self, settings: Settings | None = None):
        from google.cloud import storage  # lazy import

        self.settings = settings or get_settings()
        self.client = storage.Client(project=self.settings.gcp_project_id or None)
        self.raw_bucket = self.client.bucket(self.settings.gcs_raw_bucket)
        self.state_bucket = self.client.bucket(self.settings.gcs_state_bucket)
        self.quarantine_prefix = self.settings.gcs_quarantine_prefix

    def _blob(self, path: str):
        if path.startswith("state/"):
            return self.state_bucket.blob(path)
        if path.startswith("quarantine/"):
            return self.state_bucket.blob(path)
        return self.raw_bucket.blob(path)

    def list_json(self, prefix: str = "") -> list[str]:
        blobs = self.client.list_blobs(self.raw_bucket, prefix=prefix)
        return sorted(
            b.name
            for b in blobs
            if b.name.endswith(".json") and "/state/" not in b.name and not b.name.startswith("state/")
        )

    def read_text(self, path: str) -> str:
        return self._blob(path).download_as_text(encoding="utf-8")

    def read_json(self, path: str) -> Any:
        return json.loads(self.read_text(path))

    def write_text(self, path: str, content: str) -> None:
        self._blob(path).upload_from_string(content, content_type="application/json")

    def write_json(self, path: str, payload: Any) -> None:
        self.write_text(path, json.dumps(payload, indent=2, default=str))

    def exists(self, path: str) -> bool:
        return self._blob(path).exists()

    def copy_to_quarantine(self, source_path: str, reason: str) -> str:
        dest = f"{self.quarantine_prefix}{Path(source_path).name}"
        src_blob = self.raw_bucket.blob(source_path)
        self.raw_bucket.copy_blob(src_blob, self.state_bucket, dest)
        self.write_json(f"{dest}.meta.json", {"source": source_path, "reason": reason})
        return dest


def get_object_store(settings: Settings | None = None) -> ObjectStore:
    settings = settings or get_settings()
    if settings.is_gcp:
        return GCSObjectStore(settings)
    return LocalObjectStore(settings)
