from __future__ import annotations

from typing import Any


def get_by_path(obj: Any, path: str, default: Any = None) -> Any:
    """Resolve a simple JSONPath-like ``$.a.b[0].c`` expression."""
    if not path:
        return default
    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$"):
        path = path[1:].lstrip(".")

    cur: Any = obj
    for part in path.split("."):
        if cur is None:
            return default
        if "[" in part and part.endswith("]"):
            name, idx_s = part[:-1].split("[", 1)
            if name:
                if not isinstance(cur, dict) or name not in cur:
                    return default
                cur = cur[name]
            try:
                idx = int(idx_s)
            except ValueError:
                return default
            if not isinstance(cur, list) or idx >= len(cur):
                return default
            cur = cur[idx]
        else:
            if isinstance(cur, dict):
                cur = cur.get(part, default if part == path.split(".")[-1] else None)
            else:
                return default
    return cur if cur is not None else default


def meta_to_dict(meta_details: list | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in meta_details or []:
        if isinstance(item, dict) and "key" in item:
            out[str(item["key"])] = "" if item.get("value") is None else str(item["value"])
    return out
