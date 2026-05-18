"""
Tiered memory layer for Jarvis — COMPLEMENTS backend/agent/memory.py.

Three tiers:
- episodic    — raw session-summary blobs ("what happened in session X")
- semantic    — durable key/value facts (prefs, recurring people, projects)
- procedural  — learned behavioral rules with confidence scoring

Storage: dedicated sqlite file at backend/storage/tiered_memory.db.
We do NOT touch the project-root ruvector.db — its on-disk format is opaque
(not a standard SQLite database — `.schema` errors with "file is not a database"),
so reverse-engineering its schema would be fragile.

Retrieval today: keyword overlap + recency weighting for episodes.
TODO: swap keyword matching for RuVector embeddings once a clean API contract
is documented (either via the ruflo MCP or a published RuVector Python binding).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("jarvis.memory.tiered")

# Default DB lives in backend/storage/ — sibling to ruvector.db but separate file.
# Resolved relative to repo root so it survives `cd` shenanigans.
_DEFAULT_DB = (
    Path(__file__).resolve().parent.parent / "storage" / "tiered_memory.db"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_WORD_RE = re.compile(r"[A-Za-z0-9_]{3,}")


def _keywords(text: str) -> list[str]:
    """Lowercase word tokens >=3 chars. Used for episodic keyword search."""
    return [w.lower() for w in _WORD_RE.findall(text or "")]


class TieredMemory:
    """Three-tier persistent memory backed by SQLite.

    Thread-safe via per-thread connection (mirrors memory.py's pattern).
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._init_schema()

    # ── connection / schema ─────────────────────────────────────────── #

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        init = sqlite3.connect(str(self.db_path), check_same_thread=False)
        init.execute("PRAGMA journal_mode=WAL")
        try:
            init.executescript(
                """
                CREATE TABLE IF NOT EXISTS episodic (
                    id            TEXT PRIMARY KEY,
                    summary       TEXT NOT NULL,
                    session_id    TEXT NOT NULL,
                    ts            TEXT NOT NULL,
                    raw_keywords  TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_episodic_ts
                    ON episodic(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_episodic_session
                    ON episodic(session_id);

                CREATE TABLE IF NOT EXISTS semantic (
                    key             TEXT PRIMARY KEY,
                    value           TEXT NOT NULL,
                    source_session  TEXT,
                    updated_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS procedural (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule        TEXT UNIQUE NOT NULL,
                    confidence  REAL NOT NULL DEFAULT 0.5,
                    last_used   TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_procedural_conf
                    ON procedural(confidence DESC);
                """
            )
            init.commit()
        finally:
            init.close()

    # ── writes ──────────────────────────────────────────────────────── #

    def remember_episode(
        self, summary: str, session_id: str, ts: datetime | None = None
    ) -> str:
        """Insert an episodic memory and return its generated id."""
        eid = uuid.uuid4().hex
        ts_iso = (ts or datetime.now(timezone.utc)).isoformat()
        kws = " ".join(sorted(set(_keywords(summary))))
        conn = self._connect()
        conn.execute(
            "INSERT INTO episodic (id, summary, session_id, ts, raw_keywords) "
            "VALUES (?, ?, ?, ?, ?)",
            (eid, summary, session_id, ts_iso, kws),
        )
        conn.commit()
        _logger.debug("episodic+ id=%s session=%s len=%d", eid, session_id, len(summary))
        return eid

    def remember_semantic(
        self, key: str, value: str, source_session: str | None = None
    ) -> None:
        """Upsert a durable fact. Latest write wins."""
        now = _now_iso()
        conn = self._connect()
        conn.execute(
            "INSERT INTO semantic (key, value, source_session, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "  value = excluded.value, "
            "  source_session = excluded.source_session, "
            "  updated_at = excluded.updated_at",
            (key, value, source_session, now),
        )
        conn.commit()

    def remember_procedural(self, rule: str, confidence: float = 0.5) -> None:
        """Insert a behavioral rule, or bump confidence if it already exists."""
        now = _now_iso()
        confidence = max(0.0, min(1.0, float(confidence)))
        conn = self._connect()
        existing = conn.execute(
            "SELECT id, confidence FROM procedural WHERE rule = ?", (rule,)
        ).fetchone()
        if existing:
            # moving average — bumps toward 1.0 on repeat observation
            new_conf = (existing["confidence"] + confidence) / 2.0
            conn.execute(
                "UPDATE procedural SET confidence = ?, last_used = ? WHERE id = ?",
                (new_conf, now, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO procedural (rule, confidence, last_used) VALUES (?, ?, ?)",
                (rule, confidence, now),
            )
        conn.commit()

    # ── reads ───────────────────────────────────────────────────────── #

    def recall_episodes(self, query: str, limit: int = 5) -> list[dict]:
        """Keyword-overlap + recency-weighted episodic search.

        Score = (keyword_overlap_count + 1) * recency_factor
        where recency_factor decays linearly over 30 days.
        TODO: swap for RuVector embedding similarity once API is documented.
        """
        q_kws = set(_keywords(query))
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, summary, session_id, ts, raw_keywords FROM episodic "
            "ORDER BY ts DESC LIMIT 500"
        ).fetchall()
        now = datetime.now(timezone.utc)
        scored: list[tuple[float, dict]] = []
        for r in rows:
            row_kws = set((r["raw_keywords"] or "").split())
            overlap = len(q_kws & row_kws) if q_kws else 0
            try:
                age_days = max(
                    0.0,
                    (now - datetime.fromisoformat(r["ts"])).total_seconds() / 86400.0,
                )
            except ValueError:
                age_days = 30.0
            recency = max(0.1, 1.0 - (age_days / 30.0))
            score = (overlap + 1) * recency
            scored.append((score, dict(r)))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [d for _, d in scored[:limit]]

    def recall_semantic(
        self, query: str | None = None, key: str | None = None
    ) -> list[dict]:
        """Fetch semantic rows. key= → exact match; query= → LIKE on key/value;
        neither → all (capped at 200)."""
        conn = self._connect()
        if key is not None:
            rows = conn.execute(
                "SELECT key, value, source_session, updated_at FROM semantic "
                "WHERE key = ?",
                (key,),
            ).fetchall()
        elif query:
            like = f"%{query.lower()}%"
            rows = conn.execute(
                "SELECT key, value, source_session, updated_at FROM semantic "
                "WHERE LOWER(key) LIKE ? OR LOWER(value) LIKE ? "
                "ORDER BY updated_at DESC LIMIT 50",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, value, source_session, updated_at FROM semantic "
                "ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()
        return [dict(r) for r in rows]

    def recall_procedural(self, limit: int = 20) -> list[dict]:
        """Top procedural rules by confidence."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, rule, confidence, last_used FROM procedural "
            "ORDER BY confidence DESC, last_used DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── consolidation + context assembly ────────────────────────────── #

    def consolidate_session(
        self, session_id: str, transcript: str, claude_client: Any
    ) -> dict:
        """Extract facts/rules from a session transcript via a cheap Haiku call.

        Returns counts: {"episodic": int, "semantic": int, "procedural": int}.
        Best-effort: any LLM failure leaves the tiers untouched.
        """
        counts = {"episodic": 0, "semantic": 0, "procedural": 0}
        if not transcript.strip():
            return counts

        prompt = (
            "Read this session transcript and extract three buckets of memory.\n\n"
            "Return ONLY a JSON object with this exact shape:\n"
            "{\n"
            '  "episode_summary": "<one-paragraph summary of what happened>",\n'
            '  "semantic": [{"key": "<dotted.key>", "value": "<fact>"}],\n'
            '  "procedural": [{"rule": "<imperative rule>", "confidence": 0.0-1.0}]\n'
            "}\n\n"
            "- semantic = durable facts (preferences, names, project context, schedule).\n"
            "- procedural = behavioral rules (\"when X, do Y\").\n"
            "- Empty arrays are fine. Do not invent facts.\n\n"
            f"TRANSCRIPT:\n{transcript[:12000]}\n\nJSON:"
        )
        try:
            resp = claude_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(getattr(b, "text", "") for b in resp.content).strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end < 0:
                return counts
            data = json.loads(text[start : end + 1])
        except Exception as exc:
            _logger.debug("consolidate_session LLM call failed: %s", exc)
            return counts

        summary = (data.get("episode_summary") or "").strip()
        if summary:
            self.remember_episode(summary, session_id)
            counts["episodic"] = 1

        for item in data.get("semantic") or []:
            k = (item.get("key") or "").strip()
            v = (item.get("value") or "").strip()
            if k and v:
                self.remember_semantic(k, v, source_session=session_id)
                counts["semantic"] += 1

        for item in data.get("procedural") or []:
            rule = (item.get("rule") or "").strip()
            try:
                conf = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            if rule:
                self.remember_procedural(rule, conf)
                counts["procedural"] += 1

        _logger.info("consolidate_session %s → %s", session_id, counts)
        return counts

    def assemble_context(self, query: str, max_tokens: int = 2000) -> str:
        """Build a system-prompt-ready string from all three tiers.

        Rough token estimate: ~4 chars/token. Caps the byte budget at
        max_tokens*4 and trims the tail if overflowing.
        """
        budget = max_tokens * 4
        episodes = self.recall_episodes(query, limit=5)
        semantic = self.recall_semantic(query=query) if query else self.recall_semantic()
        procedural = self.recall_procedural(limit=20)

        parts: list[str] = []
        if procedural:
            parts.append("<procedural_rules>")
            for r in procedural:
                parts.append(f"- ({r['confidence']:.2f}) {r['rule']}")
            parts.append("</procedural_rules>")

        if semantic:
            parts.append("<semantic_facts>")
            for s in semantic[:30]:
                parts.append(f"- [{s['key']}] {s['value']}")
            parts.append("</semantic_facts>")

        if episodes:
            parts.append("<recent_episodes>")
            for e in episodes:
                parts.append(f"- {e['ts'][:10]} ({e['session_id'][:8]}): {e['summary']}")
            parts.append("</recent_episodes>")

        out = "\n".join(parts)
        if len(out) > budget:
            out = out[:budget] + "\n…[truncated]"
        return out


# ── smoke test ────────────────────────────────────────────────────── #

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    tm = TieredMemory()
    print(f"db: {tm.db_path}")
    print(f"semantic rows: {len(tm.recall_semantic())}")
    print(f"procedural rows: {len(tm.recall_procedural())}")
    print(f"episode probe: {len(tm.recall_episodes('test'))} hit(s)")
