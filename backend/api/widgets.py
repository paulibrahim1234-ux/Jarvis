"""
Widget endpoints — try desktop apps first, fall back to API-based tools.
Desktop apps (Outlook, Spotify) work with no OAuth or Azure setup.
"""

import threading
import time
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from tools.anki import _invoke as anki_invoke
from tools.imessage import get_conversations
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
    """
    now = time.time()
    entry = _CACHE.get(key)
    if entry and entry[0] > now:
        return entry[1]
    if sem is not None:
        acquired = sem.acquire(blocking=True, timeout=0.05)
        # If we couldn't grab the lock a sibling thread is already computing;
        # return the stale value (or None) rather than queuing another call.
        if not acquired:
            return entry[1] if entry else None
        try:
            value = compute()
        finally:
            sem.release()
    else:
        value = compute()
    # Short TTL on negative results so a one-time failure doesn't lock in.
    effective_ttl = ttl
    if value is None or value == {} or value == []:
        effective_ttl = min(ttl, 10.0)
    _CACHE[key] = (now + effective_ttl, value)
    return value


# ── Anki ──────────────────────────────────────────────────────────────────────

@router.get("/widgets/anki")
def anki_stats():
    try:
        due_ids = anki_invoke("findCards", query="is:due")
        reviewed_ids = anki_invoke("findCards", query="rated:1")
        new_ids = anki_invoke("findCards", query="is:new is:due")
        return {
            "due": len(due_ids),
            "reviewedToday": len(reviewed_ids),
            "newCards": len(new_ids),
            "streak": _compute_streak(),
            "retention": _compute_retention(),
            "available": True,
        }
    except Exception as e:
        return {"error": str(e), "available": False}


def _compute_streak() -> int:
    from datetime import date, timedelta
    today = date.today()
    streak = 0
    for i in range(365):
        d = today - timedelta(days=i)
        epoch = int(d.strftime("%Y%m%d"))
        try:
            reviews = anki_invoke("cardReviews", deck="*", startID=epoch)
            if reviews:
                streak += 1
            else:
                break
        except Exception:
            break
    return streak


def _compute_retention() -> int:
    from datetime import date, timedelta
    start = date.today() - timedelta(days=30)
    epoch = int(start.strftime("%Y%m%d"))
    try:
        reviews = anki_invoke("cardReviews", deck="*", startID=epoch)
        if not reviews:
            return 0
        correct = sum(1 for r in reviews if r[3] > 1)
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
    epoch_param = int(start.strftime("%Y%m%d"))
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


def _load_uworld_incorrect() -> list[dict]:
    try:
        with _UWORLD_STUB_PATH.open() as f:
            data = _json.load(f)
        items = data.get("incorrect", []) if isinstance(data, dict) else []
        return [i for i in items if isinstance(i, dict) and i.get("uworld_qid")]
    except Exception:
        return []


@router.get("/widgets/anki/suggestions")
def anki_suggestions():
    """Return suspended Anki cards tagged to UWorld questions the user missed.

    For each mock UWorld incorrect entry, queries AnkiConnect for suspended
    cards tagged `uworld_qid_<qid>`. Returns an empty list with available=False
    if AnkiConnect is unreachable.
    """
    mock_incorrects = _load_uworld_incorrect()
    if not mock_incorrects:
        return {"suggestions": [], "available": True, "source": "stub_empty"}

    suggestions: list[dict] = []
    try:
        for item in mock_incorrects:
            qid = str(item.get("uworld_qid", ""))
            if not qid:
                continue
            query = f"tag:uworld_qid_{qid} is:suspended"
            try:
                card_ids = anki_invoke("findCards", query=query) or []
            except Exception:
                # Any AnkiConnect failure at this point = not available overall
                raise
            if not card_ids:
                continue
            # Pull card fronts + tag for up to first 5 matches per qid.
            card_ids = card_ids[:5]
            try:
                info = anki_invoke("cardsInfo", cards=card_ids) or []
            except Exception:
                info = []
            for card in info:
                fields = card.get("fields", {}) or {}
                # Anki field names vary; pick first string-valued field.
                front_raw = ""
                for _, v in fields.items():
                    if isinstance(v, dict) and isinstance(v.get("value"), str):
                        front_raw = v["value"]
                        break
                # Strip basic HTML tags for preview.
                import re as _re
                front_text = _re.sub(r"<[^>]+>", "", front_raw).strip()
                tags = card.get("tags", []) or []
                primary_tag = next(
                    (t for t in tags if not t.startswith("uworld_qid_")),
                    tags[0] if tags else "",
                )
                suggestions.append({
                    "card_id": card.get("cardId"),
                    "front": front_text[:100],
                    "tag": primary_tag,
                    "uworld_qid": qid,
                    "uworld_topic": item.get("uworld_topic", ""),
                    "missed_at": item.get("missed_at", ""),
                })
        return {"suggestions": suggestions, "available": True, "source": "stub"}
    except Exception as e:
        return {"suggestions": [], "available": False, "error": str(e)}


class AnkiUnsuspendBody(BaseModel):
    card_ids: list[int]


def _require_local_origin(request) -> None:
    """
    Reject cross-site POSTs. The dashboard binds 127.0.0.1:8000 but a
    malicious page in another tab could fetch with Content-Type: text/plain
    (a "simple" CORS request that bypasses preflight) and trigger writes.
    Allow only requests whose Origin / Referer (when present) maps to
    localhost, or browser-less callers (curl) that send neither header.
    """
    from fastapi import HTTPException

    def _host(url: str) -> str:
        # crude — just enough to extract netloc from "http://host:port/..."
        if "://" not in url:
            return ""
        rest = url.split("://", 1)[1]
        return rest.split("/", 1)[0].lower()

    LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
    for header in ("origin", "referer"):
        val = request.headers.get(header)
        if not val:
            continue
        host = _host(val)
        # Host portion may include :port — strip it.
        bare = host.rsplit(":", 1)[0] if host.startswith(("127.", "localhost", "[::1]")) else host.split(":")[0]
        if bare not in LOCAL_HOSTS:
            raise HTTPException(
                status_code=403,
                detail=f"cross-site write rejected (origin host: {bare})",
            )


@router.post("/widgets/anki/unsuspend")
def anki_unsuspend(body: AnkiUnsuspendBody, request: Request):
    """Unsuspend the given Anki card IDs via AnkiConnect. Requires explicit
    click in the dashboard. Cross-site POSTs are rejected."""
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
def imessage_widget(include_groups: bool = False, limit: int = 25):
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
        try:
            from tools.contacts import resolve as _resolve_contact
            for c in convos:
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


@router.get("/widgets/email")
def email_widget(
    folder: str = Query("", description="Optional mail folder name"),
    account: str = Query("", description="Optional account name/email filter"),
):
    # Cache per (folder, account) pair; 60s TTL matches the default.
    cache_key = f"email::{folder}::{account}"
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
    # HIPAA: hide clinical/rotation titles and room-allocation location strings
    _HIDDEN_CALS = {"Rotation", "Subscribed Calendar", "Work"}
    for e in deduped:
        if e.get("calendar") in _HIDDEN_CALS:
            e["title"] = "(hidden)"
            e["location"] = ""
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
def calendar_widget(start: str = "", end: str = ""):
    # 10 min cache — Calendar.app AppleScript takes 30-60s on user's
    # 12-calendar setup. The single-permit semaphore caused the FIRST
    # caller to get None (no cache yet, sem held by in-flight compute)
    # while later callers got real data — frontend then never refetched.
    # Drop the sem here; FastAPI's threadpool absorbs the parallel hits
    # and the first compute populates the cache for everyone after.
    cached = _cached("calendar", 600, _compute_calendar)
    if cached:
        # Apply date-range filtering when both start and end are provided.
        # Event "start" fields from AppleScript are human-formatted strings
        # (e.g. "Wednesday, April 22, 2026 at 1:00:00 PM") — not ISO dates —
        # so we can only filter on events that carry an ISO "start_iso" field.
        # If the cache lacks that field we silently return all events so the
        # endpoint never 422s.
        if start and end:
            try:
                start_dt = datetime.fromisoformat(start.rstrip("Z"))
                end_dt = datetime.fromisoformat(end.rstrip("Z"))
                events = cached.get("events", [])
                filtered = []
                for e in events:
                    iso = e.get("start_iso") or e.get("start_dt") or ""
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


# ── On-demand warmup ──────────────────────────────────────────────────────────

@router.post("/widgets/warm")
def warm_widgets():
    """Fire all slow AppleScript compute functions in the background so caches
    are hot before the user's first widget interaction.

    Returns immediately with a list of which caches were already warm and
    which were triggered. Safe to call multiple times — semaphores prevent
    duplicate in-flight AppleScript invocations.
    """
    import concurrent.futures

    tasks = {
        "calendar": ("calendar", 90, _compute_calendar, _SEM_CALENDAR),
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
    return _cached("spotify_playlists", 60, _compute)


def _spotify_recents_cached():
    if not _spotify_web_ok():
        return None
    def _compute():
        from tools.spotify import get_recently_played
        return get_recently_played(limit=10)
    return _cached("spotify_recents", 60, _compute)


def _spotify_queue_live():
    if not _spotify_web_ok():
        return None
    try:
        from tools.spotify import get_queue
        return get_queue()
    except Exception:
        return None


@router.get("/widgets/spotify")
def spotify_widget():
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
        progress_ms = int(now.get("position_s", 0) or 0) * 1000
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
        try:
            from tools.spotify import get_now_playing
            wp = get_now_playing()
            if wp:
                track_block = {
                    **wp,
                    "name": wp.get("title"),
                }
                album_art = wp.get("album_art")
        except Exception:
            pass

    return {
        "available": bool(track_block) or web_ok,
        "source": "desktop" if now.get("track") else ("web_api" if web_ok else None),
        "track": track_block,
        "album_art_url": album_art,
        "web_api_connected": web_ok,
        "auth_url": None if web_ok else "http://127.0.0.1:8000/auth/spotify",
        "queue": _spotify_queue_live(),
        "playlists": _spotify_playlists_cached(),
        "recently_played": _spotify_recents_cached(),
    }


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
def spotify_search(body: SpotifySearchBody):
    if not _spotify_web_ok():
        return {
            "results": None,
            "error": "Spotify Web API not connected. Visit /auth/spotify to connect.",
            "auth_url": "http://127.0.0.1:8000/auth/spotify",
        }
    try:
        from tools.spotify import search_tracks
        results = search_tracks(body.query, limit=10) or []
        return {"results": results}
    except Exception as e:
        return {"results": None, "error": str(e)}


@router.post("/widgets/spotify/play")
def spotify_play(body: SpotifyPlayBody):
    """Play a Spotify URI via AppleScript (requires Spotify desktop app open)."""
    data = _spotify_play_uri(body.uri)
    if "error" in data:
        return {"ok": False, "error": data["error"]}
    return {"ok": True, "now_playing": data.get("track")}


@router.post("/widgets/spotify/control")
def spotify_control(body: SpotifyControlBody):
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


@router.post("/widgets/spotify/volume")
def spotify_volume(body: SpotifyVolumeBody):
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
        # HIPAA: hide clinical/rotation titles and room-allocation location strings
        _HIDDEN_CALS = {"Rotation", "Subscribed Calendar", "Work"}
        for e in events:
            if e.get("calendar") in _HIDDEN_CALS:
                e["title"] = "(hidden)"
                e["location"] = ""
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
    """Format an ISO datetime as '7:00 AM'. Returns '' if unparsable."""
    if not iso or len(iso) < 16:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return ""
    return dt.strftime("%-I:%M %p")


# ── Morning briefing ──────────────────────────────────────────────────────────

@router.get("/widgets/briefing")
def briefing_widget():
    """
    Aggregates Anki stats + today's calendar events + unread mail count
    + folder-level mail breakdown + iMessage unread + Spotify now-playing
    + NBME score trend / next-exam countdown.

    Each fetcher runs in a ThreadPoolExecutor with a per-task 3s timeout so
    one slow integration can't block the whole briefing.
    """
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
            if cached:
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
                    if dt.tzinfo is not None:
                        dt = dt.replace(tzinfo=None)
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

    # Folders that are noise in a morning briefing — Inbox is rolled into
    # `unread_mail`, the rest are infra/cleanup buckets the user doesn't read.
    _BRIEFING_HIDDEN = {
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
    }

    def fetch_folders():
        try:
            data = _cached("email_folders", 300, _compute_email_folders)
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
            convos = get_conversations(limit=25, messages_per_thread=1, include_groups=False)
            try:
                from tools.contacts import resolve as _resolve_contact
            except Exception:
                _resolve_contact = None
            count = 0
            for c in convos:
                unread = int(c.get("unread_count") or 0)
                if unread <= 0:
                    continue
                handle = c.get("handle") or c.get("contact", "")
                resolved = None
                if _resolve_contact:
                    try:
                        resolved = _resolve_contact(handle)
                    except Exception:
                        resolved = None
                count += unread
            return count
        except Exception as e:
            errors.append(f"imessage: {e}")
            return None

    def fetch_now_playing():
        # Use _osascript with a 2s timeout so a closed Spotify app doesn't
        # stall the briefing. The full _spotify_now_playing() uses the 15s
        # default which always exceeds the briefing's per-fetcher budget.
        try:
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

    fetchers = {
        "anki": fetch_anki,
        "events": fetch_events,
        "unread": fetch_unread,
        "folders": fetch_folders,
        "messages": fetch_messages,
        "now_playing": fetch_now_playing,
        "nbme": fetch_nbme,
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
def nbme_create(payload: NBMEScoreIn):
    scores = _load_nbme()
    new_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}"
    record = {"id": new_id, **payload.model_dump()}
    scores.append(record)
    _save_nbme(scores)
    return record


@router.delete("/widgets/nbme/{score_id}")
def nbme_delete(score_id: str):
    scores = _load_nbme()
    remaining = [s for s in scores if s.get("id") != score_id]
    if len(remaining) == len(scores):
        raise HTTPException(status_code=404, detail="score not found")
    _save_nbme(remaining)
    return {"deleted": True}
