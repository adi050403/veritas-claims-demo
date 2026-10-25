from __future__ import annotations

from typing import Any


def validate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Range checks, outlier bounds, unit-family sanity, analytics flag."""
    for row in rows:
        if row.get("record_type") != "lab_result":
            continue

        value = row.get("result_value")
        numeric_expected = row.pop("_numeric_expected", True)
        outlier = row.pop("_outlier_bounds", {}) or {}
        ref = row.pop("_reference_range", {}) or {}
        low = ref.get("low") if ref.get("low") is not None else row.get("range_low")
        high = ref.get("high") if ref.get("high") is not None else row.get("range_high")

        # Invalid: numeric expected but missing/unparseable (and not qualitative)
        text = (row.get("result_text") or "").strip().upper()
        qualitative_ok = text in {
            "POSITIVE",
            "NEGATIVE",
            "REACTIVE",
            "NON-REACTIVE",
            "NOT DETECTED",
            "DETECTED",
            "ABSENT",
            "PRESENT",
            "NIL",
            "NORMAL",
        }

        if value is None:
            if numeric_expected and not qualitative_ok and row.get("result_text"):
                # Could be contradictory multi-value / garbage
                if _looks_contradictory(row.get("result_text")):
                    row["test_analytics"] = "Invalid"
                elif qualitative_ok:
                    row["test_analytics"] = "Within Range"
                else:
                    row["test_analytics"] = "Invalid"
            else:
                row["test_analytics"] = row.get("source_analytics") or "Invalid"
            continue

        o_low = outlier.get("low")
        o_high = outlier.get("high")
        if (o_low is not None and value < o_low) or (o_high is not None and value > o_high):
            row["test_analytics"] = "Outlier"
            continue

        if low is not None and value < float(low):
            row["test_analytics"] = "Below Range"
        elif high is not None and value > float(high):
            row["test_analytics"] = "Above Range"
        else:
            row["test_analytics"] = "Within Range"

    return rows


def _looks_contradictory(text: object) -> bool:
    if text is None:
        return False
    s = str(text)
    # e.g. combined multi-value strings with conflicting markers
    if s.count("/") >= 3 and any(ch.isdigit() for ch in s):
        return True
    if " and " in s.lower() and any(ch.isdigit() for ch in s):
        return True
    return False
