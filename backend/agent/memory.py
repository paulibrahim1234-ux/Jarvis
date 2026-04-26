"""
Server-side persistent memory for Jarvis chatbot.
- SQLite at ~/.jarvis/chat.db
- conversations, messages, facts tables
- Fact extraction via a cheap Haiku call
- Dashboard snapshot helper (concurrent widget fetch)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

DB_DIR = Path.home() / ".jarvis"
DB_PATH = DB_DIR / "chat.db"
BACKEND_URL = "http://localhost:8000"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── PHI scrubber ────────────────────────────── #

# Patterns that replace specific PII with [REDACTED]
_PHI_PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)
_PHI_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
_PHI_LONGNUM_RE = re.compile(r"\b\d{7,}\b")

# PHI marker keywords that should trigger wholesale rejection.
# mrn and patient id use a left-word-boundary only (no right \b) because
# they commonly appear run together with digits (e.g. MRN12345, PatientID7).
_PHI_MARKER_RE = re.compile(
    r"\bmrn"
    r"|\battending\b"
    r"|\bpatient(?:\s*id)?"
    r"|\bdiagnosis\b"
    r"|\brotation\b"
    r"|\bpreceptor\b"
    r"|\bpt\b",
    re.IGNORECASE,
)


def _scrub_phi(text: str) -> "str | None":
    """Scrub PHI from *text* before sending to an LLM.

    Returns None if the text contains a PHI marker and must be rejected
    wholesale (caller should abort the LLM call entirely).
    Returns the scrubbed string otherwise (phone numbers, emails, and long
    digit runs replaced with [REDACTED]).
    """
    if _PHI_MARKER_RE.search(text):
        return None
    t = _PHI_PHONE_RE.sub("[REDACTED]", text)
    t = _PHI_EMAIL_RE.sub("[REDACTED]", t)
    t = _PHI_LONGNUM_RE.sub("[REDACTED]", t)
    return t


# ─────────────────────────────────────────────────────────────────────── #


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables on startup."""
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id           TEXT PRIMARY KEY,
                title        TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id  TEXT NOT NULL,
                role             TEXT NOT NULL,
                content          TEXT NOT NULL,
                tool_calls       TEXT,
                created_at       TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_id, id);

            CREATE TABLE IF NOT EXISTS facts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                topic         TEXT NOT NULL,
                fact          TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                last_used_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_facts_last_used
                ON facts(last_used_at DESC);
            """
        )
        conn.commit()
    finally:
        conn.close()


# ────────────────────────── conversations ────────────────────────── #

def create_conversation(title: Optional[str] = None) -> dict:
    cid = uuid.uuid4().hex
    now = _now_iso()
    title = title or "New chat"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (cid, title, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "title": title, "created_at": now, "updated_at": now}


def list_conversations() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation(cid: str) -> Optional[dict]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (cid,),
        ).fetchone()
        if not row:
            return None
        msgs = conn.execute(
            "SELECT id, role, content, tool_calls, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id ASC",
            (cid,),
        ).fetchall()
        return {
            **dict(row),
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": m["content"],
                    "tool_calls": json.loads(m["tool_calls"]) if m["tool_calls"] else None,
                    "created_at": m["created_at"],
                }
                for m in msgs
            ],
        }
    finally:
        conn.close()


def delete_conversation(cid: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def append_message(
    conversation_id: str,
    role: str,
    content: str,
    tool_calls: Optional[Any] = None,
) -> None:
    now = _now_iso()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls is not None else None,
                now,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        # Auto-title: if first user message, set as title (truncated)
        if role == "user":
            row = conn.execute(
                "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row and row["title"] in (None, "", "New chat"):
                title = content.strip().splitlines()[0][:60]
                if title:
                    conn.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (title, conversation_id),
                    )
        conn.commit()
    finally:
        conn.close()


def get_recent_messages(conversation_id: str, limit: int = 40) -> list[dict]:
    """Return last N messages for a conversation, oldest-first, shaped for the API."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        msgs = [{"role": r["role"], "content": r["content"]} for r in rows]
        msgs.reverse()
        return msgs
    finally:
        conn.close()


# ──────────────────────────── facts ──────────────────────────────── #

def add_fact(topic: str, fact: str) -> None:
    now = _now_iso()
    conn = _connect()
    try:
        # dedupe on (topic, fact) — update timestamps if exists
        existing = conn.execute(
            "SELECT id FROM facts WHERE topic = ? AND fact = ?", (topic, fact)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE facts SET last_used_at = ? WHERE id = ?", (now, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO facts (topic, fact, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?)",
                (topic, fact, now, now),
            )
        conn.commit()
    finally:
        conn.close()


def get_top_facts(limit: int = 10) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT topic, fact, created_at, last_used_at FROM facts "
            "ORDER BY last_used_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def touch_facts(ids: list[int]) -> None:
    if not ids:
        return
    now = _now_iso()
    conn = _connect()
    try:
        qmarks = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE facts SET last_used_at = ? WHERE id IN ({qmarks})",
            (now, *ids),
        )
        conn.commit()
    finally:
        conn.close()


def extract_facts_async(client, user_msg: str, assistant_reply: str) -> None:
    """
    Fire a cheap Haiku call to extract durable user facts.
    Swallows all errors — fact extraction is best-effort.
    """
    # Scrub PHI before sending to LLM; abort entirely on PHI markers.
    clean_user = _scrub_phi(user_msg or "")
    if clean_user is None:
        return
    clean_assistant = _scrub_phi(assistant_reply or "")
    if clean_assistant is None:
        return

    prompt = (
        "Extract any DURABLE user facts from this exchange "
        "(preferences, identity, schedule, names, goals, constraints). "
        "Return ONLY a JSON array of {topic, fact} objects. "
        "Return an empty array [] if there are no durable facts. "
        "Skip trivial/transient facts (what they're looking at now, one-off requests).\n\n"
        f"USER: {clean_user}\n"
        f"ASSISTANT: {clean_assistant}\n\n"
        "JSON array:"
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text
        text = text.strip()
        # strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < 0:
            return
        items = json.loads(text[start : end + 1])
        for item in items:
            topic = (item.get("topic") or "").strip()
            fact = (item.get("fact") or "").strip()
            if topic and fact:
                # Gate add_fact: skip if LLM echoed PHI
                if _scrub_phi(topic) is None or _scrub_phi(fact) is None:
                    continue
                add_fact(topic, fact)
    except Exception:
        pass


# ─────────────────────── dashboard snapshot ──────────────────────── #

async def _fetch_one(client: httpx.AsyncClient, path: str) -> dict:
    try:
        r = await client.get(f"{BACKEND_URL}{path}", timeout=3.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


async def dashboard_snapshot_async() -> str:
    """Concurrent fetch of widget state → 5-line summary."""
    now_label = datetime.now().strftime("%a %b %d, %-I:%M%p")
    try:
        async with httpx.AsyncClient() as client:
            import asyncio
            anki, cal, email, spotify = await asyncio.gather(
                _fetch_one(client, "/widgets/anki"),
                _fetch_one(client, "/widgets/calendar"),
                _fetch_one(client, "/widgets/email"),
                _fetch_one(client, "/widgets/spotify"),
            )
    except Exception:
        anki = cal = email = spotify = {}

    lines = [f"Now: {now_label}."]

    # calendar — skip events from any HIPAA-sensitive calendar (rotations,
    # subscribed clinical feeds, Outlook). Title text from those events must
    # never reach the LLM context.
    from hipaa import LLM_HIDDEN_CALENDARS, is_hidden
    _UPPERCASE_TOKEN_RE = re.compile(r"\b[A-Z]{2,3}\b")
    events = cal.get("events") or []
    if events:
        # Find first non-redacted event
        e0 = None
        for e in events:
            if not is_hidden(e.get("calendar"), LLM_HIDDEN_CALENDARS):
                e0 = e
                break
        if e0:
            raw_title = (e0.get("title") or "").strip()
            title = raw_title[:80]
            title = _UPPERCASE_TOKEN_RE.sub("[REDACTED]", title)
            start = (e0.get("start") or "").strip()
            lines.append(f"Next event: {title} @ {start}.")
        else:
            lines.append("No non-rotation events today.")
    else:
        lines.append("No upcoming events loaded.")

    # anki
    if anki.get("available"):
        due = anki.get("due", 0)
        ret = anki.get("retention", 0)
        reviewed = anki.get("reviewedToday", 0)
        lines.append(
            f"Anki: {due} due, {reviewed} reviewed today, {ret}% retention (30d)."
        )
    else:
        lines.append("Anki: not available.")

    # email
    if email.get("available"):
        emails = email.get("emails", []) or []
        unread = sum(1 for e in emails if e.get("unread") or e.get("is_unread"))
        lines.append(f"Inbox: {unread} unread (of {len(emails)} loaded).")
    else:
        lines.append("Inbox: not available.")

    # spotify
    if spotify.get("available") and spotify.get("track"):
        t = spotify["track"]
        title = t.get("title") or t.get("name") or "?"
        state = "playing" if t.get("is_playing") else "paused"
        lines.append(f"Spotify {state} on \"{title}\".")
    else:
        lines.append("Spotify: not running.")

    return "\n".join(lines)


def dashboard_snapshot() -> str:
    """Sync wrapper — safe from non-async contexts."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # we're inside an async context — caller should await dashboard_snapshot_async
            return "(dashboard unavailable in sync path)"
    except RuntimeError:
        pass
    try:
        return asyncio.run(dashboard_snapshot_async())
    except Exception:
        return "(dashboard unavailable)"


# ───────────────────────── system prompt ─────────────────────────── #

def build_system_prompt(base_prompt: str, dashboard: str, facts: list[dict]) -> str:
    parts = [base_prompt, "", "<dashboard>", dashboard, "</dashboard>"]
    if facts:
        parts.append("")
        parts.append("<known_facts>")
        parts.append(
            "These are durable facts about the user from past conversations. "
            "Use them to personalize responses. Do NOT mention them unprompted."
        )
        for f in facts:
            parts.append(f"- [{f['topic']}] {f['fact']}")
        parts.append("</known_facts>")
    return "\n".join(parts)
