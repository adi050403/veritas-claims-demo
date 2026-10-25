from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from veritas.settings import Settings, get_settings


class Registry:
    """Canonical test / unit / medicine registry with optional learned aliases."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        root = Path(self.settings.config_root) / "registry"
        self.test_path = root / "test_names.yaml"
        self.units_path = root / "units.yaml"
        self.meds_path = root / "medicines.yaml"
        self.reload()

    def reload(self) -> None:
        self.tests = yaml.safe_load(self.test_path.read_text(encoding="utf-8")) or {}
        self.units = yaml.safe_load(self.units_path.read_text(encoding="utf-8")) or {}
        self.meds = yaml.safe_load(self.meds_path.read_text(encoding="utf-8")) or {}
        self._alias_index: dict[str, str] = {}
        for canonical, meta in (self.tests.get("canonical_tests") or {}).items():
            for alias in meta.get("aliases") or []:
                self._alias_index[_norm(alias)] = canonical
            self._alias_index[_norm(canonical)] = canonical
        for alias, canonical in (self.tests.get("learned_aliases") or {}).items():
            self._alias_index[_norm(alias)] = canonical

    def exact_lookup(self, name: str) -> str | None:
        return self._alias_index.get(_norm(name))

    def all_canonical_names(self) -> list[str]:
        return list((self.tests.get("canonical_tests") or {}).keys())

    def all_alias_pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for canonical, meta in (self.tests.get("canonical_tests") or {}).items():
            for alias in meta.get("aliases") or []:
                pairs.append((alias, canonical))
            pairs.append((canonical, canonical))
        for alias, canonical in (self.tests.get("learned_aliases") or {}).items():
            pairs.append((alias, canonical))
        return pairs

    def test_meta(self, canonical: str) -> dict[str, Any]:
        return deepcopy((self.tests.get("canonical_tests") or {}).get(canonical) or {})

    def convert_unit(
        self, unit_family: str | None, unit_original: str | None, value: float | None
    ) -> tuple[float | None, str | None, bool]:
        """Return (converted_value, canonical_unit, ok)."""
        if not unit_family:
            return value, unit_original, True
        family = (self.units.get("unit_families") or {}).get(unit_family) or {}
        canonical = family.get("canonical")
        aliases = family.get("aliases") or {}
        if not unit_original:
            return value, canonical, True
        # direct
        if unit_original in aliases:
            factor = aliases[unit_original]
            return (None if value is None else value * factor), canonical, True
        # case-insensitive
        for k, factor in aliases.items():
            if k.lower() == str(unit_original).lower():
                return (None if value is None else value * factor), canonical, True
        return value, unit_original, False

    def map_medicine(self, brand: str | None) -> str | None:
        if not brand:
            return None
        mapping = self.meds.get("brand_to_generic") or {}
        if brand in mapping:
            return mapping[brand]
        for k, v in mapping.items():
            if k.lower() == brand.lower():
                return v
        return None

    def push_learned_alias(self, original: str, canonical: str) -> None:
        learned = self.tests.setdefault("learned_aliases", {})
        learned[original] = canonical
        self._alias_index[_norm(original)] = canonical
        self.test_path.write_text(
            yaml.safe_dump(self.tests, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().replace("_", " ").split())


def load_clinic_config(source_system: str | None, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    clinics_dir = Path(settings.config_root) / "clinics"
    default = yaml.safe_load((clinics_dir / "default.yaml").read_text(encoding="utf-8"))

    chosen = None
    if source_system:
        path = clinics_dir / f"{source_system}.yaml"
        if path.exists():
            chosen = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not chosen:
        # match by source_systems list
        for path in clinics_dir.glob("*.yaml"):
            if path.name == "default.yaml":
                continue
            cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
            systems = cfg.get("source_systems") or []
            if source_system in systems:
                chosen = cfg
                break

    if not chosen:
        return default

    if chosen.get("extends") == "default":
        return _deep_merge(default, chosen)
    return chosen


def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        if k == "extends":
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out
