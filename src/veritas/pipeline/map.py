from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from veritas.pipeline.ingest import IngestedFile
from veritas.registry import load_clinic_config
from veritas.utils.paths import get_by_path, meta_to_dict


@dataclass
class MappedRow:
    record_type: str
    fields: dict[str, Any] = field(default_factory=dict)
    source_section_index: int = 0


def map_file(ingested: IngestedFile) -> list[MappedRow]:
    """Config-driven field-path mapping → canonical intermediate rows per source."""
    payload = ingested.payload
    meta = ingested.meta or meta_to_dict(get_by_path(payload, "$.data.metaDetails") or [])
    source_system = meta.get("source_system") or meta.get("SourceSystem")
    cfg = load_clinic_config(source_system)

    envelope = cfg.get("envelope") or {}
    base = {
        "trace_id": get_by_path(payload, envelope.get("trace_id", "$.traceId")),
        "document_id": get_by_path(payload, envelope.get("document_id", "$.data.documentId")),
        "correlation_id": get_by_path(
            payload, envelope.get("correlation_id", "$.data.correlationId")
        ),
        "source_system": source_system,
        "clinic_id": cfg.get("clinic_id") or ingested.clinic_id,
        "claim_no": meta.get("claim_no"),
        "nt_code": meta.get("nt_code"),
        "consumer_client_id": meta.get("ConsumerClientId") or meta.get("consumer_client_id"),
        "destination_identifier": meta.get("DestinationIdentifier"),
        "file_gcs_path": ingested.path,
        "content_hash": ingested.content_hash,
        "ingested_at": ingested.ingested_at,
        "metadetails": meta,
    }

    rows: list[MappedRow] = []
    details = get_by_path(payload, envelope.get("response_details", "$.data.responseDetails")) or []
    for idx, section in enumerate(details):
        if not isinstance(section, dict):
            continue
        classifier = section.get("classifier")
        status = section.get("status")
        if status and str(status).lower() not in {"success", "ok", "true"}:
            continue

        if classifier == (cfg.get("lab_report") or {}).get("classifier", "lab_report"):
            rows.extend(_map_lab(section, cfg, base, idx))
        elif classifier == (cfg.get("discharge_summary") or {}).get(
            "classifier", "discharge_summary"
        ):
            rows.extend(_map_discharge(section, cfg, base, idx))
        else:
            rows.append(
                MappedRow(
                    record_type=classifier or "unknown",
                    fields={**base, "raw_section": section},
                    source_section_index=idx,
                )
            )
    return rows


def _map_lab(section: dict, cfg: dict, base: dict, idx: int) -> list[MappedRow]:
    lab = cfg.get("lab_report") or {}
    info_paths = lab.get("basic_info") or {}
    info = {k: get_by_path(section, v) for k, v in info_paths.items()}
    skip = {s.lower() for s in (lab.get("skip_test_names") or [])}
    test_fields = lab.get("test_fields") or {}
    tests = get_by_path(section, lab.get("tests_path", "$.data.report_details")) or []

    out: list[MappedRow] = []
    for t in tests:
        if not isinstance(t, dict):
            continue
        raw_name = t.get(test_fields.get("test_name", "test_name"))
        if raw_name is None or str(raw_name).strip().lower() in skip:
            continue
        if str(raw_name).strip().lower() == "test_name":
            continue
        fields = {
            **base,
            **info,
            "test_name_original": raw_name,
            "result_text_original": t.get(test_fields.get("result", "result")),
            "unit_original": t.get(test_fields.get("unit", "unit")),
            "range_text_original": t.get(test_fields.get("range", "range")),
            "page_no": t.get(test_fields.get("page_no", "page_no")),
            "source_analytics": t.get(test_fields.get("source_analytics", "test_analytics")),
        }
        out.append(MappedRow(record_type="lab_result", fields=fields, source_section_index=idx))
    return out


def _map_discharge(section: dict, cfg: dict, base: dict, idx: int) -> list[MappedRow]:
    ds = cfg.get("discharge_summary") or {}
    field_paths = ds.get("fields") or {}
    header = {k: get_by_path(section, v) for k, v in field_paths.items()}
    # Always emit one header/summary row for audit + demographics
    summary = MappedRow(
        record_type="discharge_summary",
        fields={**base, **header},
        source_section_index=idx,
    )
    out = [summary]

    med_fields = ds.get("medication_fields") or {}
    meds = get_by_path(section, ds.get("medications_path", "$.data.dischargeMedications")) or []
    for med in meds:
        if not isinstance(med, dict):
            continue
        medicine = med.get(med_fields.get("medicine", "medicine"))
        if not medicine:
            continue
        out.append(
            MappedRow(
                record_type="medication",
                fields={
                    **base,
                    **header,
                    "medicine": medicine,
                    "dose": med.get(med_fields.get("dose", "dose")),
                    "frequency": med.get(med_fields.get("frequency", "frequency")),
                    "medicine_type": med.get(med_fields.get("type", "type")),
                },
                source_section_index=idx,
            )
        )
    return out
