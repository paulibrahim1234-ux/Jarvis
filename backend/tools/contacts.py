"""
macOS Contacts.app reader — direct SQLite access.

Reads the AddressBook-v22.abcddb SQLite database directly instead of going
through AppleScript (which times out on even trivial queries). Returns a
normalized handle → display name map that the iMessage widget (and future
mail/calendar widgets) use to resolve phone numbers / emails.

Zero permissions required beyond Full Disk Access (already granted for
iMessage). Read-only. Refreshes on a TTL.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Optional


_ADDRESSBOOK_ROOT = Path.home() / "Library" / "Application Support" / "AddressBook" / "Sources"

# Cache the lookup map so we don't hit the DB on every request.
_CACHE: dict = {"lookup": None, "ts": 0.0}
_TTL_SECONDS = 300  # refresh every 5 min


def _normalize(handle: str) -> str:
    """Last 10 digits for phones; lowercased trimmed string for emails."""
    if not handle:
        return ""
    if "@" in handle:
        return handle.strip().lower()
    digits = re.sub(r"\D", "", handle)
    return digits[-10:] if len(digits) >= 10 else digits


def _discover_db() -> Optional[Path]:
    """
    macOS stores a DB per CardDAV source under a UUID directory. Usually
    there's only one; we pick the largest AddressBook-v22.abcddb we find.
    """
    if not _ADDRESSBOOK_ROOT.exists():
        return None
    candidates: list[Path] = []
    for source in _ADDRESSBOOK_ROOT.iterdir():
        db = source / "AddressBook-v22.abcddb"
        if db.exists():
            candidates.append(db)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def _build_lookup() -> dict[str, str]:
    db_path = _discover_db()
    if db_path is None:
        return {}

    lookup: dict[str, str] = {}
    try:
        # Read-only — no chance of writing even if something went wrong.
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        cur = con.cursor()

        cur.execute(
            """
            SELECT
              COALESCE(r.ZFIRSTNAME, '') ||
              CASE WHEN r.ZLASTNAME IS NOT NULL THEN ' ' || r.ZLASTNAME ELSE '' END,
              p.ZFULLNUMBER
            FROM ZABCDRECORD r
            JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
            WHERE p.ZFULLNUMBER IS NOT NULL
            """
        )
        for name, phone in cur.fetchall():
            if not name or not phone:
                continue
            key = _normalize(phone)
            if key and key not in lookup:
                lookup[key] = name.strip()

        cur.execute(
            """
            SELECT
              COALESCE(r.ZFIRSTNAME, '') ||
              CASE WHEN r.ZLASTNAME IS NOT NULL THEN ' ' || r.ZLASTNAME ELSE '' END,
              e.ZADDRESS
            FROM ZABCDRECORD r
            JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK
            WHERE e.ZADDRESS IS NOT NULL
            """
        )
        for name, email in cur.fetchall():
            if not name or not email:
                continue
            key = _normalize(email)
            if key and key not in lookup:
                lookup[key] = name.strip()

        con.close()
    except Exception:
        # DB might be locked or schema may have drifted — empty lookup is fine.
        return {}

    return lookup


def get_lookup(force_refresh: bool = False) -> dict[str, str]:
    """Return normalized-handle → display-name map, cached for _TTL_SECONDS."""
    now = time.time()
    if (
        not force_refresh
        and _CACHE["lookup"] is not None
        and now - _CACHE["ts"] < _TTL_SECONDS
    ):
        return _CACHE["lookup"]
    lookup = _build_lookup()
    _CACHE["lookup"] = lookup
    _CACHE["ts"] = now
    return lookup


def resolve(handle: str) -> Optional[str]:
    """Resolve one handle to a display name, or None if unknown."""
    if not handle:
        return None
    # Group chat: resolve each, join with commas; leave raw if all unknown.
    if "," in handle:
        parts = [p.strip() for p in handle.split(",") if p.strip()]
        names = [resolve(p) or p for p in parts]
        return ", ".join(names)
    lookup = get_lookup()
    return lookup.get(_normalize(handle))
