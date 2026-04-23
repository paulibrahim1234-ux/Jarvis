"""
iMessage read tool — queries macOS chat.db (read-only).

Reads ~/Library/Messages/chat.db. The process (the specific python binary
behind the launchd uvicorn worker, /opt/homebrew/Cellar/python@3.12/.../bin/python3.12)
must have Full Disk Access. Grant in System Settings → Privacy & Security → Full Disk Access.

One conversation entry per contact (DM). Group chats filtered by default.
"""

import re
import sqlite3
import os
import sys
from datetime import datetime, timezone, date, timedelta

CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")

# Apple Core Data epoch: seconds since 2001-01-01 00:00:00 UTC
MAC_EPOCH_OFFSET = 978307200

# chat.style: 45 = DM (one-on-one), 43 = group chat
STYLE_DM = 45
STYLE_GROUP = 43


# ── timestamp helpers ─────────────────────────────────────────────────────────

def _mac_ns_to_dt(ts: int) -> datetime | None:
    """Apple `date` col is ns since 2001-01-01 UTC. Convert to local datetime."""
    if ts is None or ts == 0:
        return None
    try:
        secs = ts / 1e9 + MAC_EPOCH_OFFSET
        return datetime.fromtimestamp(secs, tz=timezone.utc).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def _fmt_time(dt: datetime | None) -> str:
    """Year-aware relative time formatter.

    today           → 10:42 AM
    yesterday       → Yesterday
    this week       → Mon
    this year       → Mar 1
    older           → Mar 1, 2024     (year shown so old threads aren't
                                       confused for current ones)
    """
    if dt is None:
        return ""
    today = date.today()
    d = dt.date()
    if d == today:
        return dt.strftime("%-I:%M %p")
    if d == today - timedelta(days=1):
        return "Yesterday"
    if (today - d).days < 7:
        return dt.strftime("%a")
    if d.year == today.year:
        return dt.strftime("%b %-d")
    return dt.strftime("%b %-d, %Y")


# ── privacy scrubber ──────────────────────────────────────────────────────────

# 10+ digit phone sequences, 5+ digit numbers in message body, street-address
# style matches. Intent: reduce risk of leaking another person's PII into the
# frontend payload without destroying the body text.
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_LONGNUM_RE = re.compile(r"\b\d{7,}\b")
_ADDR_RE = re.compile(
    r"\b\d{1,5}\s+\w+(?:\s+\w+){0,4}\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ct|Court|Way|Pl|Place)\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _scrub(text: str | None) -> str:
    if not text:
        return ""
    t = text.replace("\ufffc", "")  # attachment sentinel
    t = _PHONE_RE.sub("[phone]", t)
    t = _ADDR_RE.sub("[address]", t)
    t = _EMAIL_RE.sub("[email]", t)
    t = _LONGNUM_RE.sub("[num]", t)
    return t.strip()


# ── contact name / phone formatting ───────────────────────────────────────────

def _format_phone(raw: str | None) -> str:
    # Sentinel for missing handle is empty string — NOT "Unknown" — so that
    # multiple unknown-handle chats don't collapse to a single dedup key.
    # Caller is responsible for substituting a stable placeholder if needed.
    if not raw:
        return ""
    s = raw.strip()
    # Email-style iMessage id — leave as-is
    if "@" in s:
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) == 11 and digits.startswith("1"):
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
    return s


def _best_contact_name(display_name: str | None, handle: str | None) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    return _format_phone(handle)


# ── DB connection ─────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    if not os.path.exists(CHAT_DB):
        raise FileNotFoundError(f"chat.db not found at {CHAT_DB}")
    try:
        return sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "unable to open" in msg or "authorization denied" in msg:
            raise PermissionError(
                f"Cannot read chat.db — grant Full Disk Access to {sys.executable} "
                "in System Settings → Privacy → Full Disk Access."
            ) from e
        raise


# ── main query ────────────────────────────────────────────────────────────────

def get_conversations(
    *,
    limit: int = 25,
    messages_per_thread: int = 15,
    include_groups: bool = False,
) -> list[dict]:
    """Return a list of conversations, one per contact, most-recent first.

    Each entry:
        contact:         display name or formatted phone
        handle:          raw handle id (phone / email)
        chat_id:         chat.ROWID (stable identifier for the chat row)
        is_group:        bool
        unread_count:    # messages after chat.last_read_message_timestamp
                         where is_from_me = 0
        last_message:    scrubbed preview of newest message
        last_message_from_me: bool
        last_time:       formatted time string ("3:42 PM", "Yesterday", "Mon")
        messages:        oldest→newest list of {text, time, isFromMe}
    """
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        style_filter = (
            f"c.style IN ({STYLE_DM},{STYLE_GROUP})" if include_groups
            else f"c.style = {STYLE_DM}"
        )

        # Step 1: most-recent-message timestamp per chat
        chat_rows = conn.execute(
            f"""
            SELECT
                c.ROWID                              AS chat_id,
                c.style                              AS style,
                c.display_name                       AS display_name,
                c.chat_identifier                    AS chat_identifier,
                c.last_read_message_timestamp        AS last_read_ts,
                MAX(m.date)                          AS last_date
            FROM chat c
            JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
            JOIN message m             ON m.ROWID    = cmj.message_id
            WHERE {style_filter}
              AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
            GROUP BY c.ROWID
            ORDER BY last_date DESC
            LIMIT ?
            """,
            # Over-fetch x3 so we can safely collapse duplicate handles
            # without losing newer threads. Higher multipliers (we tried *6)
            # made the per-chat SQL trio (handle + messages + unread) blow
            # the FastAPI threadpool budget — each chat is ~3 round trips,
            # so 150 chats = ~450 trips = ~20s. *3 is the sweet spot.
            (limit * 3,),
        ).fetchall()

        result: list[dict] = []
        seen_contacts: set[str] = set()

        for cr in chat_rows:
            chat_id = cr["chat_id"]
            is_group = cr["style"] == STYLE_GROUP

            # pull primary handle for this chat (first handle id for DMs)
            handle_row = conn.execute(
                """
                SELECT h.id
                FROM chat_handle_join chj
                JOIN handle h ON h.ROWID = chj.handle_id
                WHERE chj.chat_id = ?
                ORDER BY h.ROWID
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
            handle = handle_row["id"] if handle_row else cr["chat_identifier"]

            contact = _best_contact_name(cr["display_name"], handle)

            # De-dup on a STABLE identifier (handle) — not on the formatted
            # display string. Display strings can collide across people
            # ("Unknown", same name two roommates) and silently drop the
            # newer thread. Falling back to chat_identifier (then chat_id)
            # keeps every otherwise-anonymous chat distinct.
            dedup_key = (
                (handle or cr["chat_identifier"] or f"chat-{chat_id}")
                .lower()
            )
            if dedup_key in seen_contacts:
                continue
            seen_contacts.add(dedup_key)

            # Step 2: recent messages in this chat, newest first
            msg_rows = conn.execute(
                """
                SELECT m.text, m.is_from_me, m.date
                FROM message m
                JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                WHERE cmj.chat_id = ?
                  AND m.text IS NOT NULL
                  AND m.text != ''
                ORDER BY m.date DESC
                LIMIT ?
                """,
                (chat_id, messages_per_thread),
            ).fetchall()

            if not msg_rows:
                continue

            # Step 3: unread count (messages after last_read, not from me)
            last_read = cr["last_read_ts"] or 0
            unread_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM message m
                JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                WHERE cmj.chat_id = ?
                  AND m.is_from_me = 0
                  AND m.date > ?
                  AND m.is_read = 0
                """,
                (chat_id, last_read),
            ).fetchone()[0]

            newest = msg_rows[0]
            newest_dt = _mac_ns_to_dt(newest["date"])

            messages = []
            for mr in reversed(msg_rows):  # oldest → newest for UI
                dt = _mac_ns_to_dt(mr["date"])
                messages.append({
                    "text": _scrub(mr["text"]),
                    "time": _fmt_time(dt),
                    "time_iso": dt.isoformat() if dt else None,
                    "isFromMe": bool(mr["is_from_me"]),
                })

            result.append({
                "contact": contact,
                "handle": handle or "",
                "chat_id": chat_id,
                "is_group": is_group,
                "unread_count": int(unread_count),
                "last_message": _scrub(newest["text"])[:160],
                "last_message_from_me": bool(newest["is_from_me"]),
                "last_time": _fmt_time(newest_dt),
                "last_time_iso": newest_dt.isoformat() if newest_dt else None,
                "messages": messages,
            })

            if len(result) >= limit:
                break

        return result
    finally:
        conn.close()


# Back-compat name (old widgets.py import)
def get_recent_conversations(limit: int = 20) -> list[dict]:
    return get_conversations(limit=limit, include_groups=False)


def get_recent_messages(contact_handles: list[str], limit: int = 20) -> list[dict]:
    """Fetch messages for specific handles (phone numbers / emails)."""
    if not contact_handles:
        return []
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in contact_handles)
        rows = conn.execute(
            f"""
            SELECT m.text, m.is_from_me, m.date, h.id
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE h.id IN ({placeholders}) AND m.text IS NOT NULL
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (*contact_handles, limit),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "text": _scrub(row[0]),
            "isFromMe": bool(row[1]),
            "time": _fmt_time(_mac_ns_to_dt(row[2])),
            "handle": row[3],
        }
        for row in rows
    ]
