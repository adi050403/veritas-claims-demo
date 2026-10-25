from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from veritas.pipeline.map import MappedRow
from veritas.pipeline.standardise import standardise_rows
from veritas.registry import Registry


def test_haemoglobin_variant_and_numeric():
    registry = Registry()
    rows = [
        MappedRow(
            record_type="lab_result",
            fields={
                "test_name_original": "aemoglobin",
                "result_text_original": "14.2 g/dL",
                "unit_original": "g/dL",
                "range_text_original": "13-17",
                "age": "33Y11M",
                "gender": "M",
                "bill_date": "11-10-2025",
            },
        )
    ]
    out = standardise_rows(rows, registry)[0]
    assert out["test_name_canonical"] == "HAEMOGLOBIN"
    assert out["normalization_method"] in {"exact_registry", "fuzzy", "nlp"}
    assert out["result_value"] == 14.2
    assert out["gender"] == "Male"
    assert out["bill_date"] == "2025-10-11"
    assert out["age_years"] is not None


def test_unit_harmonisation_million_cells():
    registry = Registry()
    rows = [
        MappedRow(
            record_type="lab_result",
            fields={
                "test_name_original": "WBC COUNT",
                "result_text_original": "9.7",
                "unit_original": "mil/cu.mm",
                "range_text_original": "4000-10000",
            },
        )
    ]
    out = standardise_rows(rows, registry)[0]
    assert out["test_name_canonical"] == "WHITE BLOOD CELL COUNT"
    assert out["unit_canonical"] == "cells/cu.mm"
    assert out["result_value"] == 9.7 * 1_000_000


def test_medicine_mapping():
    registry = Registry()
    rows = [
        MappedRow(
            record_type="medication",
            fields={"medicine": "TAB DOLO 650", "dose": "1", "frequency": "TID"},
        )
    ]
    out = standardise_rows(rows, registry)[0]
    assert out["medicine_generic"] == "Paracetamol"
