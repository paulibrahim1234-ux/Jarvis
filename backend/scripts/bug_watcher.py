#!/usr/bin/env python3
"""
Jarvis Bug Watcher — daemon that tails the backend error log and surfaces
actionable issues to the Claude-Code wakeup queue.

What it does:
  1. Tails ~/Library/Logs/jarvis-backend.err.log continuously.
  2. Classifies each line as 'critical' / 'warning' by pattern.
  3. Appends the last 50 high-signal lines to ~/.cache/jarvis/recent_bugs.json
     (rolling; oldest drops off when cap is hit).
  4. Appends CRITICAL-level items to ~/.cache/jarvis/CLAUDE_WAKEUP_QUEUE.txt
     so a future Claude-Code session can pick them up during /loop.

Install (run ONCE — does NOT auto-start):
  cp ~/jarvis/backend/scripts/com.jarvis.bugwatcher.plist \\
     ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.jarvis.bugwatcher.plist
  launchctl start com.jarvis.bugwatcher

Uninstall:
  launchctl unload ~/Library/LaunchAgents/com.jarvis.bugwatcher.plist

WHY a separate process (not a background thread in main.py):
  main.py is restarted by launchd on crash; a watcher embedded in it would
  lose its log position on restart. A separate daemon persists position via
  inode tracking and survives main.py restarts cleanly.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

LOG_PATH      = Path.home() / "Library/Logs/jarvis-backend.err.log"
CACHE_DIR     = Path.home() / ".cache/jarvis"
BUGS_JSON     = CACHE_DIR / "recent_bugs.json"
WAKEUP_QUEUE  = CACHE_DIR / "CLAUDE_WAKEUP_QUEUE.txt"
POSITION_FILE = CACHE_DIR / "bugwatcher_pos.json"  # inode + offset for resume on restart

MAX_BUG_ENTRIES = 50   # rolling cap on recent_bugs.json
POLL_INTERVAL   = 2.0  # seconds between tail polls

# ── Pattern classifier ────────────────────────────────────────────────────────

_CRITICAL_RE = re.compile(
    r"\b(ERROR|CRITICAL|Exception|Traceback|raise |Fatal)\b",
    re.IGNORECASE,
)
_WARNING_RE = re.compile(
    r"\b(WARNING|WARN|DeprecationWarning|UserWarning|timeout|timed out|rate.?limit)\b",
    re.IGNORECASE,
)
# Lines matching these are silently dropped — too noisy to be actionable.
_NOISE_RE = re.compile(
    r"(Started reloader|Application startup|Uvicorn running"
    r"|INFO:|DEBUG:"
    r"|cache HIT|cache STALE|cache MISS|SWR refresh)",
    re.IGNORECASE,
)


def classify(line: str) -> str | None:
    """Return 'critical', 'warning', or None (drop)."""
    if _NOISE_RE.search(line):
        return None
    if _CRITICAL_RE.search(line):
        return "critical"
    if _WARNING_RE.search(line):
        return "warning"
    return None


# ── State helpers ─────────────────────────────────────────────────────────────

def load_position() -> tuple[int, int]:
    """Return (inode, offset) of last-read position, or (0, 0) on first run."""
    if POSITION_FILE.exists():
        try:
            d = json.loads(POSITION_FILE.read_text())
            return int(d.get("inode", 0)), int(d.get("offset", 0))
        except Exception:
            pass
    return 0, 0


def save_position(inode: int, offset: int) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    POSITION_FILE.write_text(json.dumps({"inode": inode, "offset": offset}))


def load_bugs() -> list[dict]:
    if BUGS_JSON.exists():
        try:
            data = json.loads(BUGS_JSON.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_bugs(bugs: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    BUGS_JSON.write_text(json.dumps(bugs, indent=2))


def append_wakeup(entry: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{entry['ts']}] {entry['severity'].upper()}: {entry['line'][:200]}\n"
    with open(WAKEUP_QUEUE, "a") as f:
        f.write(line)


# ── Main tail loop ────────────────────────────────────────────────────────────

def run() -> None:
    """Tail the log file indefinitely, classifying and storing findings."""
    print(f"Bug watcher started. Watching: {LOG_PATH}", flush=True)
    print(f"Findings  → {BUGS_JSON}", flush=True)
    print(f"Wakeup    → {WAKEUP_QUEUE}", flush=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    saved_inode, offset = load_position()
    fh = None

    while True:
        try:
            # Detect log rotation (new inode) or first open.
            try:
                stat = LOG_PATH.stat()
                cur_inode = stat.st_ino
            except FileNotFoundError:
                # Log file doesn't exist yet; wait for it.
                time.sleep(POLL_INTERVAL)
                continue

            if fh is None or cur_inode != saved_inode:
                # New file or rotation — (re)open.
                if fh:
                    fh.close()
                fh = open(LOG_PATH, "r", errors="replace")
                if cur_inode == saved_inode:
                    # Same inode, just re-opened after error: seek to last position.
                    fh.seek(offset)
                else:
                    # New inode (rotation): start from beginning.
                    offset = 0
                saved_inode = cur_inode

            # Read any new lines since last poll.
            new_lines = fh.readlines()
            if not new_lines:
                time.sleep(POLL_INTERVAL)
                continue

            offset = fh.tell()
            save_position(saved_inode, offset)

            bugs = load_bugs()
            changed = False

            for raw in new_lines:
                line = raw.rstrip()
                if not line:
                    continue
                severity = classify(line)
                if severity is None:
                    continue

                entry = {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "severity": severity,
                    "line": line,
                }
                bugs.append(entry)
                changed = True

                if severity == "critical":
                    append_wakeup(entry)
                    print(f"[CRITICAL] {entry['ts']}: {line[:120]}", flush=True)
                else:
                    print(f"[WARNING]  {entry['ts']}: {line[:120]}", flush=True)

            if changed:
                # Keep only the last MAX_BUG_ENTRIES items (rolling window).
                if len(bugs) > MAX_BUG_ENTRIES:
                    bugs = bugs[-MAX_BUG_ENTRIES:]
                save_bugs(bugs)

        except Exception as exc:
            # Never crash the watcher — log the exception internally and keep going.
            print(f"[bugwatcher] internal error: {exc}", file=sys.stderr, flush=True)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
