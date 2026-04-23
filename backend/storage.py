"""Tiny JSON storage helper for widget persistence.

Keeps widget route files clean and makes it easy to add more JSON-backed
widgets in the future. Cache root is ~/.cache/jarvis/ (created on demand).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CACHE_DIR = Path.home() / ".cache" / "jarvis"


def _ensure_dir(path: Path) -> None:
    os.makedirs(path.parent, exist_ok=True)


def read_json(path: str | Path, default: Any) -> Any:
    """Read JSON from `path`, returning `default` if file doesn't exist.

    On JSON decode error, returns `default` rather than raising — we'd
    rather a widget render empty state than 500 the whole dashboard.
    """
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: str | Path, obj: Any) -> None:
    """Write `obj` as JSON to `path` (creates parent dirs if needed)."""
    p = Path(path)
    _ensure_dir(p)
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
