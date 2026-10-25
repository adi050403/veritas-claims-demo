from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from veritas.pipeline.validate import validate_rows


def test_within_range():
    rows = [
        {
            "record_type": "lab_result",
            "result_value": 14.0,
            "range_low": 13.0,
            "range_high": 17.0,
            "_outlier_bounds": {"low": 3.0, "high": 25.0},
            "_numeric_expected": True,
            "_reference_range": {"low": 13.0, "high": 17.0},
        }
    ]
    assert validate_rows(rows)[0]["test_analytics"] == "Within Range"


def test_above_and_outlier():
    above = validate_rows(
        [
            {
                "record_type": "lab_result",
                "result_value": 18.0,
                "range_low": 13.0,
                "range_high": 17.0,
                "_outlier_bounds": {"low": 3.0, "high": 25.0},
                "_numeric_expected": True,
                "_reference_range": {"low": 13.0, "high": 17.0},
            }
        ]
    )[0]
    assert above["test_analytics"] == "Above Range"

    outlier = validate_rows(
        [
            {
                "record_type": "lab_result",
                "result_value": 999.0,
                "range_low": 13.0,
                "range_high": 17.0,
                "_outlier_bounds": {"low": 3.0, "high": 25.0},
                "_numeric_expected": True,
                "_reference_range": {"low": 13.0, "high": 17.0},
            }
        ]
    )[0]
    assert outlier["test_analytics"] == "Outlier"


def test_invalid_non_numeric():
    rows = [
        {
            "record_type": "lab_result",
            "result_value": None,
            "result_text": "###ERROR###",
            "_numeric_expected": True,
            "_outlier_bounds": {},
            "_reference_range": {},
        }
    ]
    assert validate_rows(rows)[0]["test_analytics"] == "Invalid"
