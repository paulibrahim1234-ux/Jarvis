"""
Desktop app tools — drive Mac apps directly via AppleScript.
No OAuth, no Azure, no API keys needed.
Apps just need to be open and logged in.

Covers: Microsoft Outlook, Spotify, Apple Calendar, Messages
"""

import json
import os
import sqlite3
import subprocess
import time
import urllib.parse


def _as_str(value: str) -> str:
    """Escape a Python string for safe inclusion inside an AppleScript "..." literal.

    Order matters: backslash MUST be escaped first, otherwise `\\"` would be
    re-escaped as `\\\\"` and an attacker-controlled trailing backslash could
    close the string literal early (the original injection vector).
    """
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


# ── Tool definitions ──────────────────────────────────────────────────────────

DESKTOP_TOOLS = [
    # ── Apple Mail ──
    {
        "name": "mail_get_inbox",
        "description": (
            "Get recent emails from Apple Mail (works for any account configured in Mail.app — "
            "school Outlook, Gmail, iCloud, etc. No OAuth or Azure needed)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max emails (default 15)", "default": 15},
            },
            "required": [],
        },
    },
    # ── Outlook ──
    {
        "name": "outlook_get_inbox",
        "description": (
            "Use this when the user asks 'check email', 'what's in my inbox', 'any new emails', "
            "'what did I get today', or when you need to browse recent messages without a specific "
            "keyword. Returns the most recent emails with subject, sender, date, and body preview. "
            "Reads directly from open Outlook Classic — no Azure/OAuth needed. "
            "Use limit to control how many emails to return (default 10, max ~50). "
            "For keyword/topic/sender searches, use outlook_search_inbox instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max emails to return (default 10)", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "outlook_get_calendar_events",
        "description": (
            "ONLY use this when the user explicitly asks for their OUTLOOK calendar "
            "(e.g. 'what's on my Outlook calendar', 'check Outlook events'). "
            "For general calendar questions like 'what's on my calendar today' or "
            "'what's my next event', use calendar_get_events instead — Apple Calendar "
            "is the user's primary view and includes their rotation feed plus any "
            "Outlook events that sync into it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days ahead to look (default 7)", "default": 7},
            },
            "required": [],
        },
    },
    {
        "name": "outlook_send_email",
        "description": "Compose and send an email via Microsoft Outlook desktop app.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (plain text)"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "outlook_search_inbox",
        "description": (
            "Use this when the user wants to find an email by topic, sender, keyword, or urgency — "
            "e.g. 'find the email about VSLO', 'any email from Dr. Smith', 'search for residency "
            "application', 'Lehigh Valley emails', 'anything urgent from school'. "
            "Returns lightweight metadata: id, subject, sender, date, body_preview. "
            "Use query to pre-filter by subject/sender substring (case-insensitive). "
            "Use natural_query for fuzzy/semantic ranking (e.g. 'email about interview scheduling'). "
            "After finding candidates, call outlook_read_email with message_id to get the full body. "
            "Use top_k to cap ranked results (default 8). "
            "Pass query='' with only natural_query to let semantic ranking do all the work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Literal substring to match in subject/sender/name (case-insensitive). "
                        "Pass an empty string to retrieve recent messages for Haiku to rank."
                    ),
                },
                "natural_query": {
                    "type": "string",
                    "description": (
                        "Free-form intent description sent to Claude Haiku for semantic ranking "
                        "(e.g. 'find email about residency interview scheduling'). "
                        "Optional — omit for plain keyword search."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Max ranked results to return when natural_query is set (default 8)",
                    "default": 8,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "outlook_read_email",
        "description": (
            "Use this AFTER outlook_search_inbox to read the full plain-text body of a specific "
            "Outlook Classic email. Required when you need the actual content — time, address, "
            "instructions, attachment info — not just the subject. Prefer message_id (from search "
            "results) for exact lookup; use subject_query as fallback when you only have a subject "
            "substring. Returns the complete email body text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Outlook integer ID of the message (from outlook_search_inbox or outlook_get_inbox)"},
                "subject_query": {"type": "string", "description": "Substring of the subject line; newest matching email is used"},
            },
            "required": [],
        },
    },
    {
        "name": "calendar_create_event",
        "description": (
            "Use this to add a new event to Apple Calendar AFTER confirming the details with the "
            "user. Requires title and start_iso (ISO 8601 format, e.g. '2026-04-27T07:30:00'). "
            "Default calendar is 'School' — specify calendar_name if user wants it elsewhere. "
            "Always confirm the event details (title, time, calendar) with the user before calling. "
            "Typically called after extracting a date/time from outlook_read_email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title (e.g. 'OIER Orientation')"},
                "start_iso": {"type": "string", "description": "ISO 8601 start time (e.g. '2026-04-27T07:30:00')"},
                "end_iso": {"type": "string", "description": "ISO 8601 end time. Defaults to start + 60 minutes."},
                "calendar_name": {"type": "string", "description": "Target calendar name (default: 'School')", "default": "School"},
                "location": {"type": "string", "description": "Optional location"},
                "notes": {"type": "string", "description": "Optional notes/description"},
            },
            "required": ["title", "start_iso"],
        },
    },
    # ── Spotify ──
    {
        "name": "spotify_get_track",
        "description": (
            "Use this when the user asks what's currently playing, 'what song is this', "
            "'who is this artist', 'is something playing', or anything about current Spotify state. "
            "Returns track name, artist, album, playback state (playing/paused), and current position. "
            "Call this before spotify_play_search or spotify_play_pause to check current state first."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_play_pause",
        "description": "Toggle Spotify play/pause.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_next_track",
        "description": "Skip to the next Spotify track.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_prev_track",
        "description": "Go back to the previous Spotify track.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_set_volume",
        "description": "Set Spotify volume (0–100).",
        "input_schema": {
            "type": "object",
            "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["volume"],
        },
    },
    {
        "name": "spotify_play_search",
        "description": (
            "Search for and play a song, artist, or playlist on Spotify. "
            "E.g. 'play Midnight City M83' or 'play lo-fi beats'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
    # ── Apple Calendar ──
    {
        "name": "calendar_get_events",
        "description": (
            "Use this when the user asks about their schedule, upcoming events, 'what's on my "
            "calendar', 'what's my next event', 'what time is [event]', 'do I have anything [day]', "
            "'any rotation this week', 'when does [shift] start', or 'tomorrow's first thing'. "
            "Returns ALL events from ALL Apple Calendar calendars — School, the one45 rotation feed, "
            "and synced Outlook events — with title, start/end time, calendar name, and location. "
            "More complete than the dashboard snapshot; always call this for specific calendar questions. "
            "Use days=1 for today-only, days=7 for week view (default 30). "
            "Prefer this over outlook_get_calendar_events for general schedule questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days ahead to look (default 30)", "default": 30},
            },
            "required": [],
        },
    },
    # ── Messages ──
    {
        "name": "messages_send",
        "description": (
            "Use this to send an iMessage or SMS ONLY AFTER the user has explicitly confirmed "
            "they want to send. NEVER call this without user confirmation — show the draft message "
            "to the user first, wait for approval, then call this. Required: to (phone number like "
            "+1... or contact name), message (the text to send)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Phone number (+1...) or contact name"},
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["to", "message"],
        },
    },
    {
        "name": "messages_get_recent",
        "description": (
            "Use this when the user asks 'did [name] text me back', 'what did [person] say', "
            "'check my texts with [contact]', 'read my messages from [name]', or 'did anyone text me'. "
            "Returns the most recent iMessages from that contact in chronological order, "
            "with sender, timestamp, and message text. "
            "Use contact to specify a phone number (+1...) or contact name (e.g. 'Rish', 'Mom'). "
            "Use limit to control how many messages to return (default 20)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Phone number or contact name"},
                "limit": {"type": "integer", "description": "Max messages (default 20)", "default": 20},
            },
            "required": ["contact"],
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────

def run_desktop_tool(name: str, inp: dict):
    if name == "mail_get_inbox":
        return _mail_inbox(inp.get("limit", 15))
    if name == "outlook_get_inbox":
        return _outlook_inbox(inp.get("limit", 10))
    if name == "outlook_get_calendar_events":
        return _outlook_calendar(inp.get("days", 30))
    if name == "outlook_send_email":
        return _outlook_send(inp["to"], inp["subject"], inp["body"])
    if name == "outlook_search_inbox":
        return _outlook_search_inbox(
            query=inp["query"],
            natural_query=inp.get("natural_query", ""),
            top_k=inp.get("top_k", 8),
        )
    if name == "outlook_read_email":
        return _outlook_read_email(
            message_id=inp.get("message_id", ""),
            subject_query=inp.get("subject_query", ""),
        )
    if name == "calendar_create_event":
        return _calendar_create_event(
            title=inp["title"],
            start_iso=inp["start_iso"],
            end_iso=inp.get("end_iso", ""),
            calendar_name=inp.get("calendar_name", "School"),
            location=inp.get("location", ""),
            notes=inp.get("notes", ""),
        )
    if name == "spotify_get_track":
        return _spotify_now_playing()
    if name == "spotify_play_pause":
        return _spotify_cmd("playpause")
    if name == "spotify_next_track":
        return _spotify_cmd("next track")
    if name == "spotify_prev_track":
        return _spotify_cmd("previous track")
    if name == "spotify_set_volume":
        return _spotify_volume(inp["volume"])
    if name == "spotify_play_search":
        return _spotify_search_play(inp["query"])
    if name == "calendar_get_events":
        return _calendar_events(inp.get("days", 30))
    if name == "messages_send":
        return _messages_send(inp["to"], inp["message"])
    if name == "messages_get_recent":
        return _messages_recent(inp["contact"], inp.get("limit", 20))
    raise ValueError(f"Unknown desktop tool: {name}")


# ── Outlook ───────────────────────────────────────────────────────────────────

_SCHOOL_DOMAIN_PATTERNS = (
    "rowan.edu",
    "cooperhealth.org",
    "cooper.edu",
    "camdenhealth.org",
    "sjhmc.org",
    "virtua.org",
    "inspirahealthnetwork.org",
    "kennedyhealth.org",
    ".edu",
)


def _tag_source(from_email: str, from_name: str, subject: str) -> str:
    """Classify an email into canvas / one45 / school / other."""
    e = (from_email or "").lower()
    n = (from_name or "").lower()
    s = (subject or "").lower()
    if "instructure.com" in e or "canvas" in n or "canvas" in s[:40]:
        return "canvas"
    if "one45.com" in e or "one45" in n or "one45" in e:
        return "one45"
    for pat in _SCHOOL_DOMAIN_PATTERNS:
        if pat in e:
            return "school"
    return "other"


def _fetch_outlook_account_inbox(
    account_type: str,
    account_index: int,
    limit: int,
    folder_name: str = "",
) -> dict:
    """Grab up to `limit` messages from one Outlook account's inbox or a named
    subfolder (e.g. "Rowan class of 2027", "Financial Aid").

    Returns {"account", "account_email", "emails": [...]} or {"error": "..."}.
    Uses per-field `try` blocks because some messages have unresolved senders
    that crash AppleScript when you ask for display name / address.
    """
    # AppleScript block that resolves the target folder. Empty folder_name
    # means "default inbox"; any other name does a case-insensitive match
    # against top-level mail folders of the account.
    if folder_name:
        # Escape user-supplied folder name for safe inclusion in an
        # AppleScript "..." literal (backslash, quote, newline, CR).
        safe = _as_str(folder_name)
        resolve_target = (
            f'set targetFolderName to "{safe}"\n'
            '    set targetInbox to missing value\n'
            '    try\n'
            '        set targetInbox to (first mail folder of acct whose name is targetFolderName)\n'
            '    end try\n'
            '    if targetInbox is missing value then\n'
            '        repeat with f in (mail folders of acct)\n'
            '            if (name of f as string) is targetFolderName then\n'
            '                set targetInbox to f\n'
            '                exit repeat\n'
            '            end if\n'
            '        end repeat\n'
            '    end if\n'
            '    if targetInbox is missing value then set targetInbox to inbox of acct'
        )
    else:
        resolve_target = "set targetInbox to inbox of acct"

    script = f"""
tell application "Microsoft Outlook"
    set acct to item {account_index} of (every {account_type} account)
    set acctName to name of acct
    try
        set acctEmail to email address of acct
    on error
        set acctEmail to ""
    end try
    {resolve_target}
    set msgs to messages of targetInbox
    set msgCount to count of msgs
    if msgCount > {limit} then set msgCount to {limit}
    set out to acctName & "<<<ACCT>>>" & acctEmail & "<<<ACCT>>>"
    repeat with i from 1 to msgCount
        set m to item i of msgs
        set subj to ""
        set sName to ""
        set sEmail to ""
        set rcvd to ""
        set isRead to true
        set entryId to ""
        try
            set subj to subject of m
        end try
        try
            set sndr to sender of m
            try
                set sName to name of sndr
            end try
            try
                set sEmail to address of sndr
            end try
        end try
        try
            set rcvd to time received of m as string
        end try
        try
            set isRead to is read of m
        end try
        try
            set entryId to id of m as string
        end try
        set out to out & subj & "|||" & sName & "|||" & sEmail & "|||" & rcvd & "|||" & (isRead as string) & "|||" & entryId & "###ROW###"
    end repeat
    return out
end tell
"""
    result = _osascript(script, timeout=25)
    if "error" in result:
        return {"error": result["error"]}
    raw = result.get("output", "")
    if "<<<ACCT>>>" not in raw:
        return {"error": f"unexpected output from {account_type} account {account_index}"}
    acct_name, acct_email, body = raw.split("<<<ACCT>>>", 2)
    emails = []
    for line in body.split("###ROW###"):
        line = line.strip().lstrip(",").strip()
        if not line:
            continue
        parts = line.split("|||")
        if len(parts) < 4:
            continue
        subj = parts[0].strip()
        from_name = parts[1].strip()
        from_email = parts[2].strip()
        received = parts[3].strip()
        read = parts[4].strip() == "true" if len(parts) > 4 else True
        entry_id = parts[5].strip() if len(parts) > 5 else ""
        emails.append({
            "subject": subj or "(no subject)",
            "from_name": from_name or from_email or "Unknown",
            "from_email": from_email,
            "received": received,
            "read": read,
            "account": acct_name.strip(),
            "source": _tag_source(from_email, from_name, subj),
            "entry_id": entry_id or "",
            "folder": folder_name or "Inbox",
        })
    return {"account": acct_name.strip(), "account_email": acct_email.strip(), "emails": emails}


def _outlook_folders() -> dict:
    """Enumerate top-level mail folders per Outlook account with approx
    unread counts. Heavily cached upstream (folders shift slowly).

    Returns:
        {
          "accounts": [
            {
              "account": "Rowan",
              "account_email": "user@rowan.edu",
              "folders": [
                {"name": "Inbox",               "unread": 12},
                {"name": "Rowan class of 2027", "unread": 3},
                ...
              ]
            },
            ...
          ]
        }

    Unread count uses Outlook's built-in `unread count` property when
    available; falls back to 0 on per-folder errors (some protocols/
    folders don't expose it). Skips nested subfolders to keep the script
    under the AppleScript timeout budget.
    """
    script = r"""
tell application "Microsoft Outlook"
    set out to ""
    set acctLists to {}
    try
        set acctLists to acctLists & every exchange account
    end try
    try
        set acctLists to acctLists & every imap account
    end try
    try
        set acctLists to acctLists & every pop account
    end try
    repeat with acct in acctLists
        set acctName to name of acct
        set acctEmail to ""
        try
            set acctEmail to email address of acct
        end try
        set out to out & acctName & "<<<ACCT>>>" & acctEmail & "<<<ACCT>>>"
        -- Always include the default Inbox first (even if not in mail folders).
        set inboxUnread to 0
        try
            set inboxUnread to unread count of (inbox of acct)
        end try
        set out to out & "Inbox" & "|||" & (inboxUnread as string) & "###FOLDER###"
        try
            repeat with f in (mail folders of acct)
                set fName to ""
                set fUnread to 0
                try
                    set fName to name of f as string
                end try
                if fName is not "" and fName is not "Inbox" then
                    try
                        set fUnread to unread count of f
                    end try
                    set out to out & fName & "|||" & (fUnread as string) & "###FOLDER###"
                end if
            end repeat
        end try
        set out to out & "###ACCT###"
    end repeat
    return out
end tell
"""
    result = _osascript(script, timeout=20)
    if "error" in result:
        return {"accounts": [], "error": result["error"]}
    raw = result.get("output", "")
    accounts: list[dict] = []
    for acct_block in raw.split("###ACCT###"):
        acct_block = acct_block.strip().lstrip(",").strip()
        if not acct_block or "<<<ACCT>>>" not in acct_block:
            continue
        acct_name, acct_email, folders_raw = acct_block.split("<<<ACCT>>>", 2)
        folders: list[dict] = []
        for line in folders_raw.split("###FOLDER###"):
            line = line.strip().lstrip(",").strip()
            if not line or "|||" not in line:
                continue
            name, unread_s = line.split("|||", 1)
            name = name.strip()
            try:
                unread = int(unread_s.strip())
            except ValueError:
                unread = 0
            if name:
                folders.append({"name": name, "unread": unread})
        accounts.append(
            {
                "account": acct_name.strip(),
                "account_email": acct_email.strip(),
                "folders": folders,
            }
        )
    return {"accounts": accounts}


class OutlookNotRunningError(RuntimeError):
    """Raised when Outlook Classic cannot be launched within the timeout."""


class NewOutlookModeError(RuntimeError):
    """Raised when New Outlook mode is detected (incompatible with Classic AppleScript API)."""


# Perf#3: confirmation cache — epoch time until which Outlook is known to be
# running and in Classic mode.  Avoids 2 blocking subprocess.run calls
# (200–400 ms total) on every Outlook tool entry when the app is already up.
_OUTLOOK_CONFIRMED_UNTIL: float = 0.0


def _outlook_invalidate_cache() -> None:
    """Reset the Outlook running-confirmation cache to force a re-probe.

    Call this from any AppleScript error path that indicates Outlook stopped
    or became unresponsive (subprocess.CalledProcessError, osascript stderr
    containing "not running", "connection is invalid", etc.) so the next
    tool call re-probes rather than trusting a stale cached confirmation.
    """
    global _OUTLOOK_CONFIRMED_UNTIL
    _OUTLOOK_CONFIRMED_UNTIL = 0.0


def _ensure_outlook_running() -> None:
    """Guarantee Microsoft Outlook Classic is running before any AppleScript call.

    WHY this exists rather than relying on the "not running" error path: AppleScript
    errors from a not-running app are opaque ("connection is invalid") and surface
    long after the timeout. Proactive check + launch cuts the latency and returns a
    user-legible message instead of a cryptic osascript stderr dump.

    Steps:
      1. Perf#3 fast path — return immediately if confirmed within last 30 s.
      2. Query System Events for the process name (non-activating check).
      3. If absent, launch via `open -a "Microsoft Outlook"` (standard macOS app open).
      4. Poll every 0.5 s up to 15 s for the process to appear.
      5. Once running, probe for New Outlook mode via exchange-accounts count:
         New Outlook swapped that property, so a specific AppleScript error signature
         indicates the user is in New Outlook and the Classic API won't work.
      6. On success, stamp _OUTLOOK_CONFIRMED_UNTIL for 30 s.
    """
    global _OUTLOOK_CONFIRMED_UNTIL
    # Perf#3 fast path: skip the two blocking subprocess calls if we confirmed
    # Outlook was running and in Classic mode within the last 30 seconds.
    # 30 s is long enough to span a typical multi-tool sequence but short enough
    # that a quit-and-relaunch is caught on the next widget refresh cycle.
    if time.time() < _OUTLOOK_CONFIRMED_UNTIL:
        return

    def _is_running() -> bool:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to (name of processes) contains "Microsoft Outlook"'],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip().lower() == "true"

    try:
        already_up = _is_running()
    except Exception:
        already_up = False  # if System Events fails, optimistically proceed

    if not already_up:
        subprocess.run(["open", "-a", "Microsoft Outlook"], check=False, timeout=5)
        # Poll up to 15 s (30 × 0.5 s) for the process to appear in the process list.
        # The 0.5 s interval is intentional: short enough that a fast machine doesn't
        # wait unnecessarily, long enough to avoid hammering System Events.
        deadline = time.time() + 15
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                if _is_running():
                    break
            except Exception:
                pass
        else:
            raise OutlookNotRunningError(
                "Microsoft Outlook did not start within 15 seconds. "
                "Please open it manually and try again."
            )

    # New Outlook detection: Classic API exposes `exchange accounts`; New Outlook
    # silently redirected that property and the script errors with a distinctive
    # message that doesn't appear with Classic mode.
    probe = subprocess.run(
        ["osascript", "-e",
         'tell application "Microsoft Outlook" to return count of exchange accounts'],
        capture_output=True, text=True, timeout=8,
    )
    stderr = probe.stderr.strip().lower()
    # New Outlook returns "Outlook got an error: Can't get exchange accounts." or
    # a variant containing "can't get" — Classic returns a plain integer.
    if "can't get" in stderr or "cannot get" in stderr:
        raise NewOutlookModeError(
            "New Outlook is active but the Classic AppleScript API is required. "
            "Toggle off 'New Outlook' in Outlook → Help menu, then retry."
        )

    # Perf#3: stamp the cache — Outlook confirmed running in Classic mode.
    _OUTLOOK_CONFIRMED_UNTIL = time.time() + 30


def _count_outlook_accounts() -> dict:
    """Return count of exchange / imap / pop accounts."""
    script = """
tell application "Microsoft Outlook"
    set ex to 0
    set im to 0
    set po to 0
    try
        set ex to count of (every exchange account)
    end try
    try
        set im to count of (every imap account)
    end try
    try
        set po to count of (every pop account)
    end try
    return (ex as string) & "|" & (im as string) & "|" & (po as string)
end tell
"""
    result = _osascript(script, timeout=10)
    if "error" in result:
        return {"exchange": 0, "imap": 0, "pop": 0, "error": result["error"]}
    parts = result.get("output", "0|0|0").split("|")
    try:
        return {
            "exchange": int(parts[0]),
            "imap": int(parts[1]) if len(parts) > 1 else 0,
            "pop": int(parts[2]) if len(parts) > 2 else 0,
        }
    except ValueError:
        return {"exchange": 0, "imap": 0, "pop": 0}


def _parse_outlook_time(ts: str):
    """Parse Outlook's 'time received' string (e.g. 'Tuesday, April 14, 2026 at 9:18:17 AM')."""
    from datetime import datetime
    import re
    if not ts:
        return datetime.min
    cleaned = re.sub(r"^\w+,\s*", "", ts).replace(" at ", " ").strip()
    for fmt in ("%B %d, %Y %I:%M:%S %p", "%B %d, %Y %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return datetime.min


def _outlook_inbox(
    limit: int = 15,
    folder: str = "",
    account: str = "",
) -> dict:
    """Pull emails from every Outlook account (or one), optionally from a named
    subfolder, merge, source-tag, sort newest first.

    Args:
        limit: max emails to return.
        folder: optional folder name (e.g. "Rowan class of 2027"). Empty = Inbox.
        account: optional account name OR email to restrict to a single account.
    """
    # Ensure Outlook Classic is running — surfaces a user-legible error rather
    # than a cryptic AppleScript "connection is invalid" failure mid-script.
    try:
        _ensure_outlook_running()
    except (OutlookNotRunningError, NewOutlookModeError) as exc:
        _outlook_invalidate_cache()  # Perf#3: app stopped — force re-probe next call
        return {"error": str(exc), "emails": []}

    import concurrent.futures

    counts = _count_outlook_accounts()
    total_accounts = sum(counts.get(k, 0) for k in ("exchange", "imap", "pop"))
    if total_accounts == 0:
        err = counts.get("error") or "No Outlook accounts found. Is Outlook open and Classic mode enabled?"
        return {"error": err, "emails": []}

    per_account = max(limit, 10)  # over-fetch so merge picks the freshest
    acct_filter = (account or "").strip().lower()

    # Build list of (acct_type, idx) jobs.
    jobs: list[tuple[str, int]] = []
    for acct_type in ("exchange", "imap", "pop"):
        n = counts.get(acct_type, 0)
        for idx in range(1, n + 1):
            jobs.append((acct_type, idx))

    def _fetch_job(job: tuple[str, int]):
        acct_type, idx = job
        try:
            return _fetch_outlook_account_inbox(acct_type, idx, per_account, folder_name=folder)
        except Exception:
            return {"error": "exception", "emails": []}

    all_emails: list[dict] = []
    accounts_seen: list[dict] = []

    max_workers = min(len(jobs) or 1, 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_job = {pool.submit(_fetch_job, job): job for job in jobs}
        for fut in concurrent.futures.as_completed(future_to_job):
            try:
                result = fut.result()
            except Exception:
                continue
            if result.get("error"):
                continue
            # Filter by account name/email if requested.
            if acct_filter:
                name_l = (result.get("account", "") or "").lower()
                email_l = (result.get("account_email", "") or "").lower()
                if acct_filter not in name_l and acct_filter not in email_l:
                    continue
            acct_type, _ = future_to_job[fut]
            accounts_seen.append({
                "type": acct_type,
                "name": result.get("account", ""),
                "email": result.get("account_email", ""),
                "count": len(result.get("emails", [])),
            })
            all_emails.extend(result.get("emails", []))

    all_emails.sort(key=lambda e: _parse_outlook_time(e.get("received", "")), reverse=True)
    all_emails = all_emails[:limit]

    return {
        "emails": all_emails,
        "count": len(all_emails),
        "accounts": accounts_seen,
        "folder": folder or "Inbox",
    }


def _outlook_calendar(days: int = 30) -> dict:
    # Ensure Outlook Classic is running before fetching calendar events.
    try:
        _ensure_outlook_running()
    except (OutlookNotRunningError, NewOutlookModeError) as exc:
        _outlook_invalidate_cache()  # Perf#3: app stopped — force re-probe next call
        return {"error": str(exc), "events": []}
    script = f"""
tell application "Microsoft Outlook"
    set startDate to current date
    set endDate to startDate + ({days} * days)
    set evtList to {{}}
    try
        set dayEvts to calendar events from startDate to endDate
        repeat with evt in dayEvts
            try
                set evtSubj to subject of evt
                set evtStart to start time of evt as string
                set evtEnd to end time of evt as string
                set evtLoc to location of evt
                set evtId to ""
                try
                    set evtId to id of evt as string
                end try
                set end of evtList to (evtSubj & "|||" & evtStart & "|||" & evtEnd & "|||" & evtLoc & "|||" & evtId & "###ROW###")
            end try
        end repeat
    end try
    return evtList
end tell
"""
    result = _osascript(script, timeout=30)
    if "error" in result:
        return result
    events = []
    # Same U+202F / U+00A0 normalization as Apple Calendar — AppleScript time
    # strings ("9:00\u202fAM") break JS Date.parse otherwise.
    raw = result.get("output", "")
    raw = raw.replace("\u202f", " ").replace("\u00a0", " ")
    for line in raw.split("###ROW###"):
        line = line.strip().lstrip(",").strip()
        parts = line.split("|||")
        if len(parts) >= 2 and parts[0].strip():
            # Normalize start/end to ISO 8601 — matches what _calendar_events
            # produces. Without this, downstream consumers that filter by
            # `start.startswith("YYYY-MM-DD")` (e.g. the morning briefing)
            # silently drop every Outlook event because the raw AppleScript
            # string is "Tuesday, April 29, 2026 at 7:30:00 AM".
            events.append({
                "title": parts[0].strip(),
                "start": _applescript_dt_to_iso(parts[1].strip()),
                "end": _applescript_dt_to_iso(parts[2].strip()) if len(parts) > 2 else "",
                "location": parts[3].strip() if len(parts) > 3 else "",
                "calendar": "Outlook",
                "event_id": parts[4].strip() if len(parts) > 4 else None,
            })
    return {"events": events, "count": len(events)}


def _outlook_send(to: str, subject: str, body: str) -> dict:
    # Ensure Outlook Classic is running before attempting to compose a message.
    try:
        _ensure_outlook_running()
    except (OutlookNotRunningError, NewOutlookModeError) as exc:
        _outlook_invalidate_cache()  # Perf#3: app stopped — force re-probe next call
        return {"error": str(exc)}
    # Escape for AppleScript (handles backslash, quote, newline, CR).
    to_s = _as_str(to)
    subj_s = _as_str(subject)
    body_s = _as_str(body)
    script = f"""
tell application "Microsoft Outlook"
    set newMsg to make new outgoing message with properties {{subject:"{subj_s}", plain text content:"{body_s}"}}
    make new recipient at newMsg with properties {{email address:{{address:"{to_s}"}}}}
    send newMsg
    return "sent"
end tell
"""
    # 30 s timeout: SMTP/Exchange handoff after sleep or a network change can
    # push past the default 15 s — mid-send kill leaves message state undefined.
    # 30 s matches the other long-poll bands in this file (search uses 45 s).
    result = _osascript(script, timeout=30)
    if "error" in result:
        return result
    return {"status": "sent", "to": to, "subject": subject}


def _outlook_search_inbox(
    query: str,
    natural_query: str = "",
    top_k: int = 8,
) -> dict:
    """Search Outlook Classic inbox, optionally re-ranked by Claude Haiku.

    Args:
        query:         Literal substring for AppleScript pre-filter (case-insensitive).
                       Pass "" to pull recent messages without keyword filtering.
        natural_query: Free-form intent for Haiku semantic ranking.
                       When omitted, results are returned in chronological order.
        top_k:         Max ranked results returned when natural_query is set.

    Flow:
        1. Ensure Outlook Classic is running (structured error if not).
        2. AppleScript pulls up to 200 candidates (offset 0).
           - Each candidate: id, subject, sender_email, sender_name,
             received_iso, body_preview (≤280 chars from the `content` property).
        3. If zero candidates and a query was given, try offset 200, then 400
           (hard cap 600 total) before giving up — avoids empty results when the
           matching email is further down the inbox.
        4. If natural_query is set, call Haiku to score + rank candidates,
           then return top_k. Falls back to chronological order on any API error.
    """
    # ── Guard: Outlook must be running ─────────────────────────────────────────
    # Catch all exceptions from _ensure_outlook_running — not just the two custom
    # types. The probe subprocess at the end of that helper can raise
    # subprocess.TimeoutExpired if Outlook is opening but hasn't become responsive
    # yet, and that must also surface as a structured error rather than a crash.
    try:
        _ensure_outlook_running()
    except Exception as exc:
        _outlook_invalidate_cache()  # Perf#3: any error means app state unknown — re-probe next call
        return {"error": "outlook_not_running", "message": str(exc), "candidates": []}

    # ── AppleScript fetch ───────────────────────────────────────────────────────
    q = (query or "").strip().lower()
    # An empty keyword is valid when natural_query will do the ranking — skip
    # the AppleScript contains-check so all recent messages are candidates.
    use_filter = bool(q)
    q_s = _as_str(q)

    # AppleScript truncates body_preview at 280 chars to keep the osascript
    # return value small; full body is available via _outlook_read_email.
    BATCH = 200
    HARD_CAP = 600  # 3 batches maximum to bound cost/time

    def _fetch_batch(offset: int) -> list[dict]:
        """Pull one batch of up to BATCH messages starting at `offset`."""
        filter_block = f'if bag contains q then' if use_filter else 'if true then'
        script = f"""
tell application "Microsoft Outlook"
    set q to "{q_s}"
    set out to ""
    set hits to 0
    set skipped to 0
    -- Union all account types so Gmail/iCloud IMAP accounts are visible.
    -- _outlook_inbox already does this; search was inconsistently exchange-only,
    -- which made IMAP/POP inboxes invisible to keyword search (Hunter found this).
    set allAccts to {{}}
    try
        set allAccts to allAccts & (every exchange account)
    end try
    try
        set allAccts to allAccts & (every imap account)
    end try
    try
        set allAccts to allAccts & (every pop account)
    end try
    repeat with acct in allAccts
        try
            set inb to inbox of acct
            set msgs to messages of inb
            repeat with m in msgs
                -- offset support: skip the first {offset} messages globally
                if skipped < {offset} then
                    set skipped to skipped + 1
                else if hits < {BATCH} then
                    try
                        set subj to subject of m as string
                    on error
                        set subj to ""
                    end try
                    try
                        set fromAddr to address of (sender of m) as string
                    on error
                        set fromAddr to ""
                    end try
                    try
                        set fromName to name of (sender of m) as string
                    on error
                        set fromName to ""
                    end try
                    set bag to (subj & " " & fromAddr & " " & fromName) as string
                    {filter_block}
                        set hits to hits + 1
                        try
                            set mid to id of m as string
                        on error
                            set mid to ""
                        end try
                        try
                            -- time received as ISO-like string; Outlook returns localised date string
                            set ts to time received of m as string
                        on error
                            set ts to ""
                        end try
                        try
                            -- `content` is the plain-text body in Classic Outlook AppleScript
                            set rawBody to content of m as string
                            if (length of rawBody) > 280 then
                                set preview to text 1 thru 280 of rawBody
                            else
                                set preview to rawBody
                            end if
                        on error
                            set preview to ""
                        end try
                        -- Delimiter chosen to be unlikely in email content
                        set out to out & mid & "|||" & subj & "|||" & fromName & "|||" & fromAddr & "|||" & ts & "|||" & preview & "###ROW###"
                    end if
                end if
            end repeat
        end try
    end repeat
    return out
end tell
"""
        # 45 s timeout per batch; raise TimeoutExpired so callers can catch it.
        result = _osascript(script, timeout=45)
        if "error" in result:
            # Propagate structured timeout error; other errors bubble as dict.
            return result  # type: ignore[return-value]
        rows: list[dict] = []
        for line in result.get("output", "").split("###ROW###"):
            line = line.strip().lstrip(",").strip()
            parts = line.split("|||")
            if len(parts) >= 5 and parts[0]:
                rows.append({
                    "id": parts[0],
                    "subject": parts[1].strip(),
                    "sender_name": parts[2].strip(),
                    "sender_email": parts[3].strip(),
                    "received_iso": parts[4].strip(),
                    "body_preview": parts[5].strip() if len(parts) >= 6 else "",
                })
        return rows

    # ── Batch loop with pagination ──────────────────────────────────────────────
    candidates: list[dict] = []
    for offset in range(0, HARD_CAP, BATCH):
        batch = _fetch_batch(offset)

        # AppleScript-level error (timeout or other) — surface immediately.
        if isinstance(batch, dict) and "error" in batch:
            # Structured timeout so callers can retry with a narrower query.
            if batch.get("error") == "AppleScript timed out — app may be busy or not responding.":
                return {
                    "error": "applescript_timeout",
                    "message": "AppleScript timed out after 45s; try a more specific query.",
                    "candidates": [],
                }
            return batch  # other AppleScript errors

        candidates.extend(batch)  # type: ignore[arg-type]

        # Stop paginating once we have candidates OR the batch was empty
        # (no more messages in inbox) OR we're not using a keyword filter
        # (all messages are candidates; no point fetching more without ranking).
        if candidates or not isinstance(batch, list) or len(batch) < BATCH:
            break
        if not use_filter:
            # Without a keyword filter every message is a candidate; one batch
            # of 200 is enough — Haiku will pick the best ones.
            break

    # ── LLM-guided ranking ──────────────────────────────────────────────────────
    if natural_query and candidates:
        candidates = _rank_with_haiku(candidates, natural_query, top_k)

    return {
        "candidates": candidates[: top_k if natural_query else len(candidates)],
        "count": len(candidates[: top_k if natural_query else len(candidates)]),
        "query": query,
        "natural_query": natural_query or None,
    }


def _rank_with_haiku(
    candidates: list[dict],
    natural_query: str,
    top_k: int,
) -> list[dict]:
    """Ask Claude Haiku to score each candidate and return top_k sorted by score.

    WHY Haiku specifically: it is the cheapest Anthropic model and this is a
    high-frequency ranking call — we want latency < 2 s and cost < $0.001/call.
    Haiku is sufficient for subject+sender matching; Sonnet would be overkill.

    Falls back to chronological order (no re-sort) if the API call fails for
    any reason, so the user still gets *something* useful rather than an error.
    """
    import json as _json  # local import to keep module-level imports clean

    # Build the candidate list for the prompt.
    # Only include body_preview when there are ≤30 candidates — otherwise the
    # prompt grows large enough to matter for cost and latency.
    include_body = len(candidates) <= 30
    lines: list[str] = []
    for c in candidates:
        entry = f"id={c['id']} | subject={c['subject']} | from={c['sender_name']} <{c['sender_email']}> | date={c['received_iso']}"
        if include_body and c.get("body_preview"):
            entry += f" | preview={c['body_preview'][:200]}"
        lines.append(entry)
    candidate_block = "\n".join(lines)

    prompt = (
        f"You are ranking email candidates for relevance to a user's search intent.\n\n"
        f"Search intent: {natural_query}\n\n"
        f"Candidates:\n{candidate_block}\n\n"
        f"Return ONLY valid JSON — no markdown, no explanation — in this exact shape:\n"
        f'{{\"ranked\": [{{\"id\": \"<msgid>\", \"score\": 0-100, \"reason\": \"<short>\"}}]}}\n'
        f"Include the top {top_k} most relevant candidates only, sorted by score descending.\n"
        f"If none are relevant, return {{\"ranked\": []}}."
    )

    # Reuse the same client-building pattern as jarvis.py — read from env so
    # that OAuth tokens and API keys both work transparently.
    import anthropic as _anthropic

    raw = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if raw.startswith("sk-ant-oat"):
        haiku_client = _anthropic.Anthropic(
            auth_token=raw,
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
        )
    else:
        haiku_client = _anthropic.Anthropic(api_key=raw)

    try:
        response = haiku_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()
        # Strip markdown fences if the model wraps in them despite instructions.
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        ranking_data = _json.loads(raw_text)
        ranked_items: list[dict] = ranking_data.get("ranked", [])
    except Exception:
        # Any failure (network, key, rate-limit, JSON parse) → fall back.
        # Inject a reason so the caller knows ranking was skipped.
        for c in candidates:
            c["score_reason"] = "(LLM ranking unavailable, showing chronological)"
        return candidates[:top_k]

    # Merge score + reason from Haiku back into the candidate dicts by id.
    score_map = {str(r["id"]): r for r in ranked_items}
    result: list[dict] = []
    for c in candidates:
        if str(c["id"]) in score_map:
            ranked_entry = score_map[str(c["id"])]
            c["score"] = ranked_entry.get("score", 0)
            c["score_reason"] = ranked_entry.get("reason", "")
            result.append(c)

    result.sort(key=lambda x: x.get("score", 0), reverse=True)
    return result[:top_k]


def _outlook_read_email(message_id: str = "", subject_query: str = "") -> dict:
    """Read the full plain-text body of one Outlook Classic message.

    Provide either `message_id` (preferred — exact) or `subject_query` (newest match).
    Returns: {subject, sender_name, sender_email, received_at, body, html, id}
    """
    # Ensure Outlook Classic is running before reading the email body.
    try:
        _ensure_outlook_running()
    except (OutlookNotRunningError, NewOutlookModeError) as exc:
        _outlook_invalidate_cache()  # Perf#3: app stopped — force re-probe next call
        return {"error": str(exc)}
    if not message_id and not subject_query:
        return {"error": "Provide message_id or subject_query"}
    # message_id is gated on isdigit() below — drop quotes; isdigit() will
    # reject any other character anyway. subject_query goes into a literal
    # so use the full _as_str escape.
    safe_id = (message_id or "").replace('"', '').strip()
    safe_q = _as_str((subject_query or "").strip())
    if safe_id and safe_id.isdigit():
        finder = f"set m to first message of inbox of acct whose id is {safe_id}"
    elif safe_q:
        finder = (
            f'set hits to (messages of inbox of acct whose subject contains "{safe_q}")\n'
            "        if (count of hits) is 0 then error \"no match\"\n"
            "        set m to first item of hits"
        )
    else:
        finder = "error \"need id or query\""
    script = f"""
tell application "Microsoft Outlook"
    set found to false
    set body_t to ""
    set html_t to ""
    set subj_t to ""
    set sn_t to ""
    set sa_t to ""
    set ts_t to ""
    set id_t to ""
    -- Union all account types so Gmail/iCloud IMAP accounts are visible.
    -- _outlook_inbox already does this; read was inconsistently exchange-only,
    -- which made IMAP/POP messages invisible to the read tool (Hunter found this).
    set allAccts to {{}}
    try
        set allAccts to allAccts & (every exchange account)
    end try
    try
        set allAccts to allAccts & (every imap account)
    end try
    try
        set allAccts to allAccts & (every pop account)
    end try
    repeat with acct in allAccts
        try
            {finder}
            try
                set body_t to plain text content of m
            end try
            try
                set html_t to content of m
            end try
            try
                set subj_t to subject of m as string
            end try
            try
                set sn_t to name of (sender of m) as string
            end try
            try
                set sa_t to address of (sender of m) as string
            end try
            try
                set ts_t to time received of m as string
            end try
            try
                set id_t to id of m as string
            end try
            set found to true
            exit repeat
        end try
    end repeat
    if not found then return "NOTFOUND"
    return id_t & "|||" & subj_t & "|||" & sn_t & "|||" & sa_t & "|||" & ts_t & "|||BODY|||" & body_t & "|||HTML|||" & html_t
end tell
"""
    result = _osascript(script, timeout=20)
    if "error" in result:
        return result
    out = result.get("output", "")
    if out.strip() == "NOTFOUND":
        return {"error": "no match"}
    head, _, rest = out.partition("|||BODY|||")
    body, _, html = rest.partition("|||HTML|||")
    parts = head.split("|||")
    return {
        "id": parts[0].strip() if len(parts) > 0 else "",
        "subject": parts[1].strip() if len(parts) > 1 else "",
        "sender_name": parts[2].strip() if len(parts) > 2 else "",
        "sender_email": parts[3].strip() if len(parts) > 3 else "",
        "received_at": parts[4].strip() if len(parts) > 4 else "",
        "body": body.strip(),
        "html": html.strip(),
    }


def _calendar_create_event(
    title: str,
    start_iso: str,
    end_iso: str = "",
    calendar_name: str = "School",
    location: str = "",
    notes: str = "",
) -> dict:
    """Create an event in Apple Calendar.

    `start_iso` / `end_iso` are ISO 8601 ('2026-04-27T07:30:00'). If end omitted,
    defaults to start + 60 minutes. `calendar_name` must match a calendar that
    exists in Calendar.app.
    """
    import datetime as _dt
    if not title or not start_iso:
        return {"error": "title and start_iso required"}
    try:
        sdt = _dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        if sdt.tzinfo:
            sdt = sdt.astimezone().replace(tzinfo=None)
    except ValueError as e:
        return {"error": f"bad start_iso: {e}"}
    if end_iso:
        try:
            edt = _dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            if edt.tzinfo:
                edt = edt.astimezone().replace(tzinfo=None)
        except ValueError as e:
            return {"error": f"bad end_iso: {e}"}
    else:
        edt = sdt + _dt.timedelta(minutes=60)
    title_s = _as_str(title)
    cal_s = _as_str(calendar_name)
    loc_s = _as_str(location or "")
    notes_s = _as_str(notes or "")
    # AppleScript constructs date by component to avoid locale ambiguity.
    s = (sdt.year, sdt.month, sdt.day, sdt.hour, sdt.minute)
    e = (edt.year, edt.month, edt.day, edt.hour, edt.minute)
    script = f"""
tell application "Calendar"
    set startD to current date
    set year of startD to {s[0]}
    set month of startD to {s[1]}
    set day of startD to {s[2]}
    set hours of startD to {s[3]}
    set minutes of startD to {s[4]}
    set seconds of startD to 0
    set endD to current date
    set year of endD to {e[0]}
    set month of endD to {e[1]}
    set day of endD to {e[2]}
    set hours of endD to {e[3]}
    set minutes of endD to {e[4]}
    set seconds of endD to 0
    tell calendar "{cal_s}"
        set newEv to make new event with properties {{summary:"{title_s}", start date:startD, end date:endD, location:"{loc_s}", description:"{notes_s}"}}
        return uid of newEv as string
    end tell
end tell
"""
    result = _osascript(script, timeout=15)
    if "error" in result:
        return result
    return {
        "status": "created",
        "event_id": result.get("output", "").strip(),
        "title": title,
        "calendar": calendar_name,
        "start": sdt.isoformat(timespec="minutes"),
        "end": edt.isoformat(timespec="minutes"),
    }


# ── Spotify ───────────────────────────────────────────────────────────────────

def _spotify_now_playing() -> dict:
    script = """
tell application "Spotify"
    try
        set trackState to player state as string
        if player state is playing or player state is paused then
            set trackName to name of current track
            set artistName to artist of current track
            set albumName to album of current track
            set trackDur to duration of current track
            set trackPos to player position
            set trackUri to spotify url of current track
            set vol to sound volume
            try
                set art to artwork url of current track
            on error
                set art to ""
            end try
            return trackName & "|||" & artistName & "|||" & albumName & "|||" & (trackDur as string) & "|||" & (trackPos as string) & "|||" & trackState & "|||" & trackUri & "|||" & (vol as string) & "|||" & art
        else
            return "|||||||stopped||||||"
        end if
    on error e
        return "error|||" & e
    end try
end tell
"""
    result = _osascript(script)
    out = result.get("output", "")
    if "error" in result and not out:
        return result
    parts = out.split("|||")
    if len(parts) < 6:
        return {"state": "stopped", "track": None}
    try:
        duration_ms = int(parts[3]) if parts[3].isdigit() else 0
        position_s = float(parts[4]) if parts[4] else 0
    except (ValueError, IndexError):
        duration_ms = 0
        position_s = 0
    return {
        "track": parts[0] or None,
        "artist": parts[1] or None,
        "album": parts[2] or None,
        "duration_ms": duration_ms,
        "position_s": position_s,
        "state": parts[5] if len(parts) > 5 else "unknown",
        "uri": parts[6] if len(parts) > 6 else None,
        "volume": int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else None,
        "artwork_url": parts[8] if len(parts) > 8 and parts[8] else None,
    }


def _spotify_play_uri(uri: str) -> dict:
    """Play a Spotify URI (spotify:track:..., spotify:playlist:..., spotify:album:...)."""
    raw = (uri or "").strip()
    if not raw:
        return {"error": "Empty URI"}
    # Spotify URIs are alphanumeric-only after the colons. Reject anything
    # else outright so an attacker can't smuggle quotes/backslashes/newlines
    # into the AppleScript literal even if _as_str escapes them.
    import re as _re
    if not _re.match(r"^(spotify:[a-zA-Z]+:[A-Za-z0-9]+|https?://[A-Za-z0-9./_:?=&-]+)$", raw):
        return {"error": "Invalid Spotify URI"}
    safe = _as_str(raw)
    result = _osascript(f'tell application "Spotify" to play track "{safe}"')
    if "error" in result:
        return result
    time.sleep(1.5)
    return _spotify_now_playing()


def _spotify_fetch_artwork_from_url(spotify_url: str) -> str | None:
    """Scrape album art from open.spotify.com/track/... via og:image meta."""
    import re
    import httpx
    try:
        if not spotify_url:
            return None
        # Normalize spotify:track:ID or https URL to open.spotify.com
        if spotify_url.startswith("spotify:"):
            parts = spotify_url.split(":")
            if len(parts) >= 3:
                spotify_url = f"https://open.spotify.com/{parts[1]}/{parts[2]}"
        if "open.spotify.com" not in spotify_url:
            return None
        with httpx.Client(timeout=4.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
            r = client.get(spotify_url)
            html = r.text[:50000]
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def _spotify_cmd(cmd: str) -> dict:
    result = _osascript(f'tell application "Spotify" to {cmd}')
    if "error" in result:
        return result
    time.sleep(1.5)
    return _spotify_now_playing()


def _spotify_volume(vol: int) -> dict:
    result = _osascript(f'tell application "Spotify" to set sound volume to {vol}')
    if "error" in result:
        return result
    return {"status": f"Volume set to {vol}"}


def _spotify_search_play(query: str) -> dict:
    # Properly URL-encode the query AND escape the resulting URI for the
    # AppleScript string literal. Without _as_str(), a query containing
    # a double-quote would close the AppleScript string and let arbitrary
    # AppleScript run. With it, the string is always sealed.
    from urllib.parse import quote as _quote
    safe_uri = _as_str(f"spotify:search:{_quote(query)}")
    result = _osascript(f'tell application "Spotify" to play track "{safe_uri}"')
    if "error" in result:
        # Fallback: argv-list call (no shell), URI already encoded.
        subprocess.run(["open", f"spotify:search:{_quote(query)}"], timeout=5)
    time.sleep(1.5)
    return _spotify_now_playing()


# ── Apple Mail ───────────────────────────────────────────────────────────────

def _mail_inbox(limit: int = 15) -> dict:
    """Read emails from Apple Mail (works without Azure/OAuth)."""
    script = f"""
tell application "Mail"
    set msgList to {{}}
    set allMsgs to messages of inbox
    set msgCount to count of allMsgs
    if msgCount > {limit} then set msgCount to {limit}
    repeat with i from 1 to msgCount
        set m to item i of allMsgs
        try
            set subj to subject of m
            set sndr to sender of m
            set rcvd to date received of m as string
            set isRead to read status of m
            set end of msgList to (subj & "|||" & sndr & "|||" & rcvd & "|||" & (isRead as string) & "###ROW###")
        end try
    end repeat
    return msgList
end tell
"""
    result = _osascript(script, timeout=20)
    if "error" in result:
        return result
    emails = []
    for line in result.get("output", "").split("###ROW###"):
        line = line.strip().lstrip(",").strip()
        parts = line.split("|||")
        if len(parts) >= 2 and parts[0].strip():
            sender_raw = parts[1].strip()
            emails.append({
                "subject": parts[0].strip(),
                "from_name": sender_raw,
                "from_email": sender_raw,
                "received": parts[2].strip() if len(parts) > 2 else "",
                "read": parts[3].strip() == "true" if len(parts) > 3 else True,
            })
    return {"emails": emails, "count": len(emails), "source": "apple_mail"}


# ── Apple Calendar ────────────────────────────────────────────────────────────

def _calendar_events(days: int = 30) -> dict:
    """Get upcoming events from calendars on the allowlist.

    Names are drawn from the CALENDAR_ALLOWLIST env var (comma-separated).
    Defaults to common names: Work, Subscribed Calendar, Classes, School,
    Family. The one45 rotation feed lives under "Subscribed Calendar" in
    Apple Calendar and is surfaced here as "Rotation".

    WHY fast-path / slow-path split: "Subscribed Calendar" (one45 rotation
    feed) is the most likely cause of AppleScript hangs — external CalDAV
    subscriptions can stall Calendar.app indefinitely while syncing.
    We run user-owned calendars first with a 5s budget, then attempt the
    subscribed feed with its own 5s budget and silently drop it on timeout
    rather than hanging the whole request.
    """
    # Pinned-allowlist scan. The naive `whose start date ...` predicate
    # against every calendar can take tens of seconds on large setups,
    # even for calendars that end up empty. Iterating only the calendars
    # on the allowlist keeps the AppleScript well under 5s.
    #
    # Users can extend the allowlist by setting CALENDAR_ALLOWLIST in .env
    # (comma-separated, case-sensitive). Names that don't exist on the
    # system are silently skipped.
    # Note: there can be TWO calendars with the same name — AppleScript's
    # `first calendar whose name is X` returns whichever Calendar.app
    # decides; we iterate ALL calendars matching the name to cover both.
    import os

    # Previous default ("Work,Classes,School,Family") was too restrictive: it
    # missed the user's iCloud personal calendar (pi37@njit.edu) where personal
    # events live, plus Europe and Birthdays/Holidays. All confirmed calendars
    # that can appear in Calendar.app are listed here. CALENDAR_ALLOWLIST env
    # var overrides the fast list entirely (comma-separated, case-sensitive).
    _default_fast = "Work,School,Family,Classes,Europe,pi37@njit.edu,Birthdays,US Holidays"
    _default_slow = "Subscribed Calendar"  # one45 rotation — separate because it can hang

    fast_raw = os.environ.get("CALENDAR_ALLOWLIST", _default_fast)
    fast_cals = [c.strip() for c in fast_raw.split(",") if c.strip() and c.strip() != _default_slow]
    slow_cals = [_default_slow]  # always attempt; timeout is the safety valve

    def _build_script(cal_list: list) -> str:
        """Build a single AppleScript that fetches all cals in cal_list.

        WHY no 'whose' predicate: some CalDAV-backed calendars (notably large
        Exchange Work calendars) hang indefinitely on any 'whose start date >= X'
        query — even with just a lower-bound filter. We avoid 'whose' entirely
        and instead iterate 'every event of cal' in start-date order, collecting
        events in [startDate, endDate] and breaking as soon as we pass endDate.

        WHY single script for the batch (not one subprocess per calendar):
        Calendar.app serializes AppleScript connections. Multiple simultaneous
        osascript processes cause it to queue/stall them, making each one time
        out before its turn. A single script for the non-problematic calendars
        runs them sequentially inside one AppleScript process — fast and reliable.
        Work is excluded from this batch because it takes 10–20 s regardless
        (CalDAV sync lock) and would burn the whole budget for everyone else.
        """
        _target_list = ", ".join(f'"{_as_str(c)}"' for c in cal_list)
        return f"""
tell application "Calendar"
    set startDate to current date
    set endDate to startDate + ({days} * days)
    set evtList to {{}}
    set targetNames to {{{_target_list}}}
    repeat with calName in targetNames
        try
            set matchingCals to (every calendar whose name is (calName as string))
            repeat with cal in matchingCals
                try
                    -- No 'whose' predicate: avoids CalDAV sync lock on large cals.
                    -- Events are stored in start-date order so we break early.
                    repeat with evt in (every event of cal)
                        try
                            set evtStart to start date of evt
                            if evtStart > endDate then exit repeat
                            if evtStart >= startDate then
                                set evtSummary to summary of evt
                                set evtStartStr to evtStart as string
                                set evtEnd to end date of evt as string
                                set evtLoc to ""
                                try
                                    set evtLoc to location of evt
                                end try
                                if evtLoc is missing value then set evtLoc to ""
                                set evtUid to ""
                                try
                                    set evtUid to uid of evt
                                end try
                                set end of evtList to (evtSummary & "|||" & evtStartStr & "|||" & evtEnd & "|||" & (calName as string) & "|||" & evtLoc & "|||" & evtUid & "###ROW###")
                            end if
                        end try
                    end repeat
                end try
            end repeat
        end try
    end repeat
    return evtList
end tell
"""

    def _fetch_cals(cal_list: list, timeout_s: int) -> list:
        """Run one AppleScript covering all cals in cal_list; return raw rows."""
        if not cal_list:
            return []
        result = _osascript(_build_script(cal_list), timeout=timeout_s)
        if "error" in result:
            return []
        return result.get("output", "").split("###ROW###")

    # Calendars known to cause AppleScript hangs on this system:
    #   Work     — Exchange CalDAV, 727+ events, hangs on any event query
    #   School   — iCloud CalDAV, hangs when mid-sync (frequent)
    #   pi37@njit.edu — iCloud personal, same sync issue as School
    # These are run individually in separate subprocesses so their hangs
    # don't affect the reliable calendars (Europe, Family, Classes, etc.)
    _KNOWN_SLOW = {"Work", "School", "pi37@njit.edu"}

    def _fetch_cals_safe_batch(cal_list: list, timeout_s: int) -> list:
        """Run reliable (non-blocking) calendars in one batch AppleScript."""
        if not cal_list:
            return []
        result = _osascript(_build_script(cal_list), timeout=timeout_s)
        if "error" in result:
            return []
        return result.get("output", "").split("###ROW###")

    def _fetch_cals_parallel(cal_list: list, per_cal_timeout_s: int) -> list:
        """Run each calendar in its own subprocess concurrently.

        Used for calendars known to block Calendar.app (Work, School, pi37):
        each gets its own osascript process so a hang only burns its own timeout
        budget without blocking the others.
        """
        import concurrent.futures as _cf
        if not cal_list:
            return []
        rows: list = []
        with _cf.ThreadPoolExecutor(max_workers=len(cal_list)) as pool:
            futs = {pool.submit(_osascript, _build_script([cal]), per_cal_timeout_s): cal
                    for cal in cal_list}
            for fut in _cf.as_completed(futs, timeout=per_cal_timeout_s + 1):
                try:
                    r = fut.result()
                    if "error" not in r:
                        rows.extend(r.get("output", "").split("###ROW###"))
                except Exception:
                    pass
        return rows

    # Split: reliable batch + slow-cal parallel, both run concurrently
    # so the total time is max(batch_time, slow_cal_time), not their sum.
    import concurrent.futures as _pool
    _reliable = [c for c in fast_cals if c not in _KNOWN_SLOW]
    _slow_cal_list = [c for c in fast_cals if c in _KNOWN_SLOW]

    # Strategy: reliable batch first (no Calendar.app contention), then
    # slow calendars in parallel with subscribed feed.
    # WHY not all concurrent: Calendar.app serializes AppleScript connections.
    # Launching 5+ concurrent osascript processes causes ALL of them to slow
    # down — even the fast ones get queued behind the slow ones. Running the
    # reliable batch alone (no competing processes) finishes in ~4-6s.
    # Then the slow/subscribed cals run concurrently with each other (they're
    # all going to timeout anyway, so they race rather than stack).
    reliable_result = _osascript(_build_script(_reliable), timeout=8) if _reliable else {"output": ""}
    reliable_succeeded = "error" not in reliable_result
    fast_rows = reliable_result.get("output", "").split("###ROW###") if reliable_succeeded else []

    # Now run the slow/known-hanging cals + subscribed feed concurrently.
    # They share the same Calendar.app queue but since they're all expected
    # to timeout, running them in parallel limits total wait to 8s not 13s.
    with _pool.ThreadPoolExecutor(max_workers=2) as pool:
        fut_slow = pool.submit(_fetch_cals_parallel, _slow_cal_list, 8)
        fut_sub  = pool.submit(_fetch_cals, slow_cals, 5)
        fast_rows = fast_rows + fut_slow.result()
        slow_rows = fut_sub.result()

    all_rows = fast_rows + slow_rows

    # Synthetic "output" string fed into the existing parser below.
    raw_combined = "###ROW###".join(all_rows)

    # Return structured error only when the reliable batch itself failed to run
    # (Calendar.app not responding at all). Zero events from a successful batch
    # just means no events in the requested window — that's a valid result.
    if not reliable_succeeded and not any(r.strip().lstrip(",").strip() for r in all_rows):
        return {"error": "Calendar fetch timed out — try opening Calendar.app to refresh subscribed feeds", "events": []}

    # Reuse existing parse path by constructing a fake _osascript-style result.
    result = {"output": raw_combined}

    events = []
    raw = result.get("output", "")
    # AppleScript emits U+202F (narrow no-break space) in time strings ("9:00\u202fAM")
    # on recent macOS. Normalize to plain space up-front so downstream consumers
    # (frontend Date parser, ISO converters) don't choke.
    raw = raw.replace("\u202f", " ").replace("\u00a0", " ")

    for line in raw.split("###ROW###"):
        line = line.strip().lstrip(",").strip()
        parts = line.split("|||")
        if len(parts) >= 2 and parts[0].strip():
            raw_cal = parts[3].strip() if len(parts) > 3 else ""
            start_iso = _applescript_dt_to_iso(parts[1].strip())
            end_iso = _applescript_dt_to_iso(parts[2].strip()) if len(parts) > 2 else ""
            events.append({
                "title": _clean_event_title(parts[0].strip()),
                "start": start_iso,
                "end": end_iso,
                "calendar": _normalize_calendar_name(raw_cal),
                "location": parts[4].strip() if len(parts) > 4 else "",
                "event_id": parts[5].strip() if len(parts) > 5 else None,
            })
    events.sort(key=lambda e: e["start"])
    return {"events": events, "count": len(events)}


def _applescript_dt_to_iso(s: str) -> str:
    """Parse 'Saturday, May 2, 2026 at 10:45:00 AM' → '2026-05-02T10:45:00'.
    Returns the original string on parse failure so callers still see something."""
    if not s:
        return ""
    import datetime as _dt
    cleaned = s.strip().replace(" ", " ").replace(" ", " ")
    for fmt in (
        "%A, %B %d, %Y at %I:%M:%S %p",
        "%A, %B %d, %Y at %I:%M %p",
        "%A, %B %d, %Y",
    ):
        try:
            return _dt.datetime.strptime(cleaned, fmt).isoformat()
        except ValueError:
            continue
    return cleaned


def _normalize_calendar_name(name: str) -> str:
    """Rename the one45 subscribed feed so the UI tag reads 'Rotation'."""
    if name == "Subscribed Calendar":
        return "Rotation"
    return name


def _clean_event_title(title: str) -> str:
    """one45 titles look like
        'Exams - OMS III::MCQ Exam - External:COMAT - PEDIATRICS::MCQ Exam - External:COMAT - PEDIATRICS: 12'
    Extract the most specific human-readable piece and drop the repetitive category
    prefix + trailing group-size token.
    """
    if "::" not in title:
        return title
    segments = [s.strip() for s in title.split("::") if s.strip()]
    if not segments:
        return title
    last = segments[-1]
    if ":" in last:
        pieces = [p.strip() for p in last.split(":") if p.strip()]
        # Drop trailing "group size" tokens like " 12" or " Full Class".
        if pieces and (pieces[-1].isdigit() or pieces[-1].lower() == "full class"):
            pieces = pieces[:-1]
        if pieces:
            return pieces[-1]
    return last


# ── Messages ──────────────────────────────────────────────────────────────────

def _messages_send(to: str, message: str) -> dict:
    # Use the centralized escape — original code had broken order
    # (escaped quote, then escaped backslash, which double-escaped the
    # already-escaped quote and let `\` close the string literal early).
    msg_escaped = _as_str(message)
    to_escaped = _as_str(to)
    script = f"""
tell application "Messages"
    try
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{to_escaped}" of targetService
        send "{msg_escaped}" to targetBuddy
        return "sent_imessage"
    on error
        try
            -- fallback: SMS via first available service
            set smsService to 1st service whose service type = SMS
            set smsBuddy to buddy "{to_escaped}" of smsService
            send "{msg_escaped}" to smsBuddy
            return "sent_sms"
        on error e2
            return "error: " & e2
        end try
    end try
end tell
"""
    result = _osascript(script)
    out = result.get("output", "")
    if "error" in out.lower() or "error" in result:
        return {"error": out or result.get("error")}
    return {"status": out, "to": to, "message": message[:50] + "…" if len(message) > 50 else message}


def _messages_recent(contact: str, limit: int = 20) -> dict:
    """Read recent messages using chat.db (more reliable than AppleScript)."""
    import sqlite3
    import os
    from datetime import datetime

    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        # Escape SQLite LIKE wildcards (% and _) in user-supplied input.
        # Without this, a contact of "%" matches every chat, and contacts
        # legitimately containing those characters also match too broadly.
        def _esc_like(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        esc = _esc_like(contact)
        # Search by handle id (phone) or display name. ESCAPE clause must
        # match the escape character used by _esc_like.
        cur.execute("""
            SELECT m.text, m.is_from_me, m.date / 1000000000 + 978307200 as ts
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat c ON cmj.chat_id = c.ROWID
            WHERE (c.chat_identifier LIKE ? ESCAPE '\\'
                   OR c.display_name LIKE ? ESCAPE '\\')
              AND m.text IS NOT NULL
            ORDER BY m.date DESC
            LIMIT ?
        """, (f"%{esc}%", f"%{esc}%", limit))
        rows = cur.fetchall()
        conn.close()
        messages = [
            {
                "text": row[0],
                "from_me": bool(row[1]),
                "time": datetime.fromtimestamp(row[2]).strftime("%Y-%m-%d %H:%M"),
            }
            for row in reversed(rows)
        ]
        return {"messages": messages, "count": len(messages)}
    except PermissionError:
        return {"error": "Full Disk Access not granted. Go to System Settings → Privacy → Full Disk Access → add Terminal."}
    except Exception as e:
        return {"error": str(e)}


# ── AppleScript runner ────────────────────────────────────────────────────────

def _osascript(script: str, timeout: int = 15) -> dict:
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            err = r.stderr.strip()
            # "not running" → give a friendly message
            if "not running" in err.lower():
                app = _extract_app_name(script)
                return {"error": f"{app} is not open. Ask Jarvis to open it first."}
            return {"error": err}
        return {"output": r.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"error": "AppleScript timed out — app may be busy or not responding."}


def _extract_app_name(script: str) -> str:
    import re
    m = re.search(r'application "([^"]+)"', script)
    return m.group(1) if m else "App"


# ── Open-in-App endpoints ─────────────────────────────────────────────────────

def open_outlook_email(email_id: str) -> dict:
    """Open a specific email in Microsoft Outlook by message id, fallback to inbox.

    email_id should be the Outlook message's integer id (as string) from the backend.
    Falls back to opening Outlook inbox if ID is empty or opening fails.
    """
    if email_id and email_id.strip():
        # Try to open by integer id using the correct Outlook AppleScript idiom:
        # Outlook's `id` property is an integer, not a string.
        # 1. Search inbox first (most common case)
        # 2. If not found, iterate all mail folders
        # 3. If still not found, just activate Outlook
        safe_id = email_id.strip()
        # Only use numeric IDs; non-numeric means legacy entry ID string that won't work
        if not safe_id.isdigit():
            safe_id = ""
        script = f"""
tell application "Microsoft Outlook"
    activate
    try
        set theMsg to first message of inbox whose id is {safe_id or 0}
        open theMsg
        return "opened_by_id"
    on error
        try
            repeat with f in mail folders
                try
                    set theMsg to first message of f whose id is {safe_id or 0}
                    open theMsg
                    return "opened_by_id"
                end try
            end repeat
        end try
        return "fallback_to_inbox"
    end try
end tell
"""
        result = _osascript(script, timeout=10)
        if "opened_by_id" in result.get("output", ""):
            return {"ok": True}

    # Fallback: open Outlook to inbox
    try:
        subprocess.run(["open", "-a", "Microsoft Outlook"], timeout=10, check=False)
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout opening Microsoft Outlook"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_messages_chat(phone: str = "", context: dict = None) -> dict:
    """Open Messages and initiate a chat with the given phone/handle or group chat ID.

    Three-tier routing:
      1. 1:1 chats (phone/email handle): try imessage://<URL-encoded handle>.
         On failure, fall back to AppleScript buddy lookup (handles iCloud email handles
         and non-ASCII characters that the URL scheme can't open directly).
      2. Group chats (chat_id only): try AppleScript `chat id` lookup; on failure,
         query ~/Library/Messages/chat.db for the chat GUID and open imessage://<guid>.
      3. Neither — just open Messages.app.

    Args:
        phone: phone/handle for 1:1 chats (legacy; prefer context.phone)
        context: dict with optional keys:
                 - phone: phone number or email handle
                 - chat_id: iMessage chat database ID (for group chats)
                 - is_group: bool hint (group path skips phone lookup even if phone present)
    """
    context = context or {}

    # Prefer context.phone over the legacy phone parameter
    phone_to_use = context.get("phone") or phone
    chat_id = context.get("chat_id")
    is_group = context.get("is_group", False)

    # Case 1: phone/handle available for a 1:1 chat
    if phone_to_use and phone_to_use.strip() and not is_group:
        handle = phone_to_use.strip()
        # URL-encode preserving @ and + so phone numbers and email handles work
        encoded = urllib.parse.quote(handle, safe="@+")
        try:
            proc = subprocess.run(
                ["open", f"imessage://{encoded}"],
                timeout=10,
                check=False
            )
            if proc.returncode == 0:
                return {"ok": True, "type": "1-1 chat", "target": handle}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout opening Messages"}
        except Exception:
            pass

        # Fallback: AppleScript buddy lookup (works for iCloud email handles)
        script = f"""
tell application "Messages"
    activate
    try
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{_as_str(handle)}" of targetService
        set targetChat to (first chat whose participants contains targetBuddy)
        show targetChat
        return "found_buddy"
    on error errMsg
        return "buddy_error: " & errMsg
    end try
end tell
"""
        try:
            result = _osascript(script, timeout=12)
            if "found_buddy" in result.get("output", ""):
                return {"ok": True, "type": "1-1 chat (applescript)", "target": handle}
            # AppleScript fallback also failed — open app only
            subprocess.run(["open", "-a", "Messages"], timeout=10, check=False)
            return {"ok": True, "type": "1-1 chat (app only)", "target": handle}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Case 2: chat_id available (group chat or explicit chat_id path)
    if chat_id:
        chat_id_str = str(chat_id)
        try:
            # Try to open Messages and display the chat by ID via AppleScript
            script = f"""
tell application "Messages"
    activate
    try
        set targetChat to (chat id "{chat_id_str}")
        show targetChat
        return "found_chat"
    on error
        return "chat_not_found"
    end try
end tell
"""
            result = _osascript(script, timeout=10)
            if "found_chat" in result.get("output", ""):
                return {"ok": True, "type": "group chat", "chat_id": chat_id_str}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout opening Messages"}
        except Exception:
            pass

        # Fallback: look up the chat GUID in chat.db and open via imessage:// URL
        try:
            db_path = os.path.expanduser("~/Library/Messages/chat.db")
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            row = conn.execute(
                "SELECT guid FROM chat WHERE ROWID = ?", (int(chat_id),)
            ).fetchone()
            conn.close()
            if row:
                guid = row[0]
                subprocess.run(["open", f"imessage://{guid}"], timeout=10, check=False)
                return {"ok": True, "type": "group chat (guid)", "chat_id": chat_id_str, "guid": guid}
        except Exception:
            pass

        # Last resort: open Messages app
        subprocess.run(["open", "-a", "Messages"], timeout=10, check=False)
        return {"ok": True, "type": "group chat (app only)", "chat_id": chat_id_str}

    # Case 3: neither phone nor chat_id — just open Messages
    try:
        subprocess.run(["open", "-a", "Messages"], timeout=10, check=False)
        return {"ok": True, "type": "app only"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout opening Messages"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_outlook_calendar(event_id: str = "") -> dict:
    """Open Outlook calendar view, optionally to a specific event."""
    script = """
tell application "Microsoft Outlook"
    activate
    try
        open calendar
        return "opened_calendar"
    on error
        return "error_opening_calendar"
    end try
end tell
"""
    result = _osascript(script, timeout=10)
    if "opened_calendar" in result.get("output", ""):
        return {"ok": True}

    # Fallback: just open Outlook
    try:
        subprocess.run(["open", "-a", "Microsoft Outlook"], timeout=10, check=False)
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout opening Microsoft Outlook"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_uworld(ref: str = "") -> dict:
    """Open UWorld in the default browser.

    Args:
        ref: "dashboard" opens the performance dashboard directly.
             Any other value (or empty string) opens the homepage.
    """
    course_id = os.environ.get("UWORLD_COURSE_ID", "14842106")
    if ref == "dashboard":
        url = f"https://apps.uworld.com/courseapp/usmle/v50/en-US/performance/dashboard/{course_id}"
    else:
        # The /login path returns 404; the homepage redirects to login when not authenticated.
        url = "https://www.uworld.com/"
    try:
        subprocess.run(["open", url], timeout=10, check=False)
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout opening UWorld"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_anki() -> dict:
    """Open Anki app using URL scheme or direct app launch."""
    try:
        # Try URL scheme first
        subprocess.run(
            ["open", "anki://"],
            timeout=10,
            check=False
        )
        return {"ok": True}
    except subprocess.TimeoutExpired:
        # Fallback to direct app launch
        try:
            subprocess.run(["open", "-a", "Anki"], timeout=10, check=False)
            return {"ok": True}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout opening Anki"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        # Try fallback
        try:
            subprocess.run(["open", "-a", "Anki"], timeout=10, check=False)
            return {"ok": True}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout opening Anki"}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


def open_app(app_name: str, ref: str = "", context: dict = None) -> dict:
    """Unified endpoint to open any supported app.

    Args:
        app_name: one of "outlook-email", "messages", "outlook-calendar", "uworld", "anki"
        ref: item ID or query (e.g., email ID, event ID, or phone number)
        context: optional dict with additional context (e.g., {"phone": "+1234567890", "chat_id": 12345})

    Returns:
        {"ok": true} on success or {"ok": false, "error": "..."} on failure
    """
    context = context or {}

    if app_name == "outlook-email":
        return open_outlook_email(ref)
    elif app_name == "messages":
        # Pass ref as first positional arg (phone), then context
        # open_messages_chat prefers context.phone over the legacy phone parameter
        return open_messages_chat(ref, context)
    elif app_name == "outlook-calendar":
        return open_outlook_calendar(ref)
    elif app_name == "uworld":
        return open_uworld(ref)
    elif app_name == "anki":
        return open_anki()
    else:
        return {"ok": False, "error": f"Unknown app: {app_name}"}
