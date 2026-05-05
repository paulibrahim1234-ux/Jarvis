"""
Widget endpoints — try desktop apps first, fall back to API-based tools.
Desktop apps (Outlook, Spotify) work with no OAuth or Azure setup.
"""

import datetime as _datetime
import threading
import time
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel
from api._security import _require_local_origin
from tools.anki import _invoke as anki_invoke, _invoke_multi as anki_invoke_multi
from tools.imessage import get_conversations
# Imported at module level so _cached() can detect the sentinel without a
# per-call import — avoids the hot-path overhead on every cache write and
# lets the short-TTL guard in _cached fire correctly (an opaque object()
# won't match None/{}/[], so without this it cached at full 60s TTL).
from tools.spotify import RATE_LIMITED_SENTINEL as _RATE_LIMITED_SENTINEL
from tools.desktop_apps import (
    run_desktop_tool,
    _outlook_inbox,
    _outlook_calendar,
    _spotify_now_playing,
    _spotify_cmd,
    _spotify_volume,
    _spotify_play_uri,
    _spotify_fetch_artwork_from_url,
    _calendar_events,
    _mail_inbox,
    _osascript,
)

router = APIRouter()

# Simple TTL cache: {key: (expires_at, value)}
_CACHE: dict = {}
_CACHE_MAX = 128  # upper bound on number of live cache entries
# Lock around eviction + write — protects against the rare race where two
# threads both pass the `len() >= _CACHE_MAX` check, both pick the same
# oldest_key, and the second thread's `del` raises KeyError mid-request.
_CACHE_LOCK = threading.Lock()

# Semaphores: prevent back-to-back AppleScript calls from stacking up on the
# threadpool. A single permit per heavy route is enough — cache absorbs all
# subsequent reads while a compute is in flight.
_SEM_CALENDAR = threading.Semaphore(1)
_SEM_EMAIL = threading.Semaphore(1)
_SEM_EMAIL_FOLDERS = threading.Semaphore(1)
_SEM_STUDY_STREAK = threading.Semaphore(1)

def _cached(key: str, ttl: float, compute, sem: threading.Semaphore | None = None):
    """Return cached value when fresh; otherwise compute and store.

    If *sem* is provided it is acquired before calling compute() so that
    concurrent slow AppleScript calls don't pile up on the threadpool.
    The semaphore is released immediately after compute() returns (or
    raises), not held for the duration of the request.

    Negative results (None, empty dict, empty list) are cached at a short
    TTL (10s) instead of the full TTL. This was the "stuff disappears"
    bug: when an AppleScript call timed out and compute() returned None,
    the None got cached for 10 minutes, and the widget looked
    permanently broken even after the underlying app recovered.

    Cold-start behavior: when sem timeout AND no entry exists yet, fall
    through and compute without the semaphore guard. The old "return None"
    path here meant the very first request after backend startup (before
    warmup populated the cache) saw a null payload and the widget showed
    an error state for no reason.
    """
    now = time.time()
    entry = _CACHE.get(key)
    if entry and entry[0] > now:
        return entry[1]
    if sem is not None:
        acquired = sem.acquire(blocking=True, timeout=0.05)
        if not acquired:
            if entry:
                # Stale data is fine — sibling thread is recomputing.
                return entry[1]
            # Cold start, no stale data: do an unguarded compute. We
            # accept the rare duplicate call to avoid handing back None.
            value = compute()
        else:
            try:
                value = compute()
            finally:
                sem.release()
    else:
        value = compute()
    # Short TTL on negative results so a one-time failure doesn't lock in.
    # RATE_LIMITED_SENTINEL is an opaque object() — it won't match None/{}/ []
    # — so it must be checked explicitly; otherwise a 429 gets cached for the
    # full TTL (up to 60s) instead of the intended 10s back-off window.
    effective_ttl = ttl
    if value is None or value == {} or value == [] or value is _RATE_LIMITED_SENTINEL:
        effective_ttl = min(ttl, 10.0)
    # LRU-style eviction under a lock — `min()` then `del` is not atomic
    # without one, and a concurrent eviction can KeyError-crash the
    # endpoint with a generic 500.
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX and key not in _CACHE:
            try:
                oldest_key = min(_CACHE, key=lambda k: _CACHE[k][0])
                del _CACHE[oldest_key]
            except (ValueError, KeyError):
                pass
        _CACHE[key] = (now + effective_ttl, value)
    return value



def build_snapshot_from_cache() -> dict:
    """In-process snapshot of cached widget data for the agent system prompt.

    WHY this exists: dashboard_snapshot_async previously HTTP-called itself for
    the same data already in _CACHE. The loopback HTTP roundtrip (~60-100 ms)
    was the dominant non-Anthropic latency in /chat. Reading _CACHE directly
    cuts it to a dict lookup (~0 ms).

    Cache keys confirmed against _cached() call sites in this file:
      anki_stats  -> /widgets/anki (key="anki_stats", ttl=30s)
      calendar    -> /widgets/calendar (key="calendar", ttl=600s)
      email       -> /widgets/email default (key="email::::", ttl=60s)
      spotify     -> /widgets/spotify is a live composite; use "spotify_now_web"
                     (ttl=5s) as best-effort. Absent in desktop-only mode.

    Returns dict of hot keys only. Empty dict = all cold, caller uses HTTP path.
    """
    now = time.time()
    out: dict = {}

    anki_entry = _CACHE.get("anki_stats")
    if anki_entry and anki_entry[0] > now:
        out["anki_stats"] = anki_entry[1]

    cal_entry = _CACHE.get("calendar")
    if cal_entry and cal_entry[0] > now:
        out["calendar"] = cal_entry[1]

    # Default email key: folder="" account="" gives "email::::"
    email_entry = _CACHE.get("email::::")
    if email_entry and email_entry[0] > now:
        out["email"] = email_entry[1]

    # Spotify: composite endpoint has no single _cached() key. Use
    # "spotify_now_web" (Web API path, 5s TTL) as best-effort.
    # Desktop-only users will get {} here, which _format_snapshot turns into
    # "Spotify: not running." -- identical to the HTTP fallback output.
    spotify_entry = _CACHE.get("spotify_now_web")
    if spotify_entry and spotify_entry[0] > now and spotify_entry[1]:
        raw = spotify_entry[1]
        out["spotify"] = {
            "available": True,
            "track": {
                "title": raw.get("title") or raw.get("name"),
                "name": raw.get("name") or raw.get("title"),
                "is_playing": raw.get("is_playing", False),
            },
        }

    return out


# ── Anki ──────────────────────────────────────────────────────────────────────

@router.get("/widgets/anki")
def anki_stats():
    def _compute():
        try:
            # Six queries in one batched invoke (AnkiConnect runs them
            # sequentially server-side, but we save 5 HTTP roundtrips).
            results = anki_invoke_multi([
                {"action": "findCards", "params": {"query": "is:due"}},
                {"action": "findCards", "params": {"query": "rated:1"}},
                {"action": "findCards", "params": {"query": "is:new is:due"}},
                {"action": "findCards", "params": {"query": "is:learn"}},
                {"action": "findCards", "params": {"query": "is:suspended"}},
                {"action": "findCards", "params": {"query": "-is:suspended -is:buried"}},
            ])
            due_ids = results[0] or []
            reviewed_ids = results[1] or []
            new_ids = results[2] or []
            learn_ids = results[3] or []
            suspended_ids = results[4] or []
            available_ids = results[5] or []

            # How many UWorld-mapped cards are awaiting unsuspend? Read the
            # pre-built index without hitting Anki — instant dict read.
            suggested_count = 0
            try:
                incorrects, _ = _load_uworld_incorrect()
                if incorrects:
                    index = _load_anki_qid_index()
                    qids = {str(i.get("uworld_qid", "")) for i in incorrects if i.get("uworld_qid")}
                    suggested_count = sum(len(index.get(q, []) or []) for q in qids)
            except Exception:
                # Don't let suggestion-counting break the main widget.
                suggested_count = 0

            return {
                "due": len(due_ids),
                "reviewedToday": len(reviewed_ids),
                "newCards": len(new_ids),
                "learning": len(learn_ids),
                "suspended": len(suspended_ids),
                "available_total": len(available_ids),
                "suggested_count": suggested_count,
                "streak": _compute_streak(),
                "retention": _compute_retention(),
                "available": True,
            }
        except Exception as e:
            err = str(e)
            # Surface actionable message when AnkiConnect is unreachable
            if "connection" in err.lower() or "refused" in err.lower() or "8765" in err:
                err = "Open Anki to enable AnkiConnect (port 8765). Already open? Restart Anki and try again."
            return {"error": err, "available": False}
    return _cached("anki_stats", 30, _compute)


def _date_to_review_id(d) -> int:
    """Convert a date to the AnkiConnect cardReviews startID format.

    AnkiConnect's cardReviews uses the review timestamp in *seconds* (not ms,
    not YYYYMMDD) as startID. Passing a YYYYMMDD integer (e.g. 20260426) was
    treated as a very old timestamp (~1970) and returned all reviews ever —
    making the streak always appear as 365.
    """
    import calendar as _cal
    from datetime import datetime, timezone
    dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    return int(_cal.timegm(dt.timetuple()))


def _compute_streak() -> int:
    from datetime import date, timedelta
    today = date.today()
    # Fetch all reviews since 364 days ago in one call, then bucket by date.
    start = today - timedelta(days=364)
    start_id = _date_to_review_id(start)
    try:
        reviews = anki_invoke("cardReviews", deck="*", startID=start_id) or []
    except Exception:
        return 0
    # Build set of dates with at least one review.
    import time as _time
    reviewed_dates: set[str] = set()
    for r in reviews:
        if not isinstance(r, (list, tuple)) or len(r) < 1:
            continue
        try:
            # r[0] is review timestamp in milliseconds (Mac Anki) or seconds
            ts = int(r[0])
            # Detect ms vs s: ms timestamps are > 1e12
            secs = ts / 1000.0 if ts > 1e12 else float(ts)
            reviewed_dates.add(
                # Use module-level _datetime import — __import__ adds per-call
                # import machinery overhead and defers the import unnecessarily.
                _datetime.date.fromtimestamp(secs).isoformat()
            )
        except Exception:
            continue
    # Count consecutive days backwards from today (skip today if not done yet).
    streak = 0
    start_i = 0 if today.isoformat() in reviewed_dates else 1
    for i in range(start_i, 365):
        d = today - timedelta(days=i)
        if d.isoformat() in reviewed_dates:
            streak += 1
        else:
            break
    return streak


def _compute_retention() -> int:
    from datetime import date, timedelta
    start = date.today() - timedelta(days=30)
    start_id = _date_to_review_id(start)
    try:
        reviews = anki_invoke("cardReviews", deck="*", startID=start_id)
        if not reviews:
            return 0
        correct = sum(1 for r in reviews if len(r) > 3 and r[3] > 1)
        return round(correct / len(reviews) * 100)
    except Exception:
        return 0


# ── Study Streak (derived from Anki review history) ──────────────────────────

def _compute_study_streak_days() -> dict:
    """Aggregate Anki review history into per-day study minutes for the last
    365 days.

    AnkiConnect's `cardReviews` returns arrays shaped:
        [reviewTime_ms, cardId, usn, ease, ivl, lastIvl, factor, duration_ms, type]
    We sum index 7 (review duration ms) per local-date bucket from index 0
    (review timestamp ms). Returned `minutes` are floats rounded to 1dp.
    """
    from datetime import date, datetime, timedelta
    today = date.today()
    start = today - timedelta(days=364)
    epoch_param = _date_to_review_id(start)
    try:
        reviews = anki_invoke("cardReviews", deck="*", startID=epoch_param) or []
    except Exception as e:
        return {"days": [], "available": False, "error": str(e)}

    # Bucket review duration by local date.
    by_day: dict[str, float] = {}
    for r in reviews:
        if not isinstance(r, (list, tuple)) or len(r) < 8:
            continue
        try:
            ts_ms = int(r[0])
            dur_ms = int(r[7])
        except (TypeError, ValueError):
            continue
        if dur_ms <= 0:
            continue
        d = datetime.fromtimestamp(ts_ms / 1000.0).date()
        by_day[d.isoformat()] = by_day.get(d.isoformat(), 0.0) + dur_ms / 60000.0

    days = []
    for i in range(364, -1, -1):
        d = today - timedelta(days=i)
        key = d.isoformat()
        days.append({"date": key, "minutes": round(by_day.get(key, 0.0), 1)})
    return {"days": days, "available": True}


@router.get("/widgets/study-streak")
def study_streak_widget():
    # 30 min cache — review log changes only as user reviews; recompute is cheap
    # but the AnkiConnect call across a full year can be slow on large decks.
    return _cached("study_streak", 1800, _compute_study_streak_days, _SEM_STUDY_STREAK)


# ── Anki UWorld-suggested card unsuspension ───────────────────────────────────
# STUB: real UWorld scraper doesn't exist yet. Source list lives at
# backend/storage/uworld_stub.json — populate with scraped UWorld incorrects
# when the scraper ships.

from pathlib import Path as _Path
import json as _json

_UWORLD_STUB_PATH = _Path(__file__).resolve().parent.parent / "storage" / "uworld_stub.json"
_UWORLD_HISTORY_PATH = _Path(__file__).resolve().parent.parent / "storage" / "uworld_history.json"


def _sanitize_test_seq(items: list[dict]) -> list[dict]:
    """Null out bogus test_seq values (>40) without modifying the file.

    Legacy records have test_seq populated from the session's percentile
    (e.g. "58") — UWorld's URL routing treats those as out-of-range and
    shows the loading spinner. The frontend already handles `test_seq ==
    null` by falling back to the test-overview URL, so sanitizing at read
    time gives graceful degradation without nuking records (the prior
    "clear and re-scrape" approach lost wrongs whenever the re-scrape
    couldn't fetch every cleared test in one pass)."""
    for i in items:
        s = i.get("test_seq")
        if s in (None, ""):
            continue
        try:
            n = int(s)
        except (TypeError, ValueError):
            i["test_seq"] = None
            continue
        if n < 1 or n > 40:
            i["test_seq"] = None
        else:
            i["test_seq"] = n  # store as int for the frontend
    return items


def _load_uworld_incorrect() -> tuple[list[dict], str]:
    """Return (incorrect_items, source_label) — source is "scraped" or "stub"."""
    for path, label in ((_UWORLD_HISTORY_PATH, "scraped"), (_UWORLD_STUB_PATH, "stub")):
        try:
            with path.open() as f:
                data = _json.load(f)
            items = data.get("incorrect", []) if isinstance(data, dict) else []
            found = [i for i in items if isinstance(i, dict) and i.get("uworld_qid")]
            if found:
                return _sanitize_test_seq(found), label
        except Exception:
            continue
    return [], "stub_empty"


def _load_uworld_data() -> dict:
    """Load UWorld sessions + weak topics from storage.

    Priority:
    1. uworld_history.json — written by the real scraper (_uworld_scrape_history)
    2. uworld_stub.json   — fallback stub data (shipped with the repo)

    Both files share the same schema:
      - sessions:    list of QBankSession objects
      - weak_topics: list of {topic, score, trend}
      - incorrect:   list of {uworld_qid, uworld_topic, missed_at}
    """
    data: dict = {}
    source_label = "stub"

    # Try real scraped history first
    if _UWORLD_HISTORY_PATH.exists():
        try:
            with _UWORLD_HISTORY_PATH.open() as f:
                data = _json.load(f)
            if isinstance(data, dict) and data.get("sessions"):
                source_label = "scraped"
        except Exception:
            data = {}

    # Fall back to stub if history is empty or missing
    if not data or not (isinstance(data, dict) and data.get("sessions")):
        try:
            with _UWORLD_STUB_PATH.open() as f:
                data = _json.load(f)
            source_label = "stub"
        except Exception:
            data = {}

    sessions = data.get("sessions", []) if isinstance(data, dict) else []
    weak_topics = data.get("weak_topics", []) if isinstance(data, dict) else []

    # Derive weak_topics from incorrect list when not explicitly stored.
    if not weak_topics:
        incorrects = data.get("incorrect", []) if isinstance(data, dict) else []
        topic_counts: dict = {}
        for item in incorrects:
            topic = (item.get("uworld_topic") or "Unknown").strip()
            if topic:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
        for topic, count in topic_counts.items():
            score = max(10, 75 - (count - 1) * 15)
            weak_topics.append({"topic": topic, "score": score, "trend": "declining"})

    # Detect bogus totals written by the old stub scraper (s1=98, s2=97, …).
    # Real QBank sessions have at most 40 questions; any session with total≥80
    # is clearly bogus stub data.  Null out total/correct per-session so the
    # UI shows "—" instead of a misleading count.  score % is real and kept.
    stale_data = False
    for s in sessions:
        t = s.get("total")
        if isinstance(t, int) and t >= 80:
            s["total"] = None
            s["correct"] = None
            stale_data = True

    return {
        "sessions": sessions,
        "weak_topics": weak_topics,
        # Sanitize bogus test_seq (legacy percentile values) so the
        # frontend's per-question deep-link falls back to test-overview
        # gracefully instead of building a broken URL.
        "incorrect": _sanitize_test_seq(
            data.get("incorrect", []) if isinstance(data, dict) else []
        ),
        "available": True,
        "source": source_label,
        "scraped_at": data.get("scraped_at") if isinstance(data, dict) else None,
        "stale_data": stale_data,
    }


@router.get("/widgets/uworld")
def uworld_widget():
    """QBank performance widget data — sessions + weak topics.

    Reads from uworld_history.json (real scrape) when available,
    falls back to uworld_stub.json otherwise.
    """
    return _load_uworld_data()


@router.post("/widgets/uworld/refresh")
def uworld_refresh(request: Request, response: Response):
    """Trigger a live UWorld scrape from the logged-in browser session (default: Comet).

    Calls _uworld_scrape_history() from tools/browser.py, persists results
    to uworld_history.json, and returns the fresh payload.
    Accepts both logged-in (returns sessions) and logged-out (returns
    helpful message) as valid responses.
    Browser not running = returns logged_out state with clear message.
    """
    # no-store: POST responses must not be cached — each scrape produces fresh data.
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    import datetime as _dt
    try:
        from tools.browser import _uworld_scrape_history
        result = _uworld_scrape_history()
        # Merge with existing data format for the widget
        return {
            "available": True,
            "status": result.get("status", "ok"),
            "sessions": result.get("sessions", []),
            "weak_topics": result.get("weak_topics", []),
            "incorrect": result.get("incorrect", []),
            "incorrect_count": result.get("incorrect_count", len(result.get("incorrect", []))),
            "partial": result.get("partial", False),
            "source": result.get("source", "scraped"),
            "message": result.get("message", ""),
            "scraped_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }
    except RuntimeError as e:
        # AppleScript errors (browser not running, no window, JS disabled, etc.)
        from tools.browser import BROWSER_APP as _BA
        err_str = str(e)
        if "JavaScript from Apple Events" in err_str or "Allow JavaScript from Apple Events" in err_str:
            return {
                "available": False,
                "status": "js_disabled",
                "sessions": [],
                "weak_topics": [],
                "source": "none",
                "message": (
                    f"{_BA} has JavaScript from Apple Events disabled. "
                    f"To fix: in {_BA}, go to View > Developer > Allow JavaScript from Apple Events, "
                    f"then click Refresh."
                ),
            }
        if "Can't get application" in err_str or "AppleScript" in err_str or "browser" in err_str.lower():
            return {
                "available": True,
                "status": "logged_out",
                "sessions": [],
                "weak_topics": [],
                "source": "none",
                "message": (
                    f"{_BA} is not open or has no active window. "
                    f"Open {_BA} and log into UWorld, then click Refresh."
                ),
            }
        return {
            "available": False,
            "status": "error",
            "sessions": [],
            "weak_topics": [],
            "source": "error",
            "message": err_str,
        }
    except Exception as e:
        return {
            "available": False,
            "status": "error",
            "sessions": [],
            "weak_topics": [],
            "source": "error",
            "message": str(e),
        }


# ── UWorld deep-link navigation ──────────────────────────────────────────────

@router.post("/widgets/uworld/open-question")
def uworld_open_question(payload: dict, request: Request, response: Response):
    """Navigate the user's existing UWorld tab in Comet to the question URL.

    Why a backend endpoint instead of `window.open`? `window.open` opens a NEW
    tab — UWorld's SPA on a fresh tab loses session warmth and the user often
    sees the loading spinner / has to re-auth. By navigating the EXISTING tab
    (where authInfo is already in sessionStorage), the question loads
    instantly.

    Falls back to `open <url>` (system default browser) when no UWorld tab is
    currently open. Either way the user lands on the right page.

    POST /widgets/uworld/open-question
    {
      "url": "https://apps.uworld.com/courseapp/.../results/14842106/422970934/2"
    }
    """
    # no-store: navigation POSTs must not be cached — each call navigates a live tab.
    response.headers["Cache-Control"] = "no-store"
    # Reject cross-origin requests: combined with _uw_set_tab_url accepting any
    # URL, a missing CSRF guard would let a page on another origin navigate the
    # user's live UWorld tab to an arbitrary URL via a cross-site POST.
    _require_local_origin(request)
    import subprocess as _sp
    url = (payload or {}).get("url", "").strip()
    if not url or "uworld.com" not in url:
        return {"ok": False, "error": "missing or invalid uworld url"}

    try:
        from tools.browser import _uw_find_tab, _uw_set_tab_url
        tab = _uw_find_tab("apps.uworld.com")
        if tab is not None:
            wi, ti = tab
            _uw_set_tab_url(wi, ti, url)
            # Bring Comet to the foreground so the navigation is visible.
            try:
                from tools.browser import BROWSER_APP
                _sp.run(
                    ["osascript", "-e", f'tell application "{BROWSER_APP}" to activate'],
                    capture_output=True, timeout=3,
                )
                # Make this tab the active one in its window so the user sees
                # the navigation. AppleScript:
                #   tell window N to set active tab index to T
                _sp.run(
                    [
                        "osascript", "-e",
                        f'tell application "{BROWSER_APP}" to set active tab index of window {wi} to {ti}',
                    ],
                    capture_output=True, timeout=3,
                )
            except Exception:
                pass
            return {"ok": True, "navigated_existing_tab": True, "tab": [wi, ti]}
        # No UWorld tab open — fall back to default browser open.
        _sp.run(["open", url], timeout=10, check=False)
        return {"ok": True, "navigated_existing_tab": False}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_ANKI_QID_INDEX_PATH = _Path(__file__).resolve().parent.parent / "storage" / "anki_qid_index.json"


def _load_anki_qid_index() -> dict:
    """qid (str) → list of {card_id, front, tag} — built by /widgets/anki/build-index."""
    try:
        if _ANKI_QID_INDEX_PATH.exists():
            with _ANKI_QID_INDEX_PATH.open() as f:
                return _json.load(f)
    except Exception:
        return {}
    return {}


@router.get("/widgets/anki/suggestions")
def anki_suggestions(
    limit: int = 2000,  # raised from 250 — need all qids; 2000 covers even large backlogs
    qid_filter: str = "",  # comma-separated qids to restrict results to a specific session
):
    """Suspended AnKing cards mapped to UWorld wrong-question QIDs.

    SAFE BY DEFAULT — never queries AnkiConnect at request time.
    Reads from a pre-built `anki_qid_index.json` (built by POST /widgets/anki/build-index).

    Why: large OR-queries against `tag:#AK_…` patterns crash Anki itself
    (verified twice this session — Anki goes "Application Not Responding").
    The index is built ONCE in the background; lookups are instant dict reads.
    If the index is missing, return empty + a hint.

    qid_filter: optional comma-separated list of UWorld QIDs to restrict results
    to a specific session (e.g. "2679,17121,12027"). When provided, only cards
    matching those exact QIDs are returned — used by the QBank expand panel.
    """
    incorrects, source = _load_uworld_incorrect()
    if not incorrects:
        return {"suggestions": [], "available": True, "source": "stub_empty", "qid_count": 0}

    index = _load_anki_qid_index()

    # Sort qids by most-recently-missed first so the user sees today's
    # incorrect-questions before old ones. Was string-sorted (so "10001" <
    # "2001"), which interleaved old and new and pushed yesterday's qids
    # past the truncation cap.
    import datetime as _dt
    def _parse_missed_at(s: str) -> _dt.datetime:
        if not s:
            return _dt.datetime.min
        s = s.strip()
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
            try:
                return _dt.datetime.strptime(s[:20], fmt)
            except ValueError:
                continue
        return _dt.datetime.min

    # For each qid, find the most-recent date it was missed (a card can
    # appear in multiple sessions; treat the most recent miss as its
    # "freshness" for ordering).
    qid_latest: dict[str, _dt.datetime] = {}
    for i in incorrects:
        qid = str(i.get("uworld_qid", ""))
        if not qid:
            continue
        dt = _parse_missed_at(str(i.get("missed_at", "")))
        if qid not in qid_latest or dt > qid_latest[qid]:
            qid_latest[qid] = dt

    all_qids = sorted(
        {str(i.get("uworld_qid", "")) for i in incorrects if i.get("uworld_qid")},
        key=lambda q: (qid_latest.get(q, _dt.datetime.min), q),
        reverse=True,
    )

    # Apply optional per-session filter so the QBank expand panel can request
    # only cards relevant to the session the user just clicked, rather than
    # getting all suggestions and doing a client-side count that may truncate.
    if qid_filter:
        filter_set = {q.strip() for q in qid_filter.split(",") if q.strip()}
        qids = [q for q in all_qids if q in filter_set]
    else:
        qids = all_qids
    if not index:
        return {
            "suggestions": [],
            "available": False,
            "qid_count": len(qids),
            "error": "Anki QID index not built yet. POST /widgets/anki/build-index to populate (one-time, runs in background; safe — doesn't crash Anki).",
            "needs_index_build": True,
        }

    qid_meta = {str(i.get("uworld_qid", "")): i for i in incorrects}
    suggestions: list[dict] = []
    matched_qids = 0
    for q in qids:
        cards = index.get(q) or []
        if cards:
            matched_qids += 1
        meta = qid_meta.get(q, {})
        for card in cards:
            suggestions.append({
                "card_id": card.get("card_id"),
                "front": card.get("front", "")[:120],
                "tag": card.get("tag", ""),
                "uworld_qid": q,
                "uworld_topic": meta.get("uworld_topic", "") or meta.get("uworld_system", ""),
                "uworld_topic_name": meta.get("uworld_topic_name", ""),
                "uworld_system": meta.get("uworld_system", ""),
                "missed_at": meta.get("missed_at", ""),
            })
            if len(suggestions) >= limit:
                break
        if len(suggestions) >= limit:
            break

    return {
        "suggestions": suggestions,
        "available": True,
        "source": source,
        "qid_count": len(qids),
        "matched_qid_count": matched_qids,
        "index_size": len(index),
        "index_built_at": index.get("__built_at__") if isinstance(index, dict) else None,
    }


_ANKI_INDEX_BUILD_STATE: dict = {"running": False, "progress": 0, "total": 0, "started_at": None, "error": None}
_ANKI_BUILD_LOCK = threading.Lock()


@router.post("/widgets/anki/build-index")
def anki_build_index_start(request: Request, response: Response):
    """Kick off a background build of the QID → cards index.

    Strategy that does NOT crash Anki:
      1. ONE findCards on the AnKing UWorld root tag prefix → all suspended UWorld card IDs.
      2. cardsInfo in chunks of 100 (sequential, gentle on Anki).
      3. For each card, parse `Step::<qid>` from its tags → bucket by qid.
      4. Persist to anki_qid_index.json.

    Returns immediately with status; subsequent calls to /widgets/anki/build-index/status
    report progress. On completion, /widgets/anki/suggestions becomes instant.
    """
    # no-store: kicks off a background build; result is a one-time status token.
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    import threading

    # Acquire lock atomically around the running check + full state init so a
    # concurrent status-poll can never see running=True with stale progress/
    # total/started_at from the previous run (the window between the old
    # "running=True" set and the _run() thread's update() call).
    with _ANKI_BUILD_LOCK:
        if _ANKI_INDEX_BUILD_STATE["running"]:
            return {"status": "already_running", **_ANKI_INDEX_BUILD_STATE}
        _ANKI_INDEX_BUILD_STATE.update({
            "running": True,
            "progress": 0,
            "total": 0,
            # Use module-level _datetime import — __import__ adds per-call
            # import machinery overhead; utcnow() is called on every index build.
            "started_at": _datetime.datetime.utcnow().isoformat(),
            "error": None,
        })
    # Lock released here — state is fully consistent before the thread starts.

    def _run():
        import time as _time
        import re as _re
        # State was fully initialised inside the lock above; _run() only
        # updates progress/total as it goes and running=False at the end.
        # Resume from existing partial index if present.
        index: dict = _load_anki_qid_index()
        if "__built_at__" in index:
            del index["__built_at__"]
        already_indexed_card_ids = {
            c.get("card_id") for cards in index.values() if isinstance(cards, list) for c in cards
        }
        qid_in_tag = _re.compile(r"Step::(\d+)")

        def _persist():
            import tempfile as _tempfile, os as _os
            snapshot = dict(index)
            snapshot["__built_at__"] = _datetime.datetime.utcnow().isoformat()
            _ANKI_QID_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp file then atomically replace the target. A direct
            # open("w") + json.dump leaves a window where a crash produces a
            # zero-byte or partial file, which _load_anki_qid_index silently
            # reads as {} and loses all progress. os.replace is atomic on POSIX.
            fd, tmp = _tempfile.mkstemp(dir=_ANKI_QID_INDEX_PATH.parent, suffix=".tmp")
            try:
                with _os.fdopen(fd, "w") as f:
                    _json.dump(snapshot, f)
                _os.replace(tmp, _ANKI_QID_INDEX_PATH)
            except Exception:
                try:
                    _os.unlink(tmp)
                except OSError:
                    pass
                raise

        def _retry(action: str, **params):
            """Retry per AnkiConnect call: Anki transiently returns 'collection is
            not available' during internal DB refreshes. Backoff 2s, 4s, 8s."""
            last_err: Exception | None = None
            for attempt in range(4):
                try:
                    return anki_invoke(action, **params) or []
                except Exception as e:
                    last_err = e
                    msg = str(e).lower()
                    if "collection is not available" in msg or "timed out" in msg:
                        _time.sleep(2 ** attempt)
                        continue
                    raise
            raise last_err or RuntimeError(f"{action} failed after retries")

        try:
            # 1. Get all suspended UWorld card IDs (one cheap call).
            card_ids_all = _retry(
                "findCards",
                query="tag:#AK_Step2_v12::#UWorld::Step::* is:suspended",
            )
            # Skip cards already in the partial index.
            card_ids = [i for i in card_ids_all if i not in already_indexed_card_ids]
            with _ANKI_BUILD_LOCK:
                _ANKI_INDEX_BUILD_STATE["total"] = len(card_ids)

            # 2. Map cards → notes (one batch call, returns parallel list).
            note_ids_parallel = _retry("cardsToNotes", cards=card_ids)
            # Deduplicate notes since multiple cards share a note (front/back).
            note_to_first_card: dict = {}
            for cid, nid in zip(card_ids, note_ids_parallel):
                if nid not in note_to_first_card:
                    note_to_first_card[nid] = cid
            unique_note_ids = list(note_to_first_card.keys())
            with _ANKI_BUILD_LOCK:
                _ANKI_INDEX_BUILD_STATE["total"] = len(unique_note_ids)

            CHUNK = 100
            for i in range(0, len(unique_note_ids), CHUNK):
                chunk = unique_note_ids[i : i + CHUNK]
                # 3. notesInfo for tags + fields (chunked, gentle on Anki).
                info = _retry("notesInfo", notes=chunk)
                for note in info:
                    tags = note.get("tags", []) or []
                    qid_match = next(
                        (m.group(1) for t in tags for m in [qid_in_tag.search(t)] if m),
                        None,
                    )
                    if not qid_match:
                        continue
                    fields = note.get("fields", {}) or {}
                    front_raw = ""
                    for _, v in fields.items():
                        if isinstance(v, dict) and isinstance(v.get("value"), str):
                            front_raw = v["value"]
                            break
                    front = _re.sub(r"<[^>]+>", "", front_raw).strip()
                    primary_tag = next(
                        (t for t in tags if "Step::" not in t and "UWorld" not in t and "AK_Step" in t),
                        next((t for t in tags if "Step::" not in t), tags[0] if tags else ""),
                    )
                    index.setdefault(qid_match, []).append({
                        "card_id": note_to_first_card.get(note.get("noteId")),
                        "note_id": note.get("noteId"),
                        "front": front[:120],
                        "tag": primary_tag,
                    })
                # Guard the progress write so the status endpoint reads a
                # consistent (progress, total) pair rather than a torn update.
                with _ANKI_BUILD_LOCK:
                    _ANKI_INDEX_BUILD_STATE["progress"] = min(i + CHUNK, len(unique_note_ids))
                # Persist every 10 chunks so a crash doesn't lose work.
                if (i // CHUNK) % 10 == 9:
                    _persist()
                _time.sleep(0.1)  # be gentle to Anki
            _persist()
        except Exception as e:
            with _ANKI_BUILD_LOCK:
                _ANKI_INDEX_BUILD_STATE["error"] = str(e)
            try:
                _persist()  # keep what we have so far
            except Exception:
                pass
        finally:
            with _ANKI_BUILD_LOCK:
                _ANKI_INDEX_BUILD_STATE["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@router.get("/widgets/anki/build-index/status")
def anki_build_index_status():
    # Snapshot under lock so the status read is consistent with the background
    # thread writes — without the lock, reading progress/total as two separate
    # dict accesses can race and produce a stale or impossible percentage.
    with _ANKI_BUILD_LOCK:
        snap = dict(_ANKI_INDEX_BUILD_STATE)
    pct = round(100 * snap["progress"] / snap["total"]) if snap["total"] else 0
    index = _load_anki_qid_index()
    return {**snap, "percent": pct, "index_size": len(index)}


class AnkiUnsuspendBody(BaseModel):
    card_ids: list[int]


# NOTE: _require_local_origin is now imported from api._security to avoid
# circular imports between widgets / setup / chat / apps. See top of file.


@router.post("/widgets/anki/unsuspend")
def anki_unsuspend(body: AnkiUnsuspendBody, request: Request, response: Response):
    """Unsuspend the given Anki card IDs via AnkiConnect. Requires explicit
    click in the dashboard. Cross-site POSTs are rejected."""
    # no-store: unsuspend is a one-shot mutation; caching the response is unsafe.
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    ids = [int(x) for x in (body.card_ids or [])]
    if not ids:
        return {"unsuspended": 0, "errors": ["no card_ids provided"]}
    errors: list[str] = []
    try:
        result = anki_invoke("unsuspend", cards=ids)
        # AnkiConnect returns true/false; count treated as len(ids) on success.
        if result is True:
            return {"unsuspended": len(ids), "errors": errors}
        if result is False:
            errors.append("AnkiConnect reported one or more cards could not be unsuspended")
            return {"unsuspended": 0, "errors": errors}
        return {"unsuspended": len(ids), "errors": errors, "result": result}
    except Exception as e:
        return {"unsuspended": 0, "errors": [str(e)]}


# ── iMessage ──────────────────────────────────────────────────────────────────

@router.get("/widgets/imessage")
def imessage_widget(response: Response, include_groups: bool = True, limit: int = 25):
    # Cache-Control: 8s matches the server-side TTL — browser reuses cached
    # payload during that window and revalidates in the background via SWR.
    response.headers["Cache-Control"] = "max-age=8, stale-while-revalidate=15"
    # Group chats are now ON by default — verified via the iMessage MCP that
    # group-chat unreads (e.g. tapback "Laughed at..." in the family thread)
    # were silently dropped before. The user's complaint about "messages
    # still showing wrong ones" traced directly to this default. Pass
    # ?include_groups=false to opt out per-request if needed.
    cache_key = f"imessage::{int(include_groups)}::{limit}"

    def _compute():
        try:
            convos = get_conversations(
                limit=limit,
                messages_per_thread=15,
                include_groups=include_groups,
            )
            # Resolve handles -> Contacts.app display names server-side so every
            # consumer (widget, agent tools, future mail/call widgets) sees names,
            # not phone numbers. Falls back to the existing `contact` field if the
            # handle isn't in the address book (spam, short codes).
            #
            # CRITICAL: skip group chats. The first handle in a group is just one
            # participant; resolving it would stomp the group's display_name
            # ("OMS3s 1.0") with that participant's contact name ("Andrew Fawzy"),
            # making every group look like a 1:1. The imessage tool already
            # builds a sensible group label (display_name → participant list),
            # so groups are left alone here.
            try:
                from tools.contacts import resolve as _resolve_contact
                for c in convos:
                    if c.get("is_group"):
                        # For groups, enrich participants list AND per-message
                        # sender labels with contact-resolved names so the
                        # widget can show real names instead of phone numbers
                        # in both the row label and inside group threads.
                        parts = c.get("participants") or []
                        if parts:
                            resolved_parts: list[str] = []
                            for p in parts:
                                name = _resolve_contact(p) or p
                                resolved_parts.append(name)
                            c["participants"] = resolved_parts
                            # If the chat has no display_name set, the
                            # tool-side label was built from raw handles —
                            # rebuild it now from the resolved names so the
                            # widget shows "Alice, Bob & 3 others" properly.
                            label = (c.get("contact") or "").strip()
                            digits_only = (
                                label.replace(" ", "").replace("(", "").replace(")", "")
                                .replace("-", "").replace("+", "").replace("&", "")
                                .replace(",", "").replace("other", "")
                            )
                            looks_like_phone_label = digits_only.isdigit() and len(digits_only) >= 7
                            if looks_like_phone_label and resolved_parts:
                                n = len(resolved_parts)
                                if n <= 2:
                                    c["contact"] = " & ".join(resolved_parts)
                                else:
                                    c["contact"] = (
                                        f"{resolved_parts[0]}, {resolved_parts[1]}"
                                        f" & {n - 2} other{'s' if n - 2 != 1 else ''}"
                                    )
                        # Resolve per-message sender labels too. The tool
                        # populates sender as a formatted phone (e.g.
                        # "(551) 358-4206"); upgrade to a contact name when we
                        # can find one. Falls through to the existing phone
                        # label for unknown handles.
                        for m in c.get("messages") or []:
                            s = (m.get("sender") or "").strip()
                            if s:
                                resolved = _resolve_contact(s)
                                if resolved:
                                    m["sender"] = resolved
                        continue
                    handle = c.get("handle") or c.get("contact", "")
                    name = _resolve_contact(handle)
                    if name:
                        c["contact"] = name
            except Exception:
                pass
            total_unread = sum(c.get("unread_count", 0) for c in convos)
            return {
                "conversations": convos,
                "total_unread": total_unread,
                "count": len(convos),
                "available": True,
            }
        except PermissionError as e:
            return {"available": False, "error": str(e)}
        except Exception as e:
            return {"available": False, "error": str(e)}

    # 8s TTL — short enough that an iMessage reply the user just sent
    # shows up on the next poll, long enough to absorb burst-loads
    # from rapid widget re-renders. chat.db read is fast (~30ms) so
    # this is cheap.
    return _cached(cache_key, 8, _compute)


# ── Email (Outlook desktop first, then Graph API fallback) ────────────────────

def _compute_email(folder: str = "", account: str = ""):
    try:
        data = _outlook_inbox(limit=25, folder=folder, account=account)
        if data.get("emails"):
            return {
                "emails": data["emails"],
                "accounts": data.get("accounts", []),
                "folder": data.get("folder", "Inbox"),
                "available": True,
                "source": "outlook_desktop",
            }
    except Exception:
        pass
    # Fallback only applies when no folder was requested — Graph doesn't carry
    # the same folder structure.
    if not folder:
        try:
            from tools.outlook import run_outlook_tool as _outlook_api, is_authenticated as outlook_authed
            if outlook_authed():
                data = _outlook_api("outlook_get_emails", {"count": 15})
                return {"emails": data.get("emails", []), "available": True, "source": "graph_api"}
        except Exception:
            pass
    return {
        "available": False,
        "needs_account": True,
        "folder": folder or "Inbox",
        "error": (
            f"Outlook returned no messages for folder '{folder or 'Inbox'}'. "
            "Make sure Outlook is open, 'New Outlook' is toggled OFF, and at "
            "least one account is signed in."
        ),
    }


# ── Email body fetch (for inline preview) ────────────────────────────────────

@router.get("/widgets/email/body")
def email_body(id: str = Query(..., description="Outlook message id")):
    """Fetch the full plain-text body for one Outlook email so the dashboard
    can render an inline preview (not just the metadata snippet).

    Cached for 5 min per id — bodies are immutable, so the only reason
    they'd change is a fresh fetch from a new id. Empty/error responses
    are cached at 10s only (negative-result rule from `_cached`)."""
    msg_id = (id or "").strip()
    if not msg_id:
        return {"available": False, "error": "missing id"}

    def _compute():
        try:
            from tools.desktop_apps import _outlook_read_email
            data = _outlook_read_email(message_id=msg_id)
            if data.get("error"):
                return {"available": False, "error": data["error"]}
            return {
                "available": True,
                "id": data.get("id", msg_id),
                "subject": data.get("subject", ""),
                "sender_name": data.get("sender_name", ""),
                "sender_email": data.get("sender_email", ""),
                "received_at": data.get("received_at", ""),
                "body": data.get("body", ""),
                # html omitted — Outlook HTML can be huge and the dashboard
                # renders plain text. Add a separate ?html=true if needed.
            }
        except Exception as e:
            return {"available": False, "error": str(e)}

    return _cached(f"email_body::{msg_id}", 300, _compute)


@router.get("/widgets/email")
def email_widget(
    response: Response,
    folder: str = Query("", description="Optional mail folder name"),
    account: str = Query("", description="Optional account name/email filter"),
):
    # Cache-Control: email changes slowly; 120s browser cache prevents redundant
    # fetches from rapid widget re-renders while SWR keeps it from going stale.
    response.headers["Cache-Control"] = "max-age=120, stale-while-revalidate=240"
    # Cache per (folder, account) pair; 60s TTL.
    # Canonical default key (both empty) must match what warm_widgets and
    # briefing_widget use: "email::::".  The formula is:
    #   "email::" + folder + "::" + account  → for defaults → "email::::"
    # Truncate inputs so a malformed/long value can't flood the LRU cache.
    folder = folder[:64]
    account = account[:64]
    cache_key = "email::" + folder + "::" + account
    return _cached(cache_key, 60, lambda: _compute_email(folder=folder, account=account), _SEM_EMAIL)


def _compute_email_folders():
    try:
        from tools.desktop_apps import _outlook_folders
        data = _outlook_folders()
        if data.get("accounts"):
            return {"accounts": data["accounts"], "available": True}
        return {
            "accounts": [],
            "available": False,
            "error": data.get("error", "No Outlook accounts returned folders."),
        }
    except Exception as e:
        return {"accounts": [], "available": False, "error": str(e)}


@router.get("/widgets/email/folders")
def email_folders_endpoint():
    # 5 minutes — folder list shifts slowly and AppleScript enumeration is heavy.
    return _cached("email_folders", 300, _compute_email_folders, _SEM_EMAIL_FOLDERS)


# ── Calendar (Outlook desktop → Apple Calendar → Graph API) ──────────────────

def _compute_calendar():
    """14-day rolling window across all user calendars + rotation feed.

    Was 30 days but Calendar.app AppleScript routinely exceeds the 45s
    osascript timeout at 30 days (~80s observed for 30d, 42s for 14d).
    14d covers the dashboard's Upcoming + This Week + Briefing needs and
    fits inside the AppleScript budget.
    """
    all_events = []
    try:
        ol = _outlook_calendar(days=14)
        if ol.get("events"):
            all_events.extend(ol["events"])
    except Exception:
        pass
    try:
        ac = _calendar_events(days=14)
        if ac.get("events"):
            all_events.extend(ac["events"])
    except Exception:
        pass
    seen = set()
    deduped = []
    for e in all_events:
        k = (e.get("title", ""), e.get("start", ""))
        if k not in seen:
            seen.add(k)
            deduped.append(e)
    deduped.sort(key=lambda e: e.get("start", ""))
    if deduped:
        return {"events": deduped, "available": True, "source": "desktop"}
    try:
        from tools.outlook import run_outlook_tool as _outlook_api, is_authenticated as outlook_authed
        if outlook_authed():
            data = _outlook_api("outlook_get_calendar", {})
            return {"events": data.get("events", []), "available": True, "source": "graph_api"}
    except Exception:
        pass
    return None


@router.get("/widgets/calendar")
def calendar_widget(response: Response, start: str = "", end: str = ""):
    # Cache-Control: calendar data is expensive to fetch (30-60s AppleScript);
    # 120s browser cache absorbs repeated fetches from multiple widget renders.
    response.headers["Cache-Control"] = "max-age=120, stale-while-revalidate=240"
    # 10 min cache — Calendar.app AppleScript takes 30-60s on user's
    # 12-calendar setup. Pass _SEM_CALENDAR so concurrent warm + read requests
    # don't both fire AppleScript in parallel; the semaphore's cold-start
    # fallback in _cached ensures the first caller still gets data even if
    # the semaphore can't be acquired immediately.
    cached = _cached("calendar", 600, _compute_calendar, _SEM_CALENDAR)
    if cached:
        # Apply date-range filtering when both start and end are provided.
        # Events now carry ISO 8601 in `start` (parsed from AppleScript human
        # strings inside _calendar_events). Older cache entries may still hold
        # human-formatted strings — try `start` first, then fall back to
        # legacy aliases. Events that fail to parse pass through.
        if start and end:
            try:
                start_dt = datetime.fromisoformat(start.rstrip("Z"))
                end_dt = datetime.fromisoformat(end.rstrip("Z"))
                events = cached.get("events", [])
                filtered = []
                for e in events:
                    iso = e.get("start") or e.get("start_iso") or e.get("start_dt") or ""
                    if not iso:
                        # No parseable ISO field — include the event to avoid
                        # silently dropping things we can't classify.
                        filtered.append(e)
                        continue
                    try:
                        ev_dt = datetime.fromisoformat(iso.rstrip("Z"))
                        if start_dt <= ev_dt <= end_dt:
                            filtered.append(e)
                    except Exception:
                        filtered.append(e)
                return {**cached, "events": filtered}
            except Exception:
                # Unparseable start/end — return full payload rather than 422.
                pass
        return cached

    return {
        "available": False,
        "error": "No calendar source available. Open Outlook or Calendar app.",
    }


# ── Triage (chief-of-staff: email + iMessage classification) ─────────────────

@router.get("/widgets/triage")
def triage_widget(response: Response):
    """Chief-of-staff 4-tier triage of unread email + iMessage. 5-min cache.

    WHY read-only GET with no CSRF guard: this endpoint only reads data and
    calls the Anthropic API — it never mutates local state. _require_local_origin
    is only needed on mutating endpoints (POST/PUT/DELETE).
    """
    # Cache-Control: triage calls Anthropic (expensive); 5-min browser cache
    # matches the server-side TTL and prevents redundant Opus calls on tab focus.
    response.headers["Cache-Control"] = "max-age=300, stale-while-revalidate=600"
    def _compute():
        # Fetch payloads using the same functions the existing email/iMessage
        # endpoints use so we reuse any warm cache entries and avoid duplicate
        # AppleScript calls running concurrently.
        email_data = _compute_email()
        try:
            from tools.imessage import get_conversations as _get_convos
            imessage_data = {
                "conversations": _get_convos(
                    limit=25, messages_per_thread=10, include_groups=True
                )
            }
        except Exception as e:
            imessage_data = {"conversations": [], "error": str(e)[:200]}

        # WHY local import: avoids a circular-import risk at module load time.
        # agent.triage imports agent.jarvis which imports tools — keeping the
        # import deferred to call time is the safe pattern already used by
        # other endpoints (e.g. tools.outlook, tools.desktop_apps).
        from agent.triage import compute_triage
        try:
            return compute_triage(email_data, imessage_data)
        except Exception as e:
            # Surface a typed error object so the frontend can render ErrorState
            # instead of an unhandled blank widget.
            return {
                "error": str(e)[:200],
                "skip_count": 0,
                "skip_senders": [],
                "info_only": [],
                "meeting_info": [],
                "action_required": [],
                "stale": [],
            }

    # 300s = 5 minutes. Opus calls are expensive (~$0.015/call); caching keeps
    # cost manageable while keeping the widget reasonably fresh for an MS3's pace.
    return _cached("triage", 300, _compute)


# ── On-demand warmup ──────────────────────────────────────────────────────────

@router.post("/widgets/warm")
def warm_widgets(request: Request, response: Response):
    """Fire all slow AppleScript compute functions in the background so caches
    are hot before the user's first widget interaction.

    Returns immediately with a list of which caches were already warm and
    which were triggered. Safe to call multiple times — semaphores prevent
    duplicate in-flight AppleScript invocations.
    """
    # no-store: warmup result is a one-time status snapshot, not cacheable data.
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    import concurrent.futures

    tasks = {
        "calendar": ("calendar", 600, _compute_calendar, _SEM_CALENDAR),
        "email": ("email::::", 60, lambda: _compute_email(), _SEM_EMAIL),
        "email_folders": ("email_folders", 300, _compute_email_folders, _SEM_EMAIL_FOLDERS),
        "study_streak": ("study_streak", 1800, _compute_study_streak_days, _SEM_STUDY_STREAK),
    }

    now = time.time()
    already_warm = []
    triggered = []

    def _run(cache_key, ttl, compute_fn, sem):
        _cached(cache_key, ttl, compute_fn, sem)

    futures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for name, (cache_key, ttl, compute_fn, sem) in tasks.items():
            entry = _CACHE.get(cache_key)
            if entry and entry[0] > now:
                already_warm.append(name)
            else:
                triggered.append(name)
                futures[name] = pool.submit(_run, cache_key, ttl, compute_fn, sem)
        # Wait up to 35s total; caller gets a response as soon as they all finish
        # or timeout — whichever comes first.
        concurrent.futures.wait(futures.values(), timeout=35)

    return {"already_warm": already_warm, "triggered": triggered}


# ── Spotify ───────────────────────────────────────────────────────────────────
#
# Architecture:
#   - "Now playing" (track/artist/album/progress/volume) comes from AppleScript
#     against the Spotify desktop app. No auth needed; always preferred.
#   - Album art: try AppleScript `artwork url`, then Web API, then og:image
#     scrape of the track's Spotify page.
#   - Queue, playlists, recents, search: require Web API (OAuth). Returned as
#     null when not authed so UI can show a "Connect Spotify" button.
#   - Playback controls (play/pause/next/prev/URI play) use AppleScript (free).

def _spotify_web_ok() -> bool:
    try:
        from tools.spotify import is_authenticated
        return bool(is_authenticated())
    except Exception:
        return False


def _spotify_album_art(now: dict) -> str | None:
    """Resolve album art in order: AppleScript artwork → Web API → og:image scrape."""
    art = now.get("artwork_url")
    if art:
        return art
    if _spotify_web_ok():
        try:
            from tools.spotify import get_now_playing as _wp
            wp = _wp()
            if wp and wp.get("album_art"):
                return wp["album_art"]
        except Exception:
            pass
    uri = now.get("uri")
    if uri:
        scraped = _spotify_fetch_artwork_from_url(uri)
        if scraped:
            return scraped
    return None


def _spotify_playlists_cached():
    if not _spotify_web_ok():
        return None
    def _compute():
        from tools.spotify import get_playlists
        return get_playlists(limit=20)
    # 300s (5 min) — playlists change rarely; keeping them at 60s contributed
    # unnecessary per-minute requests to the already rate-limited Spotify quota.
    return _cached("spotify_playlists", 300, _compute)


def _spotify_recents_cached():
    if not _spotify_web_ok():
        return None
    def _compute():
        from tools.spotify import get_recently_played
        return get_recently_played(limit=10)
    return _cached("spotify_recents", 60, _compute)


def _spotify_recent_playlists_cached():
    """Return recently-played playlists (deduped by URI) or None when not authed."""
    if not _spotify_web_ok():
        return None
    def _compute():
        from tools.spotify import get_recently_played_playlists
        return get_recently_played_playlists(limit=8)
    return _cached("spotify_recent_playlists", 120, _compute)


def _spotify_queue_cached():
    if not _spotify_web_ok():
        return None
    def _compute():
        try:
            from tools.spotify import get_queue
            return get_queue()
        except Exception:
            return None
    return _cached("spotify_queue", 8, _compute)


@router.get("/widgets/spotify")
def spotify_widget(request: Request, response: Response):
    # Cache-Control: short TTL so the progress bar stays accurate without
    # hammering AppleScript on every animation frame. stale-while-revalidate
    # lets the browser show stale data instantly while revalidating in the background.
    response.headers["Cache-Control"] = "max-age=5, stale-while-revalidate=10"
    # 1) Now playing from AppleScript (free, no auth).
    now = {}
    try:
        now = _spotify_now_playing() or {}
    except Exception:
        now = {}

    web_ok = _spotify_web_ok()
    track_block = None
    album_art = None

    if now.get("track") or now.get("state") in ("playing", "paused"):
        duration_ms = now.get("duration_ms", 0) or 0
        progress_ms = int((now.get("position_s", 0) or 0) * 1000)
        album_art = _spotify_album_art(now)
        track_block = {
            "title": now.get("track"),
            "name": now.get("track"),  # alias for older clients
            "artist": now.get("artist"),
            "album": now.get("album"),
            "duration_ms": duration_ms,
            "progress_ms": progress_ms,
            "progress": (progress_ms / duration_ms) if duration_ms else 0,
            "is_playing": now.get("state") == "playing",
            "volume": now.get("volume"),
            "uri": now.get("uri"),
            "album_art": album_art,
        }
    elif web_ok:
        # Spotify desktop app not running → try Web API now-playing.
        # Cached at 5s so rapid-fire polls (HMR refresh, multi-tab) don't fan
        # out a fresh get_now_playing() call on every tick.
        def _compute_now_web():
            try:
                from tools.spotify import get_now_playing
                wp = get_now_playing()
                if wp:
                    return {**wp, "name": wp.get("title")}
            except Exception:
                pass
            return None
        cached_now = _cached("spotify_now_web", 5, _compute_now_web)
        if cached_now:
            track_block = cached_now
            album_art = cached_now.get("album_art")

    # Cached helpers may return RATE_LIMITED_SENTINEL when Spotify has 429'd
    # us; FastAPI's JSON serializer can't encode a bare `object()`. Collapse
    # the sentinel to [] here — this endpoint doesn't surface a banner (the
    # /widgets/spotify/home endpoint owns that UX), so [] is the right
    # fallthrough for the now-playing widget.
    # _RATE_LIMITED_SENTINEL is imported at module level (avoids hot-path cost).
    def _safe(v):
        if v is _RATE_LIMITED_SENTINEL:
            return []
        return v
    return {
        "available": bool(track_block) or web_ok,
        "source": "desktop" if now.get("track") else ("web_api" if web_ok else None),
        "track": track_block,
        "album_art_url": album_art,
        "web_api_connected": web_ok,
        # Derive base URL from the live request so the URL works across dev/
        # prod environments instead of hardcoding 127.0.0.1:8000.
        "auth_url": None if web_ok else str(request.base_url).rstrip("/") + "/auth/spotify",
        "queue": _safe(_spotify_queue_cached()),
        "playlists": _safe(_spotify_playlists_cached()),
        "recently_played": _safe(_spotify_recents_cached()),
    }


@router.get("/widgets/spotify/home")
def spotify_home():
    def _compute():
        if not _spotify_web_ok():
            return {"available": False, "error": "Spotify Web API not connected"}
        from tools.spotify import (
            get_top_tracks, get_top_artists, RATE_LIMITED_SENTINEL,
            rate_limit_status,
        )
        # Probe each list, collapsing the breaker sentinel into [] but
        # tracking it so we can surface a single clear UI message.
        def _norm(v):
            return [] if v is RATE_LIMITED_SENTINEL else (v or [])
        top_tracks = _norm(get_top_tracks("short_term", 8))
        top_artists = _norm(get_top_artists("short_term", 8))
        recent_playlists = _norm(_spotify_recent_playlists_cached())
        playlists = _norm(_spotify_playlists_cached())
        rls = rate_limit_status()
        return {
            "available": True,
            "top_tracks": top_tracks,
            "top_artists": top_artists,
            # recently_played is now playlist-only (user feedback: don't show songs)
            "recently_played": recent_playlists,
            "playlists": playlists,
            # Rate-limit hints — let the UI render a banner instead of leaving
            # the user staring at four empty sections wondering what broke.
            "rate_limited": rls["rate_limited"],
            "rate_limit_retry_in_seconds": rls["retry_in_seconds"],
            "rate_limit_message": (
                f"Spotify is rate-limiting Jarvis right now (about "
                f"{max(1, rls['retry_in_seconds']//60)} min until retry). "
                f"This usually clears on its own; no action needed."
                if rls["rate_limited"] else ""
            ),
        }
    return _cached("spotify_home", 60, _compute)


# ── Spotify control endpoints ─────────────────────────────────────────────────

class SpotifySearchBody(BaseModel):
    query: str


class SpotifyPlayBody(BaseModel):
    uri: str


class SpotifyControlBody(BaseModel):
    action: str  # play | pause | next | prev | toggle


class SpotifyVolumeBody(BaseModel):
    volume: int


@router.post("/widgets/spotify/search")
def spotify_search(body: SpotifySearchBody, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    if not _spotify_web_ok():
        return {
            "results": None,
            "error": "Spotify Web API not connected. Visit /auth/spotify to connect.",
            # Derive base URL from request so the URL works across environments.
            "auth_url": str(request.base_url).rstrip("/") + "/auth/spotify",
        }
    try:
        from tools.spotify import search_tracks
        results = search_tracks(body.query, limit=10) or []
        return {"results": results}
    except Exception as e:
        return {"results": None, "error": str(e)}


@router.post("/widgets/spotify/play")
def spotify_play(body: SpotifyPlayBody, request: Request, response: Response):
    """Play a Spotify URI via AppleScript (requires Spotify desktop app open)."""
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    data = _spotify_play_uri(body.uri)
    if "error" in data:
        return {"ok": False, "error": data["error"]}
    return {"ok": True, "now_playing": data.get("track")}


@router.post("/widgets/spotify/control")
def spotify_control(body: SpotifyControlBody, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    action_map = {
        "play": "play",
        "pause": "pause",
        "toggle": "playpause",
        "playpause": "playpause",
        "next": "next track",
        "prev": "previous track",
        "previous": "previous track",
    }
    cmd = action_map.get(body.action.lower())
    if not cmd:
        return {"ok": False, "error": f"Unknown action: {body.action}"}
    data = _spotify_cmd(cmd)
    if "error" in data:
        return {"ok": False, "error": data["error"]}
    return {"ok": True, "state": data.get("state"), "track": data.get("track")}


class SpotifyContextBody(BaseModel):
    context_uri: str  # spotify:playlist:... or spotify:album:...


@router.post("/widgets/spotify/play-context")
def spotify_play_context(body: SpotifyContextBody, request: Request, response: Response):
    """Play a Spotify context (playlist/album) via Web API.

    Preferred for playlists — uses PUT /v1/me/player/play with context_uri
    so the whole playlist plays in order, not just a single track.
    """
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    if not _spotify_web_ok():
        return {"ok": False, "error": "Spotify Web API not connected"}
    from tools.spotify import play_context_uri
    return play_context_uri(body.context_uri)


@router.post("/widgets/spotify/volume")
def spotify_volume(body: SpotifyVolumeBody, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    _require_local_origin(request)
    v = max(0, min(100, int(body.volume)))
    data = _spotify_volume(v)
    if "error" in data:
        return {"ok": False, "error": data["error"]}
    return {"ok": True, "volume": v}


# ── Apple Calendar standalone endpoint ────────────────────────────────────────

@router.get("/widgets/apple-calendar")
def apple_calendar_widget():
    try:
        data = _calendar_events(days=30)
        if data.get("error"):
            return {"available": False, "error": data["error"]}
        events = data.get("events", [])
        return {"events": events, "available": True}
    except Exception as e:
        return {"available": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Ported from agent-lab: briefing aggregator + NBME tracker
# ─────────────────────────────────────────────────────────────────────────────

import secrets
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from storage import CACHE_DIR, read_json, write_json


class NBMEScoreIn(BaseModel):
    exam_name: str = Field(..., min_length=1, max_length=80)
    date_taken: str = Field(..., min_length=8, max_length=10)  # YYYY-MM-DD
    raw_score: float = Field(..., ge=0, le=800)
    percentile: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = Field(None, max_length=2000)


class NBMEScore(NBMEScoreIn):
    id: str


NBME_STORE = CACHE_DIR / "nbme_scores.json"


def _format_briefing_time(iso: str) -> str:
    """Format an ISO datetime as '7:00 AM' in local time. Returns '' if unparsable."""
    if not iso or len(iso) < 16:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        # Convert tz-aware datetimes to local time before formatting.
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
    except Exception:
        try:
            dt = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return ""
    # %-I is a GNU libc extension that renders as a literal on some macOS builds.
    hour = dt.strftime("%I").lstrip("0") or "0"
    return f"{hour}:{dt.strftime('%M %p')}"


# Folders that are noise in a morning briefing — Inbox is rolled into
# `unread_mail`, the rest are infra/cleanup buckets the user doesn't read.
_BRIEFING_HIDDEN: frozenset[str] = frozenset({
    "Inbox",
    "Drafts",
    "Sent Items",
    "Deleted Items",
    "Junk Email",
    "Junk E-mail",
    "Clutter",
    "Conversation History",
    "RSS Feeds",
    "Sync Issues",
    "Outbox",
    "Subscribed Public Folders",
    "Archive",  # archived = read by definition
})


# ── Morning briefing ──────────────────────────────────────────────────────────

@router.get("/widgets/briefing")
def briefing_widget(response: Response):
    """
    Aggregates Anki stats + today's calendar events + unread mail count
    + folder-level mail breakdown + iMessage unread + Spotify now-playing
    + NBME score trend / next-exam countdown.

    Each fetcher runs in a ThreadPoolExecutor with a per-task 3s timeout so
    one slow integration can't block the whole briefing.
    """
    # Cache-Control: briefing is the most expensive endpoint (parallel Anthropic
    # calls); 60s browser cache prevents redundant fetches from tab focus events.
    response.headers["Cache-Control"] = "max-age=60, stale-while-revalidate=120"
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    now = datetime.now()
    hour = now.hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 18:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    errors: list[str] = []

    def fetch_anki():
        try:
            due_ids = anki_invoke("findCards", query="is:due")
            try:
                streak_days = _compute_streak()
            except Exception:
                streak_days = None
            out = {"due": len(due_ids)}
            if streak_days is not None:
                out["streak_days"] = streak_days
            return out
        except Exception as e:
            errors.append(f"anki: {e}")
            return None

    def fetch_events():
        # Use cached /widgets/calendar result when fresh — avoids 60s AppleScript.
        try:
            cached = _CACHE.get("calendar")
            raw = []
            if cached and cached[0] > time.time():
                _, payload = cached
                raw = payload.get("events", []) if isinstance(payload, dict) else []
            today = now.date().isoformat()
            filtered = [e for e in raw if isinstance(e.get("start"), str) and e["start"].startswith(today)]
            filtered.sort(key=lambda e: e.get("start", ""))
            top = filtered[:3]
            events = [
                {
                    "time": _format_briefing_time(e.get("start", "")),
                    "title": e.get("title") or "",
                    "location": e.get("location") or "",
                }
                for e in top
            ]
            # next_event with relative-time highlight if ≤2h out and still in the future.
            next_event = None
            for e in filtered:
                start_iso = e.get("start") or ""
                try:
                    dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                    # Convert to local naive datetime so the delta comparison
                    # with local `now` is correct. Without this, UTC events
                    # were compared against local time causing off-by-offset.
                    if dt.tzinfo is not None:
                        from datetime import timezone as _tz
                        dt = dt.astimezone().replace(tzinfo=None)
                except Exception:
                    continue
                delta = (dt - now).total_seconds() / 60.0
                if delta < -1:
                    continue
                in_minutes = int(round(delta))
                next_event = {
                    "in_minutes": in_minutes if in_minutes <= 120 else None,
                    "title": e.get("title") or "",
                    "location": e.get("location") or "",
                    "time": _format_briefing_time(start_iso),
                }
                break
            return {"events": events, "next_event": next_event}
        except Exception as e:
            errors.append(f"calendar: {e}")
            return None

    def fetch_unread():
        # Cache key for the default Inbox is `email::::` (folder + account
        # both empty). The OLD `_CACHE.get("email")` lookup was silently
        # always None — this used to be a no-op field. Backend stores
        # email payloads under the per-(folder, account) key from
        # email_widget(), so we look that up explicitly. Backend exposes
        # `read` (not `is_read`) on each email — fix that key too.
        try:
            cached = _CACHE.get("email::::")
            if cached:
                _, payload = cached
                if isinstance(payload, dict):
                    emails = payload.get("emails") or []
                    return sum(
                        1 for e in emails
                        if not e.get("read", e.get("is_read", True))
                    )
            return None
        except Exception as e:
            errors.append(f"unread: {e}")
            return None

    def fetch_folders():
        try:
            # Pass the semaphore so concurrent briefing requests don't stack
            # parallel Outlook AppleScript folder enumerations — same pattern
            # used by email_folders_endpoint and the warmup map at line ~1185.
            data = _cached("email_folders", 300, _compute_email_folders, _SEM_EMAIL_FOLDERS)
            if not isinstance(data, dict) or not data.get("available"):
                return None
            rows: list[dict] = []
            for acct in data.get("accounts") or []:
                for f in acct.get("folders") or []:
                    name = (f.get("name") or "").strip()
                    unread = int(f.get("unread") or 0)
                    if unread > 0 and name and name not in _BRIEFING_HIDDEN:
                        rows.append({"name": name, "unread": unread})
            rows.sort(key=lambda r: r["unread"], reverse=True)
            return rows[:3]
        except Exception as e:
            errors.append(f"folders: {e}")
            return None

    def fetch_messages():
        try:
            # Piggyback on P1's 30s imessage cache when available.
            # Key format is "imessage::{int(include_groups)}::{limit}"; the widget
            # always passes include_groups=True so the int is 1, not 0.
            cached_im = _CACHE.get("imessage::1::25")
            if cached_im and cached_im[0] > time.time():
                convos = (cached_im[1] or {}).get("conversations") or []
            else:
                convos = get_conversations(limit=25, messages_per_thread=1, include_groups=True)
            # Sum unread counts only — no contact resolution needed here
            # (the iMessage widget already resolves names; briefing only needs a count).
            count = sum(int(c.get("unread_count") or 0) for c in convos)
            return count
        except Exception as e:
            errors.append(f"imessage: {e}")
            return None

    _NP_SCRIPT = """
tell application "Spotify"
    try
        if player state is playing or player state is paused then
            return (name of current track) & "|||" & (artist of current track) & "|||" & (player state as string)
        else
            return "|||stopped"
        end if
    on error
        return "|||stopped"
    end try
end tell
"""

    def fetch_now_playing():
        # Use _osascript with a 2s timeout so a closed Spotify app doesn't
        # stall the briefing. The full _spotify_now_playing() uses the 15s
        # default which always exceeds the briefing's per-fetcher budget.
        # Wrap in a 15s cache so rapid briefing refreshes skip the osascript.
        def _np_compute():
            try:
                result = _osascript(_NP_SCRIPT, timeout=2)
                out = (result.get("output") or "").strip()
                if not out:
                    return None
                parts = out.split("|||")
                title = parts[0].strip() if parts else ""
                artist = parts[1].strip() if len(parts) > 1 else ""
                state = parts[2].strip() if len(parts) > 2 else ""
                if not title or state not in ("playing", "paused"):
                    return None
                return {"title": title, "artist": artist}
            except Exception:
                return None
        try:
            return _cached("briefing_now_playing", 15, _np_compute)
        except Exception as e:
            errors.append(f"spotify: {e}")
            return None

    def fetch_nbme():
        try:
            from datetime import date as _date
            scores = _load_nbme()
            if not scores:
                return None
            past = []
            future = []
            today = _date.today()
            for s in scores:
                d = s.get("date_taken") or ""
                try:
                    sd = _date.fromisoformat(d)
                except Exception:
                    continue
                if sd <= today:
                    past.append((sd, s))
                else:
                    future.append((sd, s))
            past.sort(key=lambda t: t[0], reverse=True)
            future.sort(key=lambda t: t[0])
            out: dict = {}
            if past:
                latest = past[0][1]
                out["latest_score"] = latest.get("raw_score")
                out["latest_pct"] = latest.get("percentile")
                if len(past) >= 2:
                    prev = past[1][1]
                    try:
                        out["delta"] = float(latest.get("raw_score")) - float(prev.get("raw_score"))
                    except Exception:
                        pass
            if future:
                out["days_until_next"] = (future[0][0] - today).days
                out["next_exam"] = future[0][1].get("exam_name")
            return out or None
        except Exception as e:
            errors.append(f"nbme: {e}")
            return None

    def fetch_important_unread():
        """Pick the top N unread emails by `_score_email`. Briefing is supposed
        to surface only emails that ACTUALLY matter — newsletters, promotions,
        and digest mailers are penalized; VIP-domain mail and action-word
        subjects bubble up. Source: cached email widget payload (avoids a
        second AppleScript round-trip).

        After the heuristic sort, the top-20 candidates are passed to Claude
        Haiku for an actionability rerank. When two heuristic scores are within
        10 points of each other, the LLM score breaks the tie. If the LLM call
        fails the function silently falls back to heuristic-only ordering.
        """
        try:
            cached = _CACHE.get("email::::")
            if not cached:
                return []
            _, payload = cached
            emails = (payload or {}).get("emails") or []
            unread = [
                e for e in emails
                if not e.get("read", e.get("is_read", True))
            ]

            # Pre-compute scores once so we don't call _score_email twice per item.
            scored_unread: list[tuple[int, list[str], dict]] = []
            for e in unread:
                sc, rs = _score_email(e)
                scored_unread.append((sc, rs, e))

            # Sort heuristically: higher score first, then newer date as tiebreak.
            scored_unread.sort(key=lambda t: (-t[0], t[2].get("date") or ""))

            # Take the top-20 for the LLM rerank pass.
            candidates = scored_unread[:20]

            # --- LLM rerank (best-effort; silently skipped on any error) -------
            llm_scores: dict[str, int] = {}
            try:
                raw_key = (
                    _os.getenv("ANTHROPIC_API_KEY")
                    or _os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
                    or ""
                )
                if raw_key:
                    if raw_key.startswith("sk-ant-oat"):
                        _haiku_client = _anthropic.Anthropic(
                            auth_token=raw_key,
                            default_headers={"anthropic-beta": "oauth-2025-04-20"},
                        )
                    else:
                        _haiku_client = _anthropic.Anthropic(api_key=raw_key)

                    # Build a compact list so the prompt stays small.
                    items_for_llm = []
                    for _sc, _rs, _e in candidates:
                        items_for_llm.append({
                            "id": _e.get("id") or "",
                            "from": (_e.get("from") or "")[:60],
                            "subject": (_e.get("subject") or "")[:80],
                        })

                    import json as _json_rerank
                    prompt = (
                        "User is a med student at Cooper / Rowan in pre-clinical year. "
                        "Score each email 0-100 by genuine actionability — urgent, "
                        "course-related, clinical, time-sensitive. "
                        'Return JSON: {"ranks": [{"id": "<id>", "actionability": 0-100}]}\n\n'
                        f"Emails:\n{_json_rerank.dumps(items_for_llm)}"
                    )
                    resp = _haiku_client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=512,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    raw_text = (resp.content[0].text if resp.content else "")
                    # Strip markdown fences in case the model wraps its JSON.
                    raw_text = _re.sub(r"```[a-z]*", "", raw_text).strip()
                    parsed = _json_rerank.loads(raw_text)
                    for rank_item in parsed.get("ranks", []):
                        _id = str(rank_item.get("id") or "")
                        _act = int(rank_item.get("actionability", 0))
                        llm_scores[_id] = _act
            except Exception:
                # LLM failure is non-fatal — heuristic ordering stands.
                pass

            # Re-sort with LLM as tiebreaker: when two heuristic scores differ
            # by ≤10 the LLM actionability score determines the relative order.
            def _sort_key(item: tuple[int, list[str], dict]):
                heuristic, _, e = item
                eid = str(e.get("id") or "")
                llm = llm_scores.get(eid, 50)
                # Scale llm 0-100 → 0-9 so it only breaks ties within ±10 band.
                return (-heuristic, -(llm // 10))

            if llm_scores:
                candidates.sort(key=_sort_key)

            top = candidates[:5]
            out = []
            for sc, rs, e in top:
                # Strip the Outlook display-name wrapping so the line stays
                # readable in the briefing card.
                from_field = (e.get("from") or "").strip()
                subj = (e.get("subject") or "").strip()
                folder = (e.get("folder") or "").strip() or None
                out.append({
                    "id": e.get("id"),
                    "subject": subj[:80],
                    "from": from_field[:60],
                    "folder": folder,
                    "score": sc,
                    "score_reason": "; ".join(rs),
                    "date": e.get("date"),
                })
            return out
        except Exception as e:
            errors.append(f"important_unread: {e}")
            return []

    def fetch_todos():
        try:
            items = _load_todos()
            pending = [t for t in items if not t.get("done")]
            # Sort: items with a due date first (soonest first), then undated,
            # then most-recently-created.
            def _key(t):
                due = t.get("due") or ""
                created = t.get("created_at") or ""
                # We want items with `due` to come before those without;
                # within "has due", sort by date ascending.
                return (0 if due else 1, due, created)
            pending.sort(key=_key)
            return pending[:6]
        except Exception as e:
            errors.append(f"todos: {e}")
            return []

    fetchers = {
        "anki": fetch_anki,
        "events": fetch_events,
        "unread": fetch_unread,
        "folders": fetch_folders,
        "messages": fetch_messages,
        "now_playing": fetch_now_playing,
        "nbme": fetch_nbme,
        "important_unread": fetch_important_unread,
        "todos": fetch_todos,
    }
    results: dict = {}
    with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
        futures = {name: pool.submit(fn) for name, fn in fetchers.items()}
        for name, fut in futures.items():
            timeout = 6 if name in ("anki", "events", "unread", "now_playing", "messages") else 3
            try:
                results[name] = fut.result(timeout=timeout)
            except FuturesTimeout:
                errors.append(f"{name}: timeout")
                results[name] = None
            except Exception as e:
                errors.append(f"{name}: {e}")
                results[name] = None

    events_payload = results.get("events") or {}
    if isinstance(events_payload, dict):
        events_today = events_payload.get("events")
        next_event = events_payload.get("next_event")
    else:
        events_today = events_payload
        next_event = None

    return {
        "greeting": greeting,
        "now": now.isoformat(timespec="seconds"),
        # New focused fields — used by the rewritten briefing widget. These
        # are the only sections the user wants to see in the dashboard
        # summary. Other widgets handle iMessage / Spotify / NBME details.
        "important_unread": results.get("important_unread") or [],
        "todos": results.get("todos") or [],
        # Legacy fields — kept for back-compat with anything else still
        # consuming /widgets/briefing (agent tools, future surfaces).
        "anki": results.get("anki"),
        "events_today": events_today,
        "next_event": next_event,
        "unread_mail": results.get("unread"),
        "mail_folders": results.get("folders"),
        "unread_messages": results.get("messages"),
        "now_playing": results.get("now_playing"),
        "nbme": results.get("nbme"),
        "errors": errors,
    }


# ── NBME tracker ──────────────────────────────────────────────────────────────

def _load_nbme() -> list[dict]:
    data = read_json(NBME_STORE, default=[])
    if not isinstance(data, list):
        return []
    return data


def _save_nbme(scores: list[dict]) -> None:
    write_json(NBME_STORE, scores)


@router.get("/widgets/nbme")
def nbme_widget():
    scores = _load_nbme()
    scores.sort(key=lambda s: s.get("date_taken", ""), reverse=True)
    return {"scores": scores, "available": True}


@router.post("/widgets/nbme")
def nbme_create(payload: NBMEScoreIn, request: Request):
    _require_local_origin(request)
    scores = _load_nbme()
    new_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}"
    record = {"id": new_id, **payload.model_dump()}
    scores.append(record)
    _save_nbme(scores)
    return record


@router.delete("/widgets/nbme/{score_id}")
def nbme_delete(score_id: str, request: Request):
    _require_local_origin(request)
    scores = _load_nbme()
    remaining = [s for s in scores if s.get("id") != score_id]
    if len(remaining) == len(scores):
        raise HTTPException(status_code=404, detail="score not found")
    _save_nbme(remaining)
    return {"deleted": True}


# ── Email → Calendar ──────────────────────────────────────────────────────────

class AddToCalendarBody(BaseModel):
    title: str
    start_iso: str
    end_iso: str | None = None
    location: str | None = None
    notes: str | None = None
    calendar_name: str = "School"


@router.post("/widgets/email/add-to-calendar")
def email_add_to_calendar(body: AddToCalendarBody, request: Request):
    _require_local_origin(request)
    from tools.desktop_apps import _calendar_create_event
    result = _calendar_create_event(
        title=body.title,
        start_iso=body.start_iso,
        end_iso=body.end_iso or "",
        calendar_name=body.calendar_name,
        location=body.location or "",
        notes=body.notes or "",
    )
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "event_id": result.get("event_id")}


# ── Email mark-as-read ────────────────────────────────────────────────────────

class MarkReadBody(BaseModel):
    id: str


@router.post("/widgets/email/mark-read")
def email_mark_read(body: MarkReadBody, request: Request):
    """Mark an Outlook message as read by its integer id.

    Uses the same folder-iteration lookup as open_outlook_email in
    tools/desktop_apps.py — tries inbox first, then all mail folders.
    Also busts email cache keys so the next list refresh reflects the change.
    """
    _require_local_origin(request)
    msg_id = (body.id or "").strip()
    if not msg_id or not msg_id.isdigit():
        return {"ok": False, "error": "id must be a numeric Outlook message id"}

    safe_id = msg_id
    script = f"""
tell application "Microsoft Outlook"
    try
        set theMsg to first message of inbox whose id is {safe_id}
        set is read of theMsg to true
        return "marked_read"
    on error
        try
            repeat with f in mail folders
                try
                    set theMsg to first message of f whose id is {safe_id}
                    set is read of theMsg to true
                    return "marked_read"
                end try
            end repeat
        end try
        return "not_found"
    end try
end tell
"""
    result = _osascript(script, timeout=15)
    output = result.get("output", "")
    if result.get("error"):
        return {"ok": False, "error": result["error"]}

    # Bust all email cache entries so the next poll shows read: true.
    with _CACHE_LOCK:
        stale_keys = [k for k in _CACHE if k.startswith("email::")]
        for k in stale_keys:
            del _CACHE[k]

    if "marked_read" in output:
        return {"ok": True}
    # "not_found" still means the request ran cleanly — message may already
    # be read or in a folder the script couldn't enumerate. Return ok=True
    # so the frontend still updates optimistically.
    return {"ok": True, "note": output or "not_found"}


# ── Honey-do (todos) — minimal local-storage backend ─────────────────────────
#
# Filed under storage/honeydo.json so the user can edit it by hand. The
# briefing widget reads pending todos and renders them as one of three
# top-level sections.

import re as _re
import uuid as _uuid
import anthropic as _anthropic
import os as _os

HONEYDO_STORE = CACHE_DIR / "honeydo.json"

# Canonical scoring rules — ported from frontend/src/lib/inbox-rules.ts so the
# briefing's "important unread emails" section matches what the inbox widget
# would call important. Update both files together if rules change.
_VIP_DOMAINS = ("cooperhealth.org", "rowan.edu", "kennedyhealth.org")
_ACTION_WORDS_RE = _re.compile(
    r"\b(urgent|action required|please review|sign|approve|deadline|due|invoice|appointment|interview|offer|reminder)\b",
    _re.IGNORECASE,
)
_NEWSLETTER_PATTERNS = [
    _re.compile(r"-?noreply@", _re.IGNORECASE),
    _re.compile(r"newsletter", _re.IGNORECASE),
    _re.compile(r"no-?reply", _re.IGNORECASE),
    _re.compile(r"donotreply", _re.IGNORECASE),
    _re.compile(r"\bannouncer\b", _re.IGNORECASE),
    _re.compile(r"\bdigest\b", _re.IGNORECASE),
    _re.compile(r"\bmarketing@", _re.IGNORECASE),
    _re.compile(r"\binfo@", _re.IGNORECASE),
]
_DEMOTED_FOLDERS = {
    "Promotions", "Updates", "Forums", "Newsletters",
    "Junk", "Junk Email", "Junk E-mail", "Clutter",
}
_IMPORTANT_FOLDERS = {"Inbox", "Rowan class of 2027"}

# Commerce senders (food delivery, ride-share, peer payments) never belong in
# a medical-student morning briefing. These domains are senders whose email is
# purely transactional and carries zero actionability for the user's studies or
# clinical workflow — hard-penalise so they never float above the fold.
_COMMERCE_BLOCKLIST = {
    "grubhub.com", "doordash.com", "ubereats.com", "seamless.com",
    "postmates.com", "uber.com", "lyft.com", "venmo.com",
    "paypal.com", "cash.app",
}

# Amazon sends genuinely important emails (seller alerts, account security) but
# the overwhelming majority are order-status notifications. We want to suppress
# only the order-related ones without nuking e.g. "Your AWS bill is ready".
_AMAZON_ORDER_RE = _re.compile(
    r"\b(your order|delivery|shipped|arriving|order #|out for delivery)\b",
    _re.IGNORECASE,
)


def _is_newsletter(email: dict) -> bool:
    addr = (email.get("from_email") or email.get("from") or "")
    return any(p.search(addr) for p in _NEWSLETTER_PATTERNS)


def _score_email(email: dict) -> tuple[int, list[str]]:
    """Return (score, reasons) for the given email dict.

    reasons is a list of human-readable tags (e.g. "VIP +50") that explain
    why the score landed where it did — used by the briefing widget tooltip.
    """
    s = 0
    reasons: list[str] = []
    addr = (email.get("from_email") or email.get("from") or "").lower()
    m = _re.search(r"@([^>\s]+)", addr)
    domain = (m.group(1) if m else "").lower()

    if any(domain.endswith(d) for d in _VIP_DOMAINS):
        s += 50
        reasons.append("VIP +50")

    matches = len(_ACTION_WORDS_RE.findall(email.get("subject") or ""))
    if matches:
        bonus = min(matches * 5, 15)
        s += bonus
        reasons.append(f"action-word x{matches} +{bonus}")

    folder = email.get("folder")
    if folder and folder in _DEMOTED_FOLDERS:
        s -= 40
        reasons.append("demoted-folder -40")
    if folder and folder in _IMPORTANT_FOLDERS:
        s += 20
        reasons.append("important-folder +20")

    if _is_newsletter(email):
        s -= 35
        reasons.append("newsletter -35")

    # Commerce senders: hard-penalise so food-delivery / ride-share receipts
    # never surface in the morning briefing above genuinely actionable mail.
    if domain and any(domain.endswith(d) for d in _COMMERCE_BLOCKLIST):
        s -= 50
        reasons.append("commerce -50")
    elif domain.endswith("amazon.com") and _AMAZON_ORDER_RE.search(
        email.get("subject") or ""
    ):
        # Only penalise Amazon when the subject is clearly order-status noise;
        # account/security emails from amazon.com should still surface normally.
        s -= 50
        reasons.append("commerce -50")

    return s, reasons


class TodoIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    due: Optional[str] = Field(None, max_length=10)  # YYYY-MM-DD


class TodoUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=500)
    done: Optional[bool] = None
    due: Optional[str] = Field(None, max_length=10)


def _load_todos() -> list[dict]:
    data = read_json(HONEYDO_STORE, default=[])
    if not isinstance(data, list):
        return []
    return data


def _save_todos(items: list[dict]) -> None:
    write_json(HONEYDO_STORE, items)


@router.get("/widgets/todos")
def todos_list():
    """Return all honey-do items, oldest-first by created_at.

    Items: {id, text, done, due (YYYY-MM-DD or None), created_at (ISO)}
    """
    items = _load_todos()
    pending = [t for t in items if not t.get("done")]
    return {
        "todos": items,
        "pending": pending,
        "pending_count": len(pending),
    }


@router.post("/widgets/todos")
def todos_create(payload: TodoIn, request: Request):
    _require_local_origin(request)
    items = _load_todos()
    new = {
        "id": _uuid.uuid4().hex[:12],
        "text": payload.text.strip(),
        "done": False,
        "due": (payload.due or None),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.append(new)
    _save_todos(items)
    return {"ok": True, "todo": new}


@router.patch("/widgets/todos/{todo_id}")
def todos_update(todo_id: str, payload: TodoUpdate, request: Request):
    _require_local_origin(request)
    items = _load_todos()
    for t in items:
        if t.get("id") == todo_id:
            if payload.text is not None:
                t["text"] = payload.text.strip()
            if payload.done is not None:
                t["done"] = bool(payload.done)
            if payload.due is not None:
                t["due"] = payload.due or None
            _save_todos(items)
            return {"ok": True, "todo": t}
    # Consistent with nbme_delete — missing resource is a 404, not a silent 200.
    # Frontend `if (!r.ok)` relies on a non-2xx status to show error state.
    raise HTTPException(status_code=404, detail="todo not found")


@router.delete("/widgets/todos/{todo_id}")
def todos_delete(todo_id: str, request: Request):
    _require_local_origin(request)
    items = _load_todos()
    new_items = [t for t in items if t.get("id") != todo_id]
    if len(new_items) == len(items):
        # Consistent with nbme_delete — missing resource is a 404, not a silent 200.
        # Frontend `if (!r.ok)` relies on a non-2xx status to show error state.
        raise HTTPException(status_code=404, detail="todo not found")
    _save_todos(new_items)
    return {"ok": True}
