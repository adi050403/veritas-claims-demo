from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")

    local_raw_root: Path = Field(default=ROOT / "sample-data", alias="LOCAL_RAW_ROOT")
    local_state_root: Path = Field(default=ROOT / "data" / "state", alias="LOCAL_STATE_ROOT")
    local_quarantine_root: Path = Field(
        default=ROOT / "data" / "quarantine", alias="LOCAL_QUARANTINE_ROOT"
    )
    local_db_path: Path = Field(default=ROOT / "data" / "db" / "veritas.sqlite", alias="LOCAL_DB_PATH")
    config_root: Path = Field(default=ROOT / "config", alias="CONFIG_ROOT")

    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    gcs_raw_bucket: str = Field(default="veritas-medical-raw", alias="GCS_RAW_BUCKET")
    gcs_state_bucket: str = Field(default="veritas-medical-raw", alias="GCS_STATE_BUCKET")
    gcs_quarantine_prefix: str = Field(default="quarantine/", alias="GCS_QUARANTINE_PREFIX")
    bq_dataset: str = Field(default="veritas_claims_demo", alias="BQ_DATASET")
    bq_table: str = Field(default="canonical_records", alias="BQ_TABLE")
    bq_deadletter_table: str = Field(default="dead_letter", alias="BQ_DEADLETTER_TABLE")

    gemini_enabled: bool = Field(default=False, alias="GEMINI_ENABLED")
    gemini_model: str = Field(default="gemini-3.7-flash", alias="GEMINI_MODEL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    # False = Gemini Developer API (API key). True = Vertex AI (often needs model access).
    gemini_use_vertex: bool = Field(default=False, alias="GEMINI_USE_VERTEX")
    vertex_location: str = Field(default="global", alias="VERTEX_LOCATION")

    fuzzy_match_threshold: float = Field(default=86.0, alias="FUZZY_MATCH_THRESHOLD")
    nlp_match_threshold: float = Field(default=0.78, alias="NLP_MATCH_THRESHOLD")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_gcp(self) -> bool:
        return self.storage_backend.lower() == "gcp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
