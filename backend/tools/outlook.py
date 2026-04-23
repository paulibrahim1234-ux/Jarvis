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
             "time": m.received.strftime("%-I:%M %p") if m.received else "", "read": not m.is_read}
            for m in messages
        ]}

    if name == "outlook_draft_reply":
        return {"draft": inp.get("body", ""), "message_id": inp.get("message_id"),
                "note": "Confirm with user before sending."}

    if name == "outlook_get_calendar":
        from datetime import date, datetime, timezone, timedelta
        d = inp.get("date") or date.today().isoformat()
        try:
            target = date.fromisoformat(d)
        except ValueError:
            target = date.today()
        calendar = account.schedule().get_default_calendar()
        events = calendar.get_events(limit=20, include_recurring=True)
        return {"events": [
            {"title": e.subject, "start": str(e.start), "end": str(e.end),
             "location": str(e.location) if e.location else ""}
            for e in events
        ], "date": d}

    raise ValueError(f"Unknown outlook tool: {name}")
