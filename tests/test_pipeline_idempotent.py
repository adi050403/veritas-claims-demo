from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from veritas.pipeline.runner import run_pipeline
from veritas.settings import Settings
from veritas.storage.db import SQLiteRecordStore


def test_rerun_does_not_duplicate(tmp_path):
    db_path = tmp_path / "t.sqlite"
    state = tmp_path / "state"
    settings = Settings(
        STORAGE_BACKEND="local",
        LOCAL_RAW_ROOT=str(ROOT / "sample-data"),
        LOCAL_STATE_ROOT=str(state),
        LOCAL_QUARANTINE_ROOT=str(tmp_path / "q"),
        LOCAL_DB_PATH=str(db_path),
        CONFIG_ROOT=str(ROOT / "config"),
    )
    # clear cached settings if any
    from veritas import settings as settings_mod

    settings_mod.get_settings.cache_clear()

    s1 = run_pipeline(settings=settings)
    store = SQLiteRecordStore(settings)
    n1 = len(store.fetch_all(limit=10000))

    s2 = run_pipeline(settings=settings)
    n2 = len(store.fetch_all(limit=10000))

    assert s1["files_ok"] >= 1
    assert s2["files_ok"] == 0  # already completed via progress tracker
    assert n1 == n2
    assert n1 > 0
