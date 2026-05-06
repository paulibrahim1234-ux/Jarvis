"""
Reminders.app integration via AppleScript.

WHY a separate module: Reminders is a discrete macOS app with its own AppleScript
dictionary. Keeping the access layer isolated lets the briefing widget treat
"todos" as a simple list while we sync to/from the system app underneath.
"""

import subprocess
from typing import Optional

JARVIS_LIST = "Jarvis"  # Default list name. The first call creates it if missing.


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
    script = f'''
tell application "Reminders"
    set theList to list "{JARVIS_LIST}"
    set theReminders to reminders of theList whose completed is false
    set out to ""
    repeat with r in theReminders
        set rid to id of r as text
        set rname to name of r as text
        try
            set rdue to due date of r as text
        on error
            set rdue to ""
        end try
        set out to out & rid & "\\t" & rname & "\\t" & rdue & "\\n"
    end repeat
    return out
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=8,
        )
        if result.returncode != 0:
            return []
        items = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                items.append({
                    "id": parts[0],
                    "title": parts[1],
                    "due_hint": parts[2] if len(parts) > 2 else "",
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
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except subprocess.TimeoutExpired:
        return None


def complete_reminder(reminder_id: str) -> bool:
    """Mark a reminder as completed by its AppleScript id. Returns True on success.

    WHY search by id: Reminders.app ids are stable UUIDs unlike array indices.
    """
    safe_id = _as_str(reminder_id)
    script = f'''
tell application "Reminders"
    set r to first reminder whose id is "{safe_id}"
    set completed of r to true
    return "ok"
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return "ok" in result.stdout
    except subprocess.TimeoutExpired:
        return False


def delete_reminder(reminder_id: str) -> bool:
    """Delete a reminder by its AppleScript id. Returns True on success."""
    safe_id = _as_str(reminder_id)
    script = f'''
tell application "Reminders"
    set r to first reminder whose id is "{safe_id}"
    delete r
    return "ok"
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return "ok" in result.stdout
    except subprocess.TimeoutExpired:
        return False
