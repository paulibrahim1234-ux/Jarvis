"""
Server-side persistent memory for Jarvis chatbot.
- SQLite at ~/.jarvis/chat.db
- conversations, messages, facts tables
- Fact extraction via a cheap Haiku call
- Dashboard snapshot helper (concurrent widget fetch)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

_logger = logging.getLogger("jarvis.memory")

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
#
# Philosophy: the user is a 3rd-year med student on surgery rotation.
# Their chat is full of medical vocabulary — "preceptor", "attending",
# "clinical rotation", "ICU", "patient record from yesterday", "differential
# for chest pain". These bare terms are NOT PHI: they're shop-talk about
# learning, schedule, and procedures, with no identifiable patient.
#
# Real PHI requires an actual identifier — an MRN, a patient ID with a
# digit, a DOB, etc. So we ONLY block when those concrete identifier
# patterns appear, not on bare clinical vocabulary. Long digit runs and
# phone/email are still scrubbed below as [REDACTED] (substitution, not
# wholesale rejection).
_PHI_MARKER_RE = re.compile(
    r"\bmrn\s*[:#]?\s*\d"
    r"|\bpatient\s+(?:id|record|mrn|chart)\s*[:#]?\s*\d"
    r"|\bpt\s+#\s*\d+"
    r"|\bdob\s*[:#]?\s*\d",
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


# Thread-local storage for the connection pool.
# WHY: every chat turn previously opened and closed ~14 sqlite3 connections
# (one per DB helper call). With FastAPI's threadpool (~4-50 workers) each
# thread now holds one persistent WAL connection for its lifetime, cutting
# per-turn connection overhead to a single dict lookup. WAL mode (set once
# in init_db) handles concurrent readers + one writer without locking.
_local = threading.local()


def _connect() -> sqlite3.Connection:
    """Per-thread persistent connection. WAL mode is sticky from init_db."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db() -> None:
    """Create tables on startup.

    WHY a dedicated connection here: init_db runs once at startup (from
    api/chat.py import time) and must set WAL mode then close. Using a
    separate raw connect() — not the thread-local pool — avoids storing
    a connection on the startup thread that FastAPI later recycles, which
    would leave a stale handle in _local.conn on that thread.
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    # Dedicated one-shot connection: set WAL (sticky in file header) then close.
    init_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    init_conn.execute("PRAGMA journal_mode=WAL")
    try:
        init_conn.executescript(
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
        init_conn.commit()
    finally:
        init_conn.close()


# ────────────────────────── conversations ────────────────────────── #

def create_conversation(title: Optional[str] = None) -> dict:
    cid = uuid.uuid4().hex
    now = _now_iso()
    title = title or "New chat"
    conn = _connect()
    # WHY no close: thread-local pool — connection persists for thread lifetime.
    conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (cid, title, now, now),
    )
    conn.commit()
    return {"id": cid, "title": title, "created_at": now, "updated_at": now}


def list_conversations() -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(cid: str) -> Optional[dict]:
    conn = _connect()
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


def delete_conversation(cid: str) -> bool:
    conn = _connect()
    cur = conn.execute("DELETE FROM conversations WHERE id = ?", (cid,))
    # CASCADE handles messages
    conn.commit()
    return cur.rowcount > 0


def conversation_exists(conversation_id: str) -> bool:
    """Return True if the conversation row exists — used to give a clear error
    when a client sends a stale or deleted conversation_id before we attempt
    to append a message and hit a FK constraint."""
    # WHY no close: thread-local pool — connection persists for thread lifetime.
    # The old try/finally:close was correct for the old per-call connect model;
    # with the pool, closing would drop the shared handle mid-thread.
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    return row is not None


def append_message(
    conversation_id: str,
    role: str,
    content: str,
    tool_calls: Optional[Any] = None,
) -> None:
    now = _now_iso()
    conn = _connect()
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


def get_recent_messages(conversation_id: str, limit: int = 40) -> list[dict]:
    """Return last N messages for a conversation, oldest-first, shaped for the API.

    Tool breadcrumbs (assistant rows prefixed with "[tool] ") are excluded in
    SQL so the LIMIT applies only to real messages — without this, breadcrumbs
    would steal context budget and Claude would lose earlier turns."""
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content FROM messages "
        "WHERE conversation_id = ? "
        "  AND NOT (role = 'assistant' AND content LIKE '[tool] %') "
        "ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    msgs = [{"role": r["role"], "content": r["content"]} for r in rows]
    msgs.reverse()
    return msgs


# ─────────────────────────── tool breadcrumbs ────────────────────────── #

def append_tool_summary(conversation_id: str, summary: str) -> None:
    """Persist a one-line breadcrumb of tools called in a turn.
    Stored as an assistant row prefixed with "[tool] " so it stays
    out of the API replay path (filtered by get_recent_messages) but
    is visible to build_system_prompt for cross-turn memory."""
    if not summary:
        return
    text = summary if summary.startswith("[tool] ") else f"[tool] {summary}"
    now = _now_iso()
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, tool_calls, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (conversation_id, "assistant", text, None, now),
    )
    conn.commit()


def get_recent_tool_breadcrumbs(conversation_id: str, limit: int = 10) -> list[str]:
    """Return the most-recent tool breadcrumbs for the conversation, oldest-first.
    Each item is the full content string (with the "[tool] " prefix stripped)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT content FROM messages WHERE conversation_id = ? "
        "AND role = 'assistant' AND content LIKE '[tool] %' "
        "ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    items = [(r["content"] or "")[len("[tool] "):] for r in rows]
    items.reverse()
    return items


# ──────────────────────────── facts ──────────────────────────────── #

def add_fact(topic: str, fact: str) -> None:
    now = _now_iso()
    conn = _connect()
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


def get_top_facts(limit: int = 10) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT topic, fact, created_at, last_used_at FROM facts "
        "ORDER BY last_used_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_facts(ids: list[int]) -> None:
    if not ids:
        return
    now = _now_iso()
    conn = _connect()
    qmarks = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE facts SET last_used_at = ? WHERE id IN ({qmarks})",
        (now, *ids),
    )
    conn.commit()


def extract_facts_async(user_msg: str, assistant_reply: str) -> None:
    """
    Fire a cheap Haiku call to extract durable user facts.
    Swallows all errors — fact extraction is best-effort.
    Fetches the current Anthropic client at call time so reloads are picked up.
    """
    # Scrub PHI before sending to LLM; abort entirely on PHI markers.
    clean_user = _scrub_phi(user_msg or "")
    if clean_user is None:
        return
    clean_assistant = _scrub_phi(assistant_reply or "")
    if clean_assistant is None:
        return

    # Look up the live client at call time — avoids stale client after reload.
    try:
        from agent import jarvis as _jarvis_mod
        client = _jarvis_mod.client
    except Exception:
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
    except Exception as exc:
        _logger.debug("extract_facts_async failed (best-effort): %s", exc)
        # intentionally not re-raised — fact extraction is best-effort


# ─────────────────────── dashboard snapshot ──────────────────────── #

async def _fetch_one(client: httpx.AsyncClient, path: str) -> dict:
    try:
        r = await client.get(f"{BACKEND_URL}{path}", timeout=3.0)
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        _logger.debug("dashboard widget %s fetch failed (best-effort): %s", path, exc)
        # intentionally not re-raised — widget fetch is best-effort
    return {}


def _format_snapshot(anki: dict, cal: dict, email: dict, spotify: dict) -> str:
    """Format widget dicts into the 5-line dashboard string.

    WHY extracted: both the in-process cache path and the HTTP fallback path in
    dashboard_snapshot_async need identical formatting. A shared helper ensures
    the two paths produce the same output and keeps each path lean.
    """
    # %-I and %-d are GNU libc extensions that fail on some macOS Python builds,
    # rendering as literal "%-I"/"%-d".  Strip leading zeros manually instead.
    _now = datetime.now()
    _hour = _now.strftime("%I").lstrip("0") or "0"
    _day  = str(_now.day)
    now_label = _now.strftime(f"%a %b {_day}, {_hour}:%M%p")

    lines = [f"Now: {now_label}."]

    # calendar
    _ROTATION_CALENDARS = {"Rotation", "Subscribed Calendar", "Work"}
    events = cal.get("events") or []
    if events:
        e0 = None
        for e in events:
            cal_name = (e.get("calendar") or "").strip()
            if cal_name not in _ROTATION_CALENDARS:
                e0 = e
                break
        if e0:
            raw_title = (e0.get("title") or "").strip()
            title = raw_title[:80]
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
        unread = sum(1 for e in emails if not e.get("read", True))
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


async def dashboard_snapshot_async() -> str:
    """Build the 5-line dashboard summary for the agent system prompt.

    Fast path (Perf#2): read widget data directly from api.widgets._CACHE
    (in-process dict lookup, ~0 ms) instead of firing 4 loopback HTTP GETs
    (~60-100 ms). Falls back to HTTP if the cache is cold or the import fails
    (e.g. cyclic import edge case on first startup).
    """
    import asyncio as _asyncio

    # ── Fast path: in-process cache read ──────────────────────────────────
    try:
        from api.widgets import build_snapshot_from_cache
        cached = build_snapshot_from_cache()
        if cached:
            # At least one widget hot — format and return immediately.
            return _format_snapshot(
                anki=cached.get("anki_stats", {}),
                cal=cached.get("calendar", {}),
                email=cached.get("email", {}),
                spotify=cached.get("spotify", {}),
            )
    except ImportError:
        # WHY catch ImportError only: a cyclic import at startup is the one
        # expected failure mode. Any other exception (e.g. KeyError in the
        # cache read) should surface, not be silently swallowed here.
        pass

    # ── Slow path: loopback HTTP (cache cold or import unavailable) ───────
    try:
        async with httpx.AsyncClient() as client:
            anki, cal, email, spotify = await _asyncio.gather(
                _fetch_one(client, "/widgets/anki"),
                _fetch_one(client, "/widgets/calendar"),
                _fetch_one(client, "/widgets/email"),
                _fetch_one(client, "/widgets/spotify"),
            )
    except Exception as exc:
        _logger.warning("dashboard_snapshot gather failed (affects user-visible state): %s", exc)
        # intentionally not re-raised — fall back to empty dicts
        anki = cal = email = spotify = {}

    return _format_snapshot(anki=anki, cal=cal, email=email, spotify=spotify)


def dashboard_snapshot() -> str:
    """Sync wrapper — safe from non-async contexts."""
    import asyncio
    try:
        asyncio.get_running_loop()
        # A running loop means we're inside an async context — caller should
        # await dashboard_snapshot_async instead of calling this sync wrapper.
        return "(dashboard unavailable in async context)"
    except RuntimeError:
        # No running loop — safe to use asyncio.run().
        pass
    try:
        return asyncio.run(dashboard_snapshot_async())
    except Exception:
        return "(dashboard unavailable)"


# ───────────────────────── system prompt ─────────────────────────── #

def build_system_prompt(
    base_prompt: str,
    dashboard: str,
    facts: list[dict],
    breadcrumbs: list[str] | None = None,
) -> list[dict]:
    """Build a list of Anthropic content blocks for the system= parameter.

    Returns a LIST (not a string) so prompt caching can be applied:
    - Block 1 (base_prompt): cached — stable across turns
    - Block 2 (known_facts): cached — stable for this user session
    - Block 3 (breadcrumbs): cached — stable within a turn
    - Block 4 (dashboard): NOT cached — changes every turn

    The caller passes this list directly as system= in messages.create().
    """
    # Block 1: stable base prompt — cache for 1 hour (requires extended-cache-ttl beta header)
    blocks: list[dict] = [
        {
            "type": "text",
            "text": base_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # Block 2: known facts — cached (stable across turns for same user)
    if facts:
        facts_lines = [
            "<known_facts>",
            "These are durable facts about the user from past conversations. "
            "Use them to personalize responses. Do NOT mention them unprompted.",
        ]
        for f in facts:
            facts_lines.append(f"- [{f['topic']}] {f['fact']}")
        facts_lines.append("</known_facts>")
        blocks.append({
            "type": "text",
            "text": "\n".join(facts_lines),
            "cache_control": {"type": "ephemeral"},
        })

    # Block 3: recent tool breadcrumbs — cached (stable within a turn)
    if breadcrumbs:
        bc_lines = [
            "<recent_tool_calls>",
            "These are tools you called on PREVIOUS turns of this conversation. "
            "If the user refers to something you just looked up (e.g. 'open it', "
            "'what about the next one'), you likely already have the answer in "
            "the recent message history — don't redundantly re-call the same tool.",
        ]
        for b in breadcrumbs:
            bc_lines.append(f"- {b}")
        bc_lines.append("</recent_tool_calls>")
        blocks.append({
            "type": "text",
            "text": "\n".join(bc_lines),
            "cache_control": {"type": "ephemeral"},
        })

    # Block 4: dashboard snapshot — NOT cached (changes every turn)
    blocks.append({
        "type": "text",
        "text": f"<dashboard>\n{dashboard}\n</dashboard>",
        # No cache_control — this block changes every turn
    })

    return blocks
