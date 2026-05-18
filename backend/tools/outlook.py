"""
Outlook / Microsoft Graph via python-o365.

Auth: Microsoft device code flow (no redirect URI needed).
Setup: visit http://127.0.0.1:8000/setup — enter credentials there.

Token stored at ~/.jarvis/ms_token.txt (auto-refreshed).
"""

import os
from pathlib import Path

TOKEN_DIR = Path.home() / ".jarvis"
SCOPES = ["Mail.Read", "Mail.Send", "Calendars.Read", "offline_access"]

OUTLOOK_TOOLS = [
    {
        "name": "outlook_get_emails",
        "description": "Get recent emails from the Outlook inbox.",
        "input_schema": {
            "type": "object",
            "properties": {"count": {"type": "integer", "default": 10}},
            "required": [],
        },
    },
    {
        "name": "outlook_draft_reply",
        "description": "Draft a reply to an email. Does NOT send — user must confirm.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "outlook_get_calendar",
        "description": "Get calendar events for today (or a given date).",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"}},
            "required": [],
        },
    },
]


def _creds():
    return (
        os.environ.get("MS_CLIENT_ID", ""),
        os.environ.get("MS_TENANT_ID", "common"),
    )


def _get_account():
    client_id, tenant = _creds()
    if not client_id:
        raise RuntimeError("MS_CLIENT_ID not set — visit http://127.0.0.1:8000/setup")
    try:
        from O365 import Account, FileSystemTokenBackend
    except ImportError:
        raise RuntimeError("O365 not installed. Run: pip install O365")
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    backend = FileSystemTokenBackend(token_path=str(TOKEN_DIR), token_filename="ms_token.txt")
    return Account(
        (client_id, None),
        auth_flow_type="device",
        tenant_id=tenant,
        token_backend=backend,
        scopes=SCOPES,
    )


def start_device_flow() -> dict:
    account = _get_account()
    if account.is_authenticated:
        return {"already_authenticated": True}
    import io, contextlib, re
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = account.authenticate()
    output = buf.getvalue()
    code_match = re.search(r"([A-Z0-9]{8,})", output)
    url_match = re.search(r"(https://microsoft\.com/devicelogin)", output)
    return {
        "message": "Open the URL and enter the code to authorize Jarvis.",
        "url": url_match.group(1) if url_match else "https://microsoft.com/devicelogin",
        "code": code_match.group(1) if code_match else "(check terminal)",
        "raw": output.strip(),
        "authenticated": bool(result),
    }


def is_authenticated() -> bool:
    try:
        client_id, _ = _creds()
        if not client_id:
            return False
        return _get_account().is_authenticated
    except Exception:
        return False


def _fmt_time(dt) -> str:
    """Portable hour formatting. %-I is GNU-only and crashes on systems
    without GNU strftime — strip leading zero manually instead."""
    if dt is None:
        return ""
    s = dt.strftime("%I:%M %p").lstrip("0")
    return s or "0:00"


def run_outlook_tool(name: str, inp: dict):
    account = _get_account()
    if not account.is_authenticated:
        return {"error": "Not authenticated — visit http://127.0.0.1:8000/auth/microsoft"}

    if name == "outlook_get_emails":
        mailbox = account.mailbox()
        messages = mailbox.inbox_folder().get_messages(limit=inp.get("count", 10))
        return {"emails": [
            {"id": m.object_id, "from": str(m.sender), "subject": m.subject,
             "preview": (m.body_preview or "")[:200],
             "time": _fmt_time(m.received), "read": not m.is_read}
            for m in messages
        ]}

    if name == "outlook_draft_reply":
        return {"draft": inp.get("body", ""), "message_id": inp.get("message_id"),
                "note": "Confirm with user before sending."}

    if name == "outlook_get_calendar":
        from datetime import date, datetime, time, timezone
        d = inp.get("date") or date.today().isoformat()
        try:
            target = date.fromisoformat(d)
        except ValueError:
            target = date.today()
        calendar = account.schedule().get_default_calendar()
        # Filter events to the target day. The previous version parsed
        # `target` but then fetched ALL events (limit=20) regardless of date,
        # so the `date` arg in the response was a lie. Use O365.utils.Query
        # if available; otherwise filter client-side after fetch.
        day_start = datetime.combine(target, time.min, tzinfo=timezone.utc)
        day_end = datetime.combine(target, time.max, tzinfo=timezone.utc)
        try:
            from O365.utils import Query as _Q
            q = _Q().chain("and") \
                .on_attribute("start").greater_equal(day_start) \
                .chain("and").on_attribute("end").less_equal(day_end)
            events = calendar.get_events(limit=50, include_recurring=True, query=q)
        except Exception:
            # Fallback: client-side filter. O365 returns datetime objects in
            # UTC; if .start has no tzinfo, assume naive UTC.
            all_events = calendar.get_events(limit=50, include_recurring=True)
            def _on_target(e):
                s = getattr(e, "start", None)
                if s is None:
                    return False
                if s.tzinfo is None:
                    s = s.replace(tzinfo=timezone.utc)
                return day_start <= s <= day_end
            events = [e for e in all_events if _on_target(e)]
        return {"events": [
            {"title": e.subject, "start": str(e.start), "end": str(e.end),
             "location": str(e.location) if e.location else ""}
            for e in events
        ], "date": d}

    raise ValueError(f"Unknown outlook tool: {name}")
