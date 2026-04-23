"""
Desktop app tools — drive Mac apps directly via AppleScript.
No OAuth, no Azure, no API keys needed.
Apps just need to be open and logged in.

Covers: Microsoft Outlook, Spotify, Apple Calendar, Messages
"""

import json
import subprocess
import time


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
            "Get recent emails from Microsoft Outlook desktop app. "
            "No Azure/OAuth needed — reads directly from the open app."
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
        "description": "Get upcoming calendar events from Microsoft Outlook desktop app.",
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
    # ── Spotify ──
    {
        "name": "spotify_get_track",
        "description": "Get the currently playing Spotify track, artist, album, and playback state.",
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
            "Get upcoming events from Apple Calendar (all user calendars, including "
            "rotation schedule from the one45 'Subscribed Calendar' feed)."
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
        "description": "Send an iMessage or SMS to a phone number or contact name.",
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
        "description": "Get recent iMessages from a contact or phone number.",
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
        # Escape any quotes in the user-supplied folder name.
        safe = folder_name.replace('"', '\\"')
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
            set entryId to entry id of m
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
    counts = _count_outlook_accounts()
    total_accounts = sum(counts.get(k, 0) for k in ("exchange", "imap", "pop"))
    if total_accounts == 0:
        err = counts.get("error") or "No Outlook accounts found. Is Outlook open and Classic mode enabled?"
        return {"error": err, "emails": []}

    per_account = max(limit, 10)  # over-fetch so merge picks the freshest
    all_emails: list[dict] = []
    accounts_seen: list[dict] = []
    acct_filter = (account or "").strip().lower()

    for acct_type in ("exchange", "imap", "pop"):
        n = counts.get(acct_type, 0)
        for idx in range(1, n + 1):
            result = _fetch_outlook_account_inbox(acct_type, idx, per_account, folder_name=folder)
            if result.get("error"):
                continue
            # Filter by account name/email if requested.
            if acct_filter:
                name_l = (result.get("account", "") or "").lower()
                email_l = (result.get("account_email", "") or "").lower()
                if acct_filter not in name_l and acct_filter not in email_l:
                    continue
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
            events.append({
                "title": parts[0].strip(),
                "start": parts[1].strip(),
                "end": parts[2].strip() if len(parts) > 2 else "",
                "location": parts[3].strip() if len(parts) > 3 else "",
                "calendar": "Outlook",
                "event_id": parts[4].strip() if len(parts) > 4 else None,
            })
    return {"events": events, "count": len(events)}


def _outlook_send(to: str, subject: str, body: str) -> dict:
    # Escape for AppleScript
    to_s = to.replace('"', '\\"')
    subj_s = subject.replace('"', '\\"')
    body_s = body.replace('"', '\\"').replace("\n", "\\n")
    script = f"""
tell application "Microsoft Outlook"
    set newMsg to make new outgoing message with properties {{subject:"{subj_s}", plain text content:"{body_s}"}}
    make new recipient at newMsg with properties {{email address:{{address:"{to_s}"}}}}
    send newMsg
    return "sent"
end tell
"""
    result = _osascript(script)
    if "error" in result:
        return result
    return {"status": "sent", "to": to, "subject": subject}


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
        "position_s": round(position_s),
        "state": parts[5] if len(parts) > 5 else "unknown",
        "uri": parts[6] if len(parts) > 6 else None,
        "volume": int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else None,
        "artwork_url": parts[8] if len(parts) > 8 and parts[8] else None,
    }


def _spotify_play_uri(uri: str) -> dict:
    """Play a Spotify URI (spotify:track:..., spotify:playlist:..., spotify:album:...)."""
    safe = (uri or "").replace('"', '').strip()
    if not safe:
        return {"error": "Empty URI"}
    result = _osascript(f'tell application "Spotify" to play track "{safe}"')
    if "error" in result:
        return result
    for _ in range(3):
        time.sleep(0.5)
        np = _spotify_now_playing()
        if np.get("track"):
            return np
    return _spotify_now_playing()


def _spotify_fetch_artwork_from_url(spotify_url: str) -> str | None:
    """Scrape album art from open.spotify.com/track/... via og:image meta."""
    import re
    import urllib.request
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
        req = urllib.request.Request(spotify_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            html = r.read(50000).decode("utf-8", errors="ignore")
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def _spotify_cmd(cmd: str) -> dict:
    result = _osascript(f'tell application "Spotify" to {cmd}')
    if "error" in result:
        return result
    for _ in range(3):
        time.sleep(0.5)
        np = _spotify_now_playing()
        if np.get("track"):
            return np
    return _spotify_now_playing()


def _spotify_volume(vol: int) -> dict:
    result = _osascript(f'tell application "Spotify" to set sound volume to {vol}')
    if "error" in result:
        return result
    return {"status": f"Volume set to {vol}"}


def _spotify_search_play(query: str) -> dict:
    # Use Spotify URI scheme to search and play
    uri = f"spotify:search:{query.replace(' ', '%20')}"
    result = _osascript(f'tell application "Spotify" to play track "{uri}"')
    if "error" in result:
        # Fallback: open via URL scheme
        subprocess.run(["open", f"spotify:search:{query}"], timeout=5)
    for _ in range(3):
        time.sleep(0.5)
        np = _spotify_now_playing()
        if np.get("track"):
            return np
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
    _default_cals = "Work,Subscribed Calendar,Classes,School,Family"
    _cals = [c.strip() for c in os.environ.get("CALENDAR_ALLOWLIST", _default_cals).split(",") if c.strip()]
    _target_list = ", ".join(f'"{c}"' for c in _cals)
    script = f"""
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
                    set calEvts to (every event of cal whose start date >= startDate and start date <= endDate)
                    repeat with evt in calEvts
                        try
                            set evtSummary to summary of evt
                            set evtStart to start date of evt as string
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
                            set end of evtList to (evtSummary & "|||" & evtStart & "|||" & evtEnd & "|||" & (calName as string) & "|||" & evtLoc & "|||" & evtUid & "###ROW###")
                        end try
                    end repeat
                end try
            end repeat
        end try
    end repeat
    return evtList
end tell
"""
    # 20s is plenty with the allowlist; raises only if Calendar.app is wedged.
    result = _osascript(script, timeout=20)
    if "error" in result:
        return result

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
            events.append({
                "title": _clean_event_title(parts[0].strip()),
                "start": parts[1].strip(),
                "end": parts[2].strip() if len(parts) > 2 else "",
                "calendar": _normalize_calendar_name(raw_cal),
                "location": parts[4].strip() if len(parts) > 4 else "",
                "event_id": parts[5].strip() if len(parts) > 5 else None,
            })
    events.sort(key=lambda e: e["start"])
    return {"events": events, "count": len(events)}


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
    msg_escaped = message.replace('"', '\\"').replace("\\", "\\\\")
    to_escaped = to.replace('"', '\\"')
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
        # Search by handle id (phone) or display name
        cur.execute("""
            SELECT m.text, m.is_from_me, m.date / 1000000000 + 978307200 as ts
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat c ON cmj.chat_id = c.ROWID
            WHERE (c.chat_identifier LIKE ? OR c.display_name LIKE ?)
              AND m.text IS NOT NULL
            ORDER BY m.date DESC
            LIMIT ?
        """, (f"%{contact}%", f"%{contact}%", limit))
        rows = cur.fetchall()
        conn.close()
        messages = [
            {
                "text": row[0],
                "from_me": bool(row[1]),
                "time": datetime.utcfromtimestamp(row[2]).strftime("%Y-%m-%d %H:%M"),
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
    """Open a specific email in Microsoft Outlook by entry ID, fallback to inbox.

    email_id should be the Outlook message's entry ID from the backend.
    Falls back to opening Outlook inbox if ID is empty or opening fails.
    """
    if email_id and email_id.strip():
        # Try to open by entry ID using the correct Outlook AppleScript idiom:
        # 1. Search inbox first (most common case)
        # 2. If not found, iterate all mail folders
        # 3. If still not found, just activate Outlook
        script = f"""
tell application "Microsoft Outlook"
    activate
    try
        set theMsg to first message of inbox whose id is "{email_id}"
        open theMsg
        return "opened_by_id"
    on error
        try
            repeat with f in mail folders
                try
                    set theMsg to first message of f whose id is "{email_id}"
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

    Handles three cases:
      1. context.phone available (1:1 chat) → open imessage://<phone>
      2. context.chat_id available (group chat) → open Messages and try to select by chat_id
      3. Neither → just open Messages app

    Args:
        phone: phone/handle for 1:1 chats (legacy; prefer context.phone)
        context: dict with optional keys:
                 - phone: phone number or email handle
                 - chat_id: iMessage chat database ID (for group chats)
    """
    context = context or {}

    # Prefer context.phone over the legacy phone parameter
    phone_to_use = context.get("phone") or phone
    chat_id = context.get("chat_id")

    # Case 1: phone/handle available (1:1 chat)
    if phone_to_use and phone_to_use.strip():
        try:
            subprocess.run(
                ["open", f"imessage://{phone_to_use.strip()}"],
                timeout=10,
                check=False
            )
            return {"ok": True, "type": "1-1 chat", "target": phone_to_use.strip()}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout opening Messages"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Case 2: chat_id available (group chat) — try AppleScript to open and show the chat
    if chat_id:
        try:
            chat_id_str = str(chat_id)
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
            # Fallback: just open Messages
            subprocess.run(["open", "-a", "Messages"], timeout=10, check=False)
            return {"ok": True, "type": "group chat (app only)", "chat_id": chat_id_str}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Timeout opening Messages"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

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


def open_uworld() -> dict:
    """Open UWorld login page in default browser."""
    try:
        subprocess.run(
            ["open", "https://www.uworld.com/login"],
            timeout=10,
            check=False
        )
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
        return open_uworld()
    elif app_name == "anki":
        return open_anki()
    else:
        return {"ok": False, "error": f"Unknown app: {app_name}"}
