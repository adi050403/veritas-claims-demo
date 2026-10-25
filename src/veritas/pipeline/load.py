from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from veritas.storage.db import RecordStore
from veritas.utils.hashing import row_id


def to_canonical_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for r in rows:
        rid = row_id(
            str(r.get("document_id") or ""),
            str(r.get("record_type") or ""),
            str(r.get("test_name_original") or r.get("medicine") or r.get("diagnosis") or ""),
            str(r.get("page_no") or ""),
            str(r.get("result_text") or r.get("dose") or ""),
            str(r.get("content_hash") or ""),
        )
        out.append(
            {
                "row_id": rid,
                "document_id": r.get("document_id"),
                "record_type": r.get("record_type"),
                "file_gcs_path": r.get("file_gcs_path"),
                "trace_id": r.get("trace_id"),
                "correlation_id": r.get("correlation_id"),
                "source_system": r.get("source_system"),
                "clinic_id": r.get("clinic_id"),
                "claim_no": r.get("claim_no"),
                "nt_code": r.get("nt_code"),
                "consumer_client_id": r.get("consumer_client_id"),
                "destination_identifier": r.get("destination_identifier"),
                "patient_name": r.get("patient_name"),
                "age": r.get("age"),
                "age_years": r.get("age_years"),
                "gender": r.get("gender"),
                "uhid": r.get("uhid"),
                "hospital_name": r.get("hospital_name"),
                "doctor_name": r.get("doctor_name"),
                "bill_date": r.get("bill_date"),
                "reports_date": r.get("reports_date"),
                "admission_date": r.get("admission_date"),
                "discharge_date": r.get("discharge_date"),
                "diagnosis": r.get("diagnosis"),
                "brief_history": r.get("brief_history"),
                "general_examinations": r.get("general_examinations"),
                "recommendations": r.get("recommendations"),
                "hospital_address": r.get("hospital_address"),
                "ward": r.get("ward"),
                "post_discharge_advice": r.get("post_discharge_advice"),
                "course_during_hospitalisation": r.get("course_during_hospitalisation"),
                "test_name_canonical": r.get("test_name_canonical"),
                "test_name_original": r.get("test_name_original"),
                "result_value": r.get("result_value"),
                "result_text": r.get("result_text"),
                "unit_canonical": r.get("unit_canonical"),
                "unit_original": r.get("unit_original"),
                "range_low": r.get("range_low"),
                "range_high": r.get("range_high"),
                "range_text": r.get("range_text"),
                "test_analytics": r.get("test_analytics"),
                "normalization_method": r.get("normalization_method"),
                "normalization_confidence": r.get("normalization_confidence"),
                "pending_ai": r.get("pending_ai"),
                "resolved_ai": r.get("resolved_ai"),
                "medicine": r.get("medicine"),
                "medicine_generic": r.get("medicine_generic"),
                "dose": r.get("dose"),
                "frequency": r.get("frequency"),
                "medicine_type": r.get("medicine_type"),
                "medicine_injections_investigation": r.get("medicine_injections_investigation"),
                "page_no": r.get("page_no"),
                "content_hash": r.get("content_hash"),
                "processed_at": now,
                "ingested_at": r.get("ingested_at"),
                "raw_json": json.dumps(
                    {k: r.get(k) for k in ("metadetails", "source_analytics") if r.get(k)},
                    default=str,
                ),
            }
        )
    return out


def stream_load(store: RecordStore, rows: list[dict[str, Any]]) -> int:
    """Idempotent MERGE/UPSERT on row_id — does not wait for Gemini."""
    records = to_canonical_records(rows)
    return store.upsert_rows(records)
