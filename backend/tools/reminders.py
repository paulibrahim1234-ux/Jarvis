"""
Reminders.app integration via AppleScript.

WHY a separate module: Reminders is a discrete macOS app with its own AppleScript
dictionary. Keeping the access layer isolated lets the briefing widget treat
"todos" as a simple list while we sync to/from the system app underneath.
"""

import logging
import re
import subprocess
from typing import Optional

_log = logging.getLogger(__name__)

JARVIS_LIST = "Jarvis"  # Default list name. The first call creates it if missing.

# Tokens stripped from titles before dedup comparison — these vary across Haiku
# variants of the same task and cause spurious duplicates.
_NOISE_RE = re.compile(
    r"\b(before\s+expiration|your|or|via|the|and|for|with|from|this|that)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Return a canonical dedup key for a reminder title.

    Lowercases, strips punctuation, drops common noise tokens ("before
    expiration", "your", "or", "/" etc.), and collapses whitespace runs.
    Two titles that differ only in noise tokens produce the same canonical
    key, so the dedup logic can skip the second push.

    WHY here (not widgets.py): reminders.py is the boundary layer for
    Reminders.app. Anything that pushes a reminder uses the same normaliser
    so dedup keys are consistent across call sites.

    >>> _normalize_title("Complete your VSLO application before expiration")
    'complete vslo application'
    >>> _normalize_title("Complete VSLO Application!")
    'complete vslo application'
    """
    s = (title or "").strip().lower()
    s = s.replace("/", " ")          # treat "/" as whitespace (e.g. "yes/no")
    s = _PUNCT_RE.sub(" ", s)        # strip remaining punctuation
    s = _NOISE_RE.sub(" ", s)        # drop noise tokens
    s = _SPACE_RE.sub(" ", s)        # collapse whitespace
    return s.strip()


def _as_str(s: str) -> str:
    """Escape a string for safe AppleScript embedding.

    WHY this order: backslash must be escaped FIRST, otherwise the quote-escape
    below would double-escape an already-escaped backslash and let a trailing
    backslash close the AppleScript string literal early. Matches desktop_apps.py.
    """
    return (
        (s or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _ensure_list_exists() -> None:
    """Create the Jarvis list in Reminders.app if it doesn't exist.

    WHY best-effort: if the user has denied Reminders permission, this silently
    no-ops. Callers will then fail gracefully on the next real operation.
    """
    script = f'''
tell application "Reminders"
    if not (exists list "{JARVIS_LIST}") then
        make new list with properties {{name:"{JARVIS_LIST}"}}
    end if
end tell
'''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        pass  # best-effort — permission denied or app unresponsive


def list_reminders() -> list[dict]:
    """Return all incomplete reminders in the Jarvis list.

    Each dict has: id, title, due_hint, completed, source.
    Returns [] on permission denial or timeout rather than raising.
    """
    _ensure_list_exists()
    # WHY this script shape (two prior bugs collapsed):
    #
    # 1) Delimiter: previously used "\\t" and "\\n" inside the AppleScript
    #    source. AppleScript does NOT interpret those as control characters;
    #    they stay as the literal 4-char strings `\\t` and `\\n`. Python's
    #    split("\\t")/split("\\n") found zero matches and silently dropped
    #    every row. Using `|||FIELD|||` and `|||ROW|||` (matches the pattern
    #    in desktop_apps.py for calendar) is robust against this.
    #
    # 2) Predicate slowness: `reminders of theList whose completed is false`
    #    plus an inner `try/on error` for `due date` was hitting the 8s
    #    subprocess timeout even for tiny lists. Direct enumeration with a
    #    Python-side filter on `completed` is ~5x faster (verified 2.3s on
    #    the same data). We also drop the due-date access here because it
    #    raises on `missing value` and the `try` overhead dominates; the
    #    UI doesn't currently show due-date hints from Reminders, so this
    #    is a free win. Add it back via a separate property check later.
    script = f'''
tell application "Reminders"
    set theList to list "{JARVIS_LIST}"
    set out to ""
    repeat with r in (reminders of theList)
        if not (completed of r) then
            set rid to id of r as text
            set rname to name of r as text
            set out to out & rid & "|||FIELD|||" & rname & "|||FIELD|||" & "" & "|||ROW|||"
        end if
    end repeat
    return out
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=12,
        )
        if result.returncode != 0:
            return []
        items = []
        for line in result.stdout.strip().split("|||ROW|||"):
            if not line.strip():
                continue
            parts = line.split("|||FIELD|||")
            if len(parts) >= 2:
                # WHY `text` (not `title`): the BriefingTodo schema (defined
                # in frontend/src/lib/api.ts and the briefing's manual+auto
                # todos) uses `text` as the display field. We mirror that
                # here so the briefing can merge all three sources without
                # any field renaming.
                items.append({
                    "id": parts[0].strip(),
                    "text": parts[1].strip(),
                    "due_hint": parts[2].strip() if len(parts) > 2 else "",
                    "completed": False,
                    "source": "reminders",
                })
        return items
    except subprocess.TimeoutExpired:
        return []


def add_reminder(title: str, due_hint: Optional[str] = None) -> Optional[str]:
    """Add a reminder to the Jarvis list. Returns the new reminder's id, or None on failure.

    WHY no due-date parsing: Reminders.app accepts AppleScript date strings but the
    format is locale-dependent and brittle. We omit due-date setting for now to
    avoid date-format parsing bugs; due_hint is stored as a string hint only.
    """
    _ensure_list_exists()
    safe_title = _as_str(title)
    script = f'''
tell application "Reminders"
    set newR to make new reminder at end of list "{JARVIS_LIST}" with properties {{name:"{safe_title}"}}
    return id of newR as text
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=12,
        )
        if result.returncode == 0:
            rid = result.stdout.strip()
            if rid:
                return rid
            # AppleScript returned exit 0 but empty stdout — treat as failure.
            _log.warning("add_reminder: osascript exit 0 but empty id (stderr=%r)", result.stderr.strip())
            return None
        _log.warning(
            "add_reminder: osascript exit %d for title=%r; stderr=%r",
            result.returncode, title, result.stderr.strip()
        )
        return None
    except subprocess.TimeoutExpired:
        _log.warning("add_reminder: osascript timed out for title=%r", title)
        return None


def complete_reminder(reminder_id: str) -> bool:
    """Mark a reminder as completed by its AppleScript id. Returns True on success.

    WHY search by id: Reminders.app ids are stable UUIDs unlike array indices.
    """
    safe_id = _as_str(reminder_id)
    script = f'''
tell application "Reminders"
    set r to first reminder of list "Jarvis" whose id is "{safe_id}"
    set completed of r to true
    return "ok"
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=12,
        )
        return "ok" in result.stdout
    except subprocess.TimeoutExpired:
        return False


def delete_reminder(reminder_id: str) -> bool:
    """Delete a reminder by its AppleScript id. Returns True on success."""
    safe_id = _as_str(reminder_id)
    script = f'''
tell application "Reminders"
    set r to first reminder of list "Jarvis" whose id is "{safe_id}"
    delete r
    return "ok"
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=12,
        )
        return "ok" in result.stdout
    except subprocess.TimeoutExpired:
        return False


def list_all_reminders_with_completed() -> list[dict]:
    """Return ALL reminders (incomplete + completed) in the Jarvis list.

    WHY: cleanup/dedupe operations need to see the full set including
    completed items so they don't accidentally re-create deleted entries.
    Returns [] on permission denial or timeout rather than raising.
    """
    _ensure_list_exists()
    script = f'''
tell application "Reminders"
    set theList to list "{JARVIS_LIST}"
    set out to ""
    repeat with r in (reminders of theList)
        set rid to id of r as text
        set rname to name of r as text
        set rcompleted to completed of r as text
        set out to out & rid & "|||FIELD|||" & rname & "|||FIELD|||" & rcompleted & "|||ROW|||"
    end repeat
    return out
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        items: list[dict] = []
        for line in result.stdout.strip().split("|||ROW|||"):
            if not line.strip():
                continue
            parts = line.split("|||FIELD|||")
            if len(parts) >= 3:
                items.append({
                    "id": parts[0].strip(),
                    "text": parts[1].strip(),
                    "completed": parts[2].strip().lower() == "true",
                    "source": "reminders",
                })
        return items
    except subprocess.TimeoutExpired:
        return []


def delete_reminder_by_id(reminder_id: str) -> bool:
    """Delete a reminder by its AppleScript id. Alias for delete_reminder.

    WHY an alias: the dedupe endpoint uses an explicit name that clarifies
    intent at the call site; the underlying implementation is identical.
    Returns True on success, False on failure or timeout.
    """
    return delete_reminder(reminder_id)
