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
    """Year-aware relative time formatter for conversation list preview.

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


def _fmt_time_in_thread(dt: datetime | None) -> str:
    """Formatter for per-message timestamps inside a conversation thread.

    same day        → 3:16 PM
    this week       → Fri 3:16 PM
    this year       → Apr 24, 3:16 PM
    older           → Apr 24, 2025
    """
    if dt is None:
        return ""
    today = date.today()
    d = dt.date()
    if d == today:
        return dt.strftime("%-I:%M %p")
    if (today - d).days < 7:
        return dt.strftime("%a %-I:%M %p")
    if d.year == today.year:
        return dt.strftime("%b %-d, %-I:%M %p")
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
        participants:    list of formatted handles in a group chat (DMs: empty list)
        participant_count: int (DMs: 1, groups: N)
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

        # Step 1: most-recent-message timestamp per chat (index-driven CTE).
        # Replaces the old GROUP BY full-scan (~1000ms) with a top-N scan on
        # the message.date index followed by a small aggregation (~12ms).
        chat_rows = conn.execute(
            f"""
            WITH recent_msgs AS (
                SELECT m.date AS d, cmj.chat_id
                FROM message m
                JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                WHERE m.text IS NOT NULL AND m.text != ''
                ORDER BY m.date DESC
                LIMIT 8000
            ),
            chat_max AS (
                SELECT chat_id, MAX(d) AS last_date
                FROM recent_msgs GROUP BY chat_id
            )
            SELECT c.ROWID                         AS chat_id,
                   c.style                         AS style,
                   c.display_name                  AS display_name,
                   c.chat_identifier               AS chat_identifier,
                   c.last_read_message_timestamp   AS last_read_ts,
                   cm.last_date                    AS last_date
            FROM chat_max cm
            JOIN chat c ON c.ROWID = cm.chat_id
            WHERE {style_filter}
            ORDER BY cm.last_date DESC
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

            # Pull ALL handles for this chat. For DMs that's one row; for groups
            # the full participant list — needed so the widget can render a
            # multi-name label ("Alice, Bob & 3 others") when the chat has no
            # display_name set.
            participant_rows = conn.execute(
                """
                SELECT h.id
                FROM chat_handle_join chj
                JOIN handle h ON h.ROWID = chj.handle_id
                WHERE chj.chat_id = ?
                ORDER BY h.ROWID
                """,
                (chat_id,),
            ).fetchall()
            participant_handles: list[str] = [r["id"] for r in participant_rows if r["id"]]
            handle = participant_handles[0] if participant_handles else cr["chat_identifier"]
            # Pretty-format participants for label rendering (kept as the
            # group's roster regardless of who sent the most recent message).
            formatted_participants = [_format_phone(p) for p in participant_handles]

            # Group label resolution:
            #   1. chat.display_name (if set — like "OMS3s 1.0", "Co-inhabitants…")
            #   2. comma-joined participant list, truncated to first 2 names
            #      ("Alice, Bob & 3 others") so it's clearly a multi-person thread
            #   3. fallback to formatted-handle for DMs (existing behavior)
            if is_group:
                display_name = (cr["display_name"] or "").strip()
                if display_name:
                    contact = display_name
                elif formatted_participants:
                    n = len(formatted_participants)
                    if n <= 2:
                        contact = " & ".join(formatted_participants)
                    else:
                        contact = (
                            f"{formatted_participants[0]}, {formatted_participants[1]}"
                            f" & {n - 2} other{'s' if n - 2 != 1 else ''}"
                        )
                else:
                    contact = "Group chat"
            else:
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
            # Include handle_id so we can resolve sender names in group chats.
            msg_rows = conn.execute(
                """
                SELECT m.text, m.is_from_me, m.date, m.handle_id
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
            # last_read_ts NULL (stored as 0 via "or 0") maps to Apple epoch
            # (Jan 1 2001), so "m.date > 0" would match all messages ever and
            # massively overcount unread.  When last_read is falsy, skip the
            # timestamp filter and rely solely on the is_read flag instead.
            last_read = cr["last_read_ts"] or 0
            if last_read:
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
            else:
                unread_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM message m
                    JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                    WHERE cmj.chat_id = ?
                      AND m.is_from_me = 0
                      AND m.is_read = 0
                    """,
                    (chat_id,),
                ).fetchone()[0]

            newest = msg_rows[0]
            newest_dt = _mac_ns_to_dt(newest["date"])

            # Build handle_id → display name map for group chats (one query).
            sender_names: dict[int, str] = {}
            if is_group:
                handle_id_list = list({mr["handle_id"] for mr in msg_rows if mr["handle_id"]})
                if handle_id_list:
                    placeholders2 = ",".join("?" for _ in handle_id_list)
                    handle_rows = conn.execute(
                        f"SELECT ROWID, id FROM handle WHERE ROWID IN ({placeholders2})",
                        handle_id_list,
                    ).fetchall()
                    for hr in handle_rows:
                        sender_names[hr["ROWID"]] = _format_phone(hr["id"])

            messages = []
            for mr in reversed(msg_rows):  # oldest → newest for UI
                dt = _mac_ns_to_dt(mr["date"])
                epoch_ms = (mr["date"] // 1_000_000) + MAC_EPOCH_OFFSET * 1000 if mr["date"] else None
                # Sender name: only meaningful for group chats on incoming msgs.
                sender: str | None = None
                if is_group and not mr["is_from_me"] and mr["handle_id"]:
                    raw_sender = sender_names.get(mr["handle_id"], "")
                    sender = raw_sender if raw_sender else None
                messages.append({
                    "text": _scrub(mr["text"]),
                    "time": _fmt_time_in_thread(dt),
                    "time_iso": dt.isoformat() if dt else None,
                    "epoch_ms": epoch_ms,
                    "isFromMe": bool(mr["is_from_me"]),
                    "sender": sender,
                })

            result.append({
                "contact": contact,
                "handle": handle or "",
                "chat_id": chat_id,
                "chat_identifier": cr["chat_identifier"] or "",
                "is_group": is_group,
                "participants": formatted_participants,
                "participant_count": len(formatted_participants) if is_group else 1,
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
    # Initialize before the try so a query exception doesn't leave `rows`
    # undefined and trigger a NameError when the comprehension below runs.
    rows: list = []
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
    except sqlite3.Error:
        # Schema drift, lock timeout, etc. — return an empty list instead
        # of crashing the agent tool dispatch.
        rows = []
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
