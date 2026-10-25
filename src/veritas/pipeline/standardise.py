from __future__ import annotations

from typing import Any

from veritas.pipeline.map import MappedRow
from veritas.registry import Registry
from veritas.resolution.cascade import TestNameResolver
from veritas.utils.parsers import (
    normalise_age,
    normalise_date,
    normalise_gender,
    parse_numeric,
    parse_range,
)


def standardise_rows(
    rows: list[MappedRow],
    registry: Registry,
    resolver: TestNameResolver | None = None,
) -> list[dict[str, Any]]:
    """Numeric parse, units, dates, medicine mapping, test-name cascade."""
    resolver = resolver or TestNameResolver(registry)
    out: list[dict[str, Any]] = []
    for row in rows:
        f = dict(row.fields)
        f["record_type"] = row.record_type

        # Demographics
        age_text, age_years = normalise_age(f.get("age"))
        f["age"] = age_text
        f["age_years"] = age_years
        f["gender"] = normalise_gender(f.get("gender"))
        for dk in (
            "bill_date",
            "reports_date",
            "admission_date",
            "discharge_date",
        ):
            if f.get(dk):
                f[dk] = normalise_date(f.get(dk))

        # Medicine brand → generic
        if row.record_type == "medication" or f.get("medicine"):
            brand = f.get("medicine")
            f["medicine_generic"] = registry.map_medicine(brand)

        if isinstance(f.get("medicine_injections_investigation"), list):
            f["medicine_injections_investigation"] = "; ".join(
                str(x) for x in f["medicine_injections_investigation"]
            )

        # Lab result standardisation
        if row.record_type == "lab_result":
            raw_name = f.get("test_name_original")
            resolution = resolver.resolve(raw_name)
            f["test_name_canonical"] = resolution.canonical
            f["normalization_method"] = resolution.method
            f["normalization_confidence"] = resolution.confidence
            f["pending_ai"] = resolution.pending_ai
            f["resolved_ai"] = False

            result_val, result_text = parse_numeric(f.get("result_text_original"))
            f["result_text"] = result_text
            low, high, range_text = parse_range(f.get("range_text_original"))
            f["range_low"] = low
            f["range_high"] = high
            f["range_text"] = range_text

            meta = registry.test_meta(resolution.canonical) if resolution.canonical else {}
            # Prefer report range; fall back to registry
            if f["range_low"] is None and f["range_high"] is None and meta.get("reference_range"):
                f["range_low"] = meta["reference_range"].get("low")
                f["range_high"] = meta["reference_range"].get("high")

            unit_family = meta.get("unit_family")
            converted, unit_can, _ok = registry.convert_unit(
                unit_family, f.get("unit_original"), result_val
            )
            # Heuristic: platelet / WBC values reported in lakhs/millions
            if (
                resolution.canonical in {"Platelet Count", "WHITE BLOOD CELL COUNT"}
                and converted is not None
                and converted < 1000
                and (f.get("unit_original") or "").lower() in {"mil/cu.mm", "lac/cmm", "lakhs/cumm"}
            ):
                pass  # already converted via units.yaml
            f["result_value"] = converted
            f["unit_canonical"] = unit_can or meta.get("canonical_unit") or f.get("unit_original")
            f["_numeric_expected"] = bool(meta.get("numeric_expected", True))
            f["_outlier_bounds"] = meta.get("outlier_bounds") or {}
            f["_reference_range"] = {
                "low": f.get("range_low"),
                "high": f.get("range_high"),
            }
        else:
            f["pending_ai"] = False
            f["resolved_ai"] = False

        out.append(f)
    return out
