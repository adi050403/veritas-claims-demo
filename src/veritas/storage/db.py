from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from veritas.settings import Settings, get_settings

# Long/narrow canonical columns used by both SQLite and BigQuery.
CANONICAL_COLUMNS = [
    "row_id",
    "document_id",
    "record_type",
    "file_gcs_path",
    "trace_id",
    "correlation_id",
    "source_system",
    "clinic_id",
    "claim_no",
    "nt_code",
    "consumer_client_id",
    "destination_identifier",
    "patient_name",
    "age",
    "age_years",
    "gender",
    "uhid",
    "hospital_name",
    "doctor_name",
    "bill_date",
    "reports_date",
    "admission_date",
    "discharge_date",
    "diagnosis",
    "brief_history",
    "general_examinations",
    "recommendations",
    "hospital_address",
    "ward",
    "post_discharge_advice",
    "course_during_hospitalisation",
    "test_name_canonical",
    "test_name_original",
    "result_value",
    "result_text",
    "unit_canonical",
    "unit_original",
    "range_low",
    "range_high",
    "range_text",
    "test_analytics",
    "normalization_method",
    "normalization_confidence",
    "pending_ai",
    "resolved_ai",
    "medicine",
    "medicine_generic",
    "dose",
    "frequency",
    "medicine_type",
    "medicine_injections_investigation",
    "page_no",
    "content_hash",
    "processed_at",
    "ingested_at",
    "raw_json",
]


class RecordStore(ABC):
    @abstractmethod
    def ensure_schema(self) -> None:
        ...

    @abstractmethod
    def upsert_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        ...

    @abstractmethod
    def insert_dead_letter(self, entry: dict[str, Any]) -> None:
        ...

    @abstractmethod
    def fetch_all(self, limit: int = 500) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def fetch_flagged(self, limit: int = 200) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def clinic_stats(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def patch_ai_resolution(
        self, original_name: str, canonical: str, confidence: float, method: str
    ) -> int:
        ...

    @abstractmethod
    def pending_ai_names(self, limit: int = 100) -> list[str]:
        ...


class SQLiteRecordStore(RecordStore):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.path = Path(self.settings.local_db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        cols = ",\n".join(f'"{c}" TEXT' for c in CANONICAL_COLUMNS)
        with self._connect() as conn:
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS canonical_records ({cols}, PRIMARY KEY ("row_id"))'
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dead_letter (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT,
                    reason TEXT,
                    correlation_id TEXT,
                    payload TEXT,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT,
                    finished_at TEXT,
                    files_total INTEGER,
                    files_ok INTEGER,
                    files_failed INTEGER,
                    files_dup INTEGER,
                    rows_written INTEGER
                )
                """
            )
            conn.commit()

    def upsert_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        placeholders = ",".join(["?"] * len(CANONICAL_COLUMNS))
        col_list = ",".join(f'"{c}"' for c in CANONICAL_COLUMNS)
        updates = ",".join(
            f'"{c}"=excluded."{c}"' for c in CANONICAL_COLUMNS if c != "row_id"
        )
        sql = (
            f'INSERT INTO canonical_records ({col_list}) VALUES ({placeholders}) '
            f"ON CONFLICT(row_id) DO UPDATE SET {updates}"
        )
        with self._connect() as conn:
            for row in rows:
                values = [_serialize(row.get(c)) for c in CANONICAL_COLUMNS]
                conn.execute(sql, values)
            conn.commit()
        return len(rows)

    def insert_dead_letter(self, entry: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dead_letter (file_path, reason, correlation_id, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entry.get("file_path"),
                    entry.get("reason"),
                    entry.get("correlation_id"),
                    json.dumps(entry.get("payload"), default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def fetch_all(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM canonical_records ORDER BY processed_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def fetch_flagged(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM canonical_records
                WHERE test_analytics IN ('Above Range','Below Range','Outlier','Invalid')
                   OR pending_ai = 'true'
                ORDER BY processed_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def clinic_stats(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT
                  clinic_id,
                  COUNT(*) AS total_rows,
                  SUM(CASE WHEN test_analytics IN ('Above Range','Below Range','Outlier','Invalid') THEN 1 ELSE 0 END) AS flagged,
                  SUM(CASE WHEN pending_ai = 'true' THEN 1 ELSE 0 END) AS pending_ai,
                  COUNT(DISTINCT document_id) AS documents
                FROM canonical_records
                GROUP BY clinic_id
                """
            )
            return [dict(r) for r in cur.fetchall()]

    def patch_ai_resolution(
        self, original_name: str, canonical: str, confidence: float, method: str
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE canonical_records
                SET test_name_canonical = ?,
                    normalization_method = ?,
                    normalization_confidence = ?,
                    pending_ai = 'false',
                    resolved_ai = 'true'
                WHERE lower(test_name_original) = lower(?) AND pending_ai = 'true'
                """,
                (canonical, method, str(confidence), original_name),
            )
            conn.commit()
            return cur.rowcount

    def pending_ai_names(self, limit: int = 100) -> list[str]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT DISTINCT test_name_original FROM canonical_records
                WHERE pending_ai = 'true' AND test_name_original IS NOT NULL
                LIMIT ?
                """,
                (limit,),
            )
            return [r[0] for r in cur.fetchall()]

    def record_run(self, stats: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline_runs
                (started_at, finished_at, files_total, files_ok, files_failed, files_dup, rows_written)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stats.get("started_at"),
                    stats.get("finished_at"),
                    stats.get("files_total", 0),
                    stats.get("files_ok", 0),
                    stats.get("files_failed", 0),
                    stats.get("files_dup", 0),
                    stats.get("rows_written", 0),
                ),
            )
            conn.commit()

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in cur.fetchall()]


class BigQueryRecordStore(RecordStore):
    def __init__(self, settings: Settings | None = None):
        from google.cloud import bigquery

        self.settings = settings or get_settings()
        self.client = bigquery.Client(project=self.settings.gcp_project_id or None)
        self.dataset = self.settings.bq_dataset
        self.table = self.settings.bq_table
        self.deadletter = self.settings.bq_deadletter_table
        self._bq = bigquery

    @property
    def table_id(self) -> str:
        return f"{self.client.project}.{self.dataset}.{self.table}"

    def ensure_schema(self) -> None:
        dataset_ref = self._bq.Dataset(f"{self.client.project}.{self.dataset}")
        dataset_ref.location = "US"
        try:
            self.client.get_dataset(dataset_ref)
        except Exception:
            self.client.create_dataset(dataset_ref, exists_ok=True)

        schema = [self._bq.SchemaField(c, "STRING") for c in CANONICAL_COLUMNS]
        try:
            existing = self.client.get_table(self.table_id)
            existing_names = {f.name for f in existing.schema}
            missing = [c for c in CANONICAL_COLUMNS if c not in existing_names]
            if missing:
                # Incompatible legacy table — recreate with full canonical schema
                self.client.delete_table(self.table_id, not_found_ok=True)
                table = self._bq.Table(self.table_id, schema=schema)
                self.client.create_table(table)
            else:
                # Table OK
                pass
        except Exception:
            table = self._bq.Table(self.table_id, schema=schema)
            self.client.create_table(table, exists_ok=True)

        dl = self._bq.Table(
            f"{self.client.project}.{self.dataset}.{self.deadletter}",
            schema=[
                self._bq.SchemaField("file_path", "STRING"),
                self._bq.SchemaField("reason", "STRING"),
                self._bq.SchemaField("correlation_id", "STRING"),
                self._bq.SchemaField("payload", "STRING"),
                self._bq.SchemaField("created_at", "TIMESTAMP"),
            ],
        )
        self.client.create_table(dl, exists_ok=True)

    def upsert_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        """Idempotent load via MERGE on row_id (stream-friendly staging)."""
        rows = [{c: _serialize(r.get(c)) for c in CANONICAL_COLUMNS} for r in rows]
        if not rows:
            return 0
        staging = f"{self.table_id}_staging_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        job = self.client.load_table_from_json(
            rows,
            staging,
            job_config=self._bq.LoadJobConfig(
                schema=[self._bq.SchemaField(c, "STRING") for c in CANONICAL_COLUMNS],
                write_disposition="WRITE_TRUNCATE",
            ),
        )
        job.result()
        set_clause = ", ".join(f"T.{c}=S.{c}" for c in CANONICAL_COLUMNS if c != "row_id")
        insert_cols = ", ".join(CANONICAL_COLUMNS)
        insert_vals = ", ".join(f"S.{c}" for c in CANONICAL_COLUMNS)
        merge_sql = f"""
        MERGE `{self.table_id}` T
        USING `{staging}` S
        ON T.row_id = S.row_id
        WHEN MATCHED THEN UPDATE SET {set_clause}
        WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
        """
        self.client.query(merge_sql).result()
        self.client.delete_table(staging, not_found_ok=True)
        return len(rows)

    def insert_dead_letter(self, entry: dict[str, Any]) -> None:
        table = f"{self.client.project}.{self.dataset}.{self.deadletter}"
        self.client.insert_rows_json(
            table,
            [
                {
                    "file_path": entry.get("file_path"),
                    "reason": entry.get("reason"),
                    "correlation_id": entry.get("correlation_id"),
                    "payload": json.dumps(entry.get("payload"), default=str),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )

    def fetch_all(self, limit: int = 500) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM `{self.table_id}` ORDER BY processed_at DESC LIMIT @limit"
        job = self.client.query(
            sql,
            job_config=self._bq.QueryJobConfig(
                query_parameters=[self._bq.ScalarQueryParameter("limit", "INT64", limit)]
            ),
        )
        return [dict(r) for r in job.result()]

    def fetch_flagged(self, limit: int = 200) -> list[dict[str, Any]]:
        sql = f"""
        SELECT * FROM `{self.table_id}`
        WHERE test_analytics IN ('Above Range','Below Range','Outlier','Invalid')
           OR pending_ai = 'true'
        ORDER BY processed_at DESC LIMIT @limit
        """
        job = self.client.query(
            sql,
            job_config=self._bq.QueryJobConfig(
                query_parameters=[self._bq.ScalarQueryParameter("limit", "INT64", limit)]
            ),
        )
        return [dict(r) for r in job.result()]

    def clinic_stats(self) -> list[dict[str, Any]]:
        sql = f"""
        SELECT clinic_id,
          COUNT(*) AS total_rows,
          COUNTIF(test_analytics IN ('Above Range','Below Range','Outlier','Invalid')) AS flagged,
          COUNTIF(pending_ai = 'true') AS pending_ai,
          COUNT(DISTINCT document_id) AS documents
        FROM `{self.table_id}`
        GROUP BY clinic_id
        """
        return [dict(r) for r in self.client.query(sql).result()]

    def patch_ai_resolution(
        self, original_name: str, canonical: str, confidence: float, method: str
    ) -> int:
        sql = f"""
        UPDATE `{self.table_id}`
        SET test_name_canonical = @canonical,
            normalization_method = @method,
            normalization_confidence = @confidence,
            pending_ai = 'false',
            resolved_ai = 'true'
        WHERE LOWER(test_name_original) = LOWER(@original) AND pending_ai = 'true'
        """
        job = self.client.query(
            sql,
            job_config=self._bq.QueryJobConfig(
                query_parameters=[
                    self._bq.ScalarQueryParameter("canonical", "STRING", canonical),
                    self._bq.ScalarQueryParameter("method", "STRING", method),
                    self._bq.ScalarQueryParameter("confidence", "STRING", str(confidence)),
                    self._bq.ScalarQueryParameter("original", "STRING", original_name),
                ]
            ),
        )
        result = job.result()
        return result.num_dml_affected_rows or 0

    def pending_ai_names(self, limit: int = 100) -> list[str]:
        sql = f"""
        SELECT DISTINCT test_name_original
        FROM `{self.table_id}`
        WHERE pending_ai = 'true' AND test_name_original IS NOT NULL
        LIMIT @limit
        """
        job = self.client.query(
            sql,
            job_config=self._bq.QueryJobConfig(
                query_parameters=[self._bq.ScalarQueryParameter("limit", "INT64", limit)]
            ),
        )
        return [r[0] for r in job.result()]


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def get_record_store(settings: Settings | None = None) -> RecordStore:
    settings = settings or get_settings()
    if settings.is_gcp:
        return BigQueryRecordStore(settings)
    return SQLiteRecordStore(settings)
