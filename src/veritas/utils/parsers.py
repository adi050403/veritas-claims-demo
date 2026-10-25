from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

_NUM_RE = re.compile(
    r"(?P<sign>[-+]?)(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
)
_AGE_RE = re.compile(
    r"(?:(?P<y>\d+)\s*[Yy](?:ears?)?)?"
    r"(?:\s*(?P<m>\d+)\s*[Mm](?:onths?)?)?"
    r"(?:\s*(?P<d>\d+)\s*[Dd](?:ays?)?)?"
)
_RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*[-–to]+\s*(?P<high>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LT_RE = re.compile(r"[<<≤]\s*(?P<high>\d+(?:\.\d+)?)")
_GT_RE = re.compile(r"[>≥]\s*(?P<low>\d+(?:\.\d+)?)")

_DATE_FORMATS = (
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
)


def parse_numeric(value: object) -> tuple[Optional[float], Optional[str]]:
    """Extract leading numeric from mixed strings like '120000 cells/cu.mm'."""
    if value is None:
        return None, None
    if isinstance(value, (int, float)):
        return float(value), None
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NIL", "NONE", "-", "NULL"}:
        return None, text or None
    # qualitative results
    if re.fullmatch(r"[A-Za-z][A-Za-z\s/+.-]*", text) and not _NUM_RE.search(text):
        return None, text
    m = _NUM_RE.search(text.replace(" ", ""))
    if not m:
        # try with spaces kept
        m = _NUM_RE.search(text)
    if not m:
        return None, text
    num_s = m.group("sign") + m.group("num").replace(",", "")
    try:
        return float(num_s), text
    except ValueError:
        return None, text


def parse_range(range_text: object) -> tuple[Optional[float], Optional[float], Optional[str]]:
    if range_text is None:
        return None, None, None
    text = str(range_text).strip()
    if not text or text.lower() == "range":
        return None, None, text or None
    m = _RANGE_RE.search(text.replace(" ", ""))
    if not m:
        m = _RANGE_RE.search(text)
    if m:
        return float(m.group("low")), float(m.group("high")), text
    m = _LT_RE.search(text)
    if m:
        return None, float(m.group("high")), text
    m = _GT_RE.search(text)
    if m:
        return float(m.group("low")), None, text
    return None, None, text


def normalise_gender(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if "redacted" in text or not text:
        return str(value).strip() if value else None
    if text in {"m", "male", "man", "boy"}:
        return "Male"
    if text in {"f", "female", "woman", "girl"}:
        return "Female"
    if text in {"o", "other", "unknown", "u"}:
        return "Other"
    return str(value).strip()


def normalise_age(value: object) -> tuple[Optional[str], Optional[float]]:
    """Return (age_text_canonical, age_years). Handles '33Y11M265D' style."""
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    if "redacted" in text.lower():
        return text, None
    # plain number
    try:
        years = float(text)
        return f"{int(years)}Y", years
    except ValueError:
        pass
    m = _AGE_RE.fullmatch(text.replace(" ", "")) or _AGE_RE.search(text)
    if not m or not any(m.group(g) for g in ("y", "m", "d")):
        return text, None
    y = int(m.group("y") or 0)
    mo = int(m.group("m") or 0)
    d = int(m.group("d") or 0)
    age_years = y + mo / 12.0 + d / 365.25
    canonical = f"{y}Y{mo}M{d}D" if (mo or d) else f"{y}Y"
    return canonical, round(age_years, 3)


def normalise_date(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text
