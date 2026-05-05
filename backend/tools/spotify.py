"""
Spotify integration via spotipy.

Auth: Authorization Code Flow (browser redirect).
Setup: visit http://127.0.0.1:8000/setup — enter credentials there.

Token stored at ~/.jarvis/spotify_token (auto-refreshed).
"""

import os
from pathlib import Path

CACHE_PATH = str(Path.home() / ".jarvis" / "spotify_token")
SCOPES = (
    "user-read-currently-playing "
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-recently-played "
    "playlist-read-private "
    "playlist-read-collaborative "
    "user-library-read "
    "user-top-read"
)

SPOTIFY_TOOLS = [
    {
        "name": "spotify_now_playing",
        "description": "Get the currently playing Spotify track, artist, album, and playback progress.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_play_pause",
        "description": "Toggle Spotify play/pause.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "spotify_skip",
        "description": "Skip to the next track on Spotify.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _creds():
    return (
        os.environ.get("SPOTIFY_CLIENT_ID", ""),
        os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/auth/spotify/callback"),
    )


def _auth():
    client_id, client_secret, redirect_uri = _creds()
    if not client_id:
        raise RuntimeError("SPOTIFY_CLIENT_ID not set — visit http://127.0.0.1:8000/setup")
    from spotipy.oauth2 import SpotifyOAuth
    Path(CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPES,
        cache_path=CACHE_PATH,
        open_browser=False,
    )


def _sp():
    """Return the module-level Spotify client singleton, creating it on first call.

    Using a singleton avoids constructing a new requests.Session on every widget
    tick (the old fresh-per-call pattern), which was the primary source of the
    4-burst pattern that tripped Spotify's rate limiter. The singleton is kept
    until a 401 forces a rebuild via _reset_sp_instance().

    Py#6 — lock-order fix: the old code held _SP_INSTANCE_LOCK (outer) while
    acquiring _TOKEN_REFRESH_LOCK (inner) and doing network I/O. Problems:
      1. Nested lock-order hazard — any path taking _TOKEN_REFRESH_LOCK first
         then _SP_INSTANCE_LOCK would deadlock.
      2. All threads blocked on _SP_INSTANCE_LOCK during a token-refresh HTTP
         round-trip (up to 8 s), serialising every concurrent widget tick.

    New pattern: fast-path read with no locks (GIL guards the pointer read),
    then network I/O under _TOKEN_REFRESH_LOCK alone, then briefly take
    _SP_INSTANCE_LOCK only for the cheap pointer assignment. The double-check
    inside the instance lock handles the race where two threads both took the
    slow path — the second one returns whichever instance won the assignment.
    """
    # Fast path: singleton already built — no lock needed (GIL protects read).
    if _SP_INSTANCE is not None:
        return _SP_INSTANCE

    # Slow path: build a new client. Validate the cached token under the
    # refresh lock alone so concurrent widget threads don't race on the
    # Spotify token endpoint (rotation: first write wins, others get 401).
    import spotipy
    auth = _auth()
    with _TOKEN_REFRESH_LOCK:
        auth.validate_token(auth.cache_handler.get_cached_token())
    new_client = spotipy.Spotify(
        auth_manager=auth,
        retries=0,             # don't auto-retry — we'd rather see the failure quick
        status_retries=0,
        backoff_factor=0,
        requests_timeout=8,    # per-call HTTP timeout in seconds
    )
    # Brief instance-lock window — only the pointer assignment, no I/O.
    # Double-check: if another thread won the race and set _SP_INSTANCE
    # while we were building new_client, return their instance (both are
    # equally valid; only one refresh-token write matters, already done
    # above under _TOKEN_REFRESH_LOCK).
    with _SP_INSTANCE_LOCK:
        if _SP_INSTANCE is None:
            globals()["_SP_INSTANCE"] = new_client
        return _SP_INSTANCE


def _reset_sp_instance() -> None:
    """Force rebuild of the Spotify client singleton on the next _sp() call.

    Called from any 401 catch path — a 401 means the auth_manager's token
    has become invalid in a way that requires re-creating the client (e.g.
    refresh token rotation issued a new token that the old session doesn't
    know about). Resetting here causes _sp() to redo validate_token +
    construct a fresh Spotify object with the new token on the next call.
    """
    global _SP_INSTANCE
    with _SP_INSTANCE_LOCK:
        _SP_INSTANCE = None


# ── Rate-limit circuit breaker ────────────────────────────────────────────────
# Spotify can rate-limit an app's CLIENT credentials for hours at a time
# (observed Retry-After 19,000+ seconds = 5+ hours). Without a breaker,
# every widget tick fires another doomed request, which:
#   1. Makes the rate-limit window potentially renew (each blocked request
#      still counts in some quota implementations).
#   2. Leaves the user with empty arrays and zero hint why.
#   3. Floods stderr with spotipy "Max Retries reached" noise.
#
# Pattern: any function that hits a 429 calls _record_rate_limit(retry_after_s).
# All public getters check _check_rate_limited() first and short-circuit
# with a sentinel marker dict (not a bare []), so the widget endpoint can
# distinguish "rate-limited" from "empty result" and surface a clear UI
# message ("Spotify rate-limited — retrying at HH:MM").

import threading as _threading
import time as _time

_RATE_LIMIT_LOCK = _threading.Lock()

# Serializes the token expiry-check + potential refresh across threads.
# Without this, concurrent widget calls (ThreadPoolExecutor, up to 4 workers)
# all hit validate_token simultaneously on expiry. Spotify rotates refresh
# tokens — first write wins, the others get invalidated refresh tokens and
# produce 401s on the very next cycle.
_TOKEN_REFRESH_LOCK = _threading.Lock()

# ── Singleton Spotify client ──────────────────────────────────────────────────
# Constructing a fresh spotipy.Spotify on every _sp() call means every widget
# tick recreates the underlying requests.Session, which (a) does not reuse
# HTTP keep-alive connections and (b) re-runs validate_token under
# _TOKEN_REFRESH_LOCK on every single call — serializing all concurrent widget
# requests through a single gate. A module-level singleton reuses the session
# and only rebuilds on 401 (via _reset_sp_instance()).
_SP_INSTANCE: "spotipy.Spotify | None" = None
_SP_INSTANCE_LOCK = _threading.Lock()

_RATE_LIMIT_UNTIL: float = 0.0          # epoch seconds; 0 = not limited
_RATE_LIMIT_LAST_REASON: str = ""       # human-readable last reason, for logs/UI

# Sentinel returned in place of [] when we're skipping a call due to the breaker.
# Endpoints check `is RATE_LIMITED_SENTINEL` to switch behavior.
RATE_LIMITED_SENTINEL = object()


def _check_rate_limited() -> float:
    """Return seconds remaining in the rate-limit window (0.0 if clear)."""
    with _RATE_LIMIT_LOCK:
        if _RATE_LIMIT_UNTIL <= 0:
            return 0.0
        remaining = _RATE_LIMIT_UNTIL - _time.time()
        return max(0.0, remaining)


def _record_rate_limit(retry_after_s: float, reason: str = "") -> None:
    """Trip the breaker until now+retry_after_s.

    Cap at 1 hour to avoid pathologically long stalls if Spotify returns
    a multi-hour Retry-After (5+ hours has been observed). After the cap,
    we'll let one probe through and re-trip if still limited.
    """
    global _RATE_LIMIT_UNTIL, _RATE_LIMIT_LAST_REASON
    capped = max(60.0, min(retry_after_s, 3600.0))
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_UNTIL = _time.time() + capped
        _RATE_LIMIT_LAST_REASON = reason or f"rate-limited for {int(capped)}s"


def _maybe_trip_breaker(exc: Exception) -> bool:
    """If `exc` looks like a 429, trip the breaker and return True.

    Reads Retry-After from the SpotifyException message ("Retry will occur
    after: 19149 s") since spotipy doesn't expose headers reliably after
    its retries=0 path swallows them.
    """
    msg = str(exc)
    if "429" not in msg and "rate/request limit" not in msg.lower() and "Max Retries" not in msg:
        return False
    import re as _re
    # Prefer Retry-After from the exception headers (spotipy exposes these on
    # SpotifyException as e.headers when retries=0 bypasses the retry machinery).
    # Fall back to parsing the seconds from the exception message string.
    retry_after = 600.0
    try:
        headers = getattr(exc, "headers", None) or {}
        ra = headers.get("Retry-After") or headers.get("retry-after")
        if ra:
            retry_after = float(ra)
    except Exception:
        pass
    if retry_after == 600.0:
        m = _re.search(r"after:\s*(\d+)", msg)
        if m:
            retry_after = float(m.group(1))
    _record_rate_limit(retry_after, reason=msg[:200])
    return True


def rate_limit_status() -> dict:
    """Public probe — used by the widget endpoint to surface state to the UI."""
    remaining = _check_rate_limited()
    return {
        "rate_limited": remaining > 0,
        "retry_in_seconds": int(remaining),
        "last_reason": _RATE_LIMIT_LAST_REASON if remaining > 0 else "",
    }


def get_auth_url() -> str:
    return _auth().get_authorize_url()


def handle_callback(code: str) -> bool:
    try:
        _auth().get_access_token(code, as_dict=False)
        return True
    except Exception:
        return False


def is_authenticated() -> bool:
    try:
        client_id, _, _ = _creds()
        if not client_id:
            return False
        a = _auth()
        token = a.get_cached_token()
        return bool(token and not a.is_token_expired(token))
    except Exception:
        return False


def get_now_playing() -> dict | None:
    if _check_rate_limited() > 0:
        return None  # widget already shows breaker banner; no point in a second one here
    try:
        sp = _sp()
        current = sp.current_playback()
        if not current or not current.get("item"):
            return None
        item = current["item"]
        progress_ms = current.get("progress_ms", 0)
        duration_ms = item.get("duration_ms", 1)
        return {
            "title": item["name"],
            "artist": ", ".join(a["name"] for a in item["artists"]),
            "album": item["album"]["name"],
            "album_art": item["album"]["images"][0]["url"] if item["album"]["images"] else None,
            "duration_ms": duration_ms,
            "progress_ms": progress_ms,
            "progress": progress_ms / duration_ms,
            "is_playing": current.get("is_playing", False),
            "uri": item.get("uri"),
        }
    except Exception as e:
        _maybe_trip_breaker(e)
        return None


def get_queue() -> list[dict] | None:
    """Upcoming tracks (requires user-read-playback-state)."""
    if _check_rate_limited() > 0:
        return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
    try:
        sp = _sp()
        q = sp.queue()
        if not q:
            return []
        return [
            {
                "title": t.get("name"),
                "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                "album": t.get("album", {}).get("name"),
                "album_art": (t.get("album", {}).get("images") or [{}])[0].get("url"),
                "duration_ms": t.get("duration_ms", 0),
                "uri": t.get("uri"),
            }
            for t in (q.get("queue") or [])[:20]
        ]
    except Exception as e:
        if _maybe_trip_breaker(e):
            return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
        return None


def get_playlists(limit: int = 20) -> list[dict] | None:
    if _check_rate_limited() > 0:
        return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
    try:
        sp = _sp()
        res = sp.current_user_playlists(limit=limit)
        items = res.get("items", []) if res else []
        return [
            {
                "name": p.get("name"),
                "uri": p.get("uri"),
                "id": p.get("id"),
                "cover": (p.get("images") or [{}])[0].get("url"),
                "track_count": (p.get("tracks") or {}).get("total", 0),
                "owner": (p.get("owner") or {}).get("display_name"),
            }
            for p in items
        ]
    except Exception as e:
        if _maybe_trip_breaker(e):
            return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
        return None


def get_recently_played(limit: int = 10) -> list[dict] | None:
    if _check_rate_limited() > 0:
        return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
    try:
        sp = _sp()
        res = sp.current_user_recently_played(limit=limit)
        out = []
        seen_uris = set()
        for item in (res.get("items", []) if res else []):
            t = item.get("track") or {}
            uri = t.get("uri")
            if uri in seen_uris:
                continue
            seen_uris.add(uri)
            out.append({
                "title": t.get("name"),
                "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                "album": t.get("album", {}).get("name"),
                "album_art": (t.get("album", {}).get("images") or [{}])[0].get("url"),
                "duration_ms": t.get("duration_ms", 0),
                "uri": uri,
                "played_at": item.get("played_at"),
            })
        return out
    except Exception as e:
        if _maybe_trip_breaker(e):
            return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
        return None


def get_top_tracks(time_range: str = "short_term", limit: int = 8) -> list[dict]:
    """Get user's top tracks for the given time range (short_term/medium_term/long_term).

    Returns RATE_LIMITED_SENTINEL when the breaker is tripped so the widget
    can render a "rate-limited until HH:MM" notice instead of a blank list.
    """
    if _check_rate_limited() > 0:
        return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
    try:
        sp = _sp()
        result = sp.current_user_top_tracks(limit=limit, time_range=time_range)
        return [
            {
                "title": t["name"],
                "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                "album_art": (t["album"]["images"][0]["url"] if t["album"].get("images") else None),
                "uri": t.get("uri"),
            }
            for t in (result.get("items") or [])
        ]
    except Exception as e:
        if _maybe_trip_breaker(e):
            return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
        return []


def get_top_artists(time_range: str = "short_term", limit: int = 8) -> list[dict]:
    """Get user's top artists for the given time range."""
    if _check_rate_limited() > 0:
        return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
    try:
        sp = _sp()
        result = sp.current_user_top_artists(limit=limit, time_range=time_range)
        return [
            {
                "name": a["name"],
                "album_art": (a["images"][0]["url"] if a.get("images") else None),
                "uri": a.get("uri"),
            }
            for a in (result.get("items") or [])
        ]
    except Exception as e:
        if _maybe_trip_breaker(e):
            return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
        return []


def search_tracks(query: str, limit: int = 10) -> list[dict] | None:
    try:
        sp = _sp()
        res = sp.search(q=query, type="track", limit=limit)
        items = ((res or {}).get("tracks") or {}).get("items", [])
        return [
            {
                "title": t.get("name"),
                "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                "album": t.get("album", {}).get("name"),
                "album_art": (t.get("album", {}).get("images") or [{}])[0].get("url"),
                "duration_ms": t.get("duration_ms", 0),
                "uri": t.get("uri"),
            }
            for t in items
        ]
    except Exception:
        return None


def play_context_uri(uri: str) -> dict:
    """Play a context (playlist/album/artist) via the Spotify Web API.

    Uses PUT /v1/me/player/play with {"context_uri": uri}.
    Returns {ok: bool, error?: str (machine code), message?: str (user-facing)}.
    """
    try:
        sp = _sp()
        sp.start_playback(context_uri=uri)
        return {"ok": True}
    except Exception as e:
        msg = str(e)
        # No device with active playback. User must open Spotify and play
        # at least one track manually to register a device with the API.
        if "No active device" in msg or "NO_ACTIVE_DEVICE" in msg:
            return {
                "ok": False,
                "error": "no_active_device",
                "message": "Open Spotify and start any track first, then try the mood tile again.",
            }
        # 404 on the context URI — Spotify-editorial playlists were locked
        # down to non-commercial clients in late 2024, so most 37i9... IDs
        # return Resource not found. User can replace via the Edit button.
        if "Resource not found" in msg or "404" in msg:
            return {
                "ok": False,
                "error": "playlist_unavailable",
                "message": "Spotify can't access this playlist for your account. Click Edit on the Moods tab to swap in one of your own playlists.",
            }
        if "PREMIUM_REQUIRED" in msg or "Premium" in msg or "403" in msg:
            return {
                "ok": False,
                "error": "premium_required",
                "message": "Playback control requires Spotify Premium.",
            }
        return {"ok": False, "error": "unknown", "message": msg}


def get_recently_played_playlists(limit: int = 8) -> list[dict] | None:
    """Return up to `limit` unique playlists from recently-played history.

    For each item in the recently-played endpoint, inspect context.type.
    Deduplicate by context URI and fetch cover art via /v1/playlists/{id}.
    Returns None when unauthenticated, [] when no playlist context found.

    Performance: per-playlist sp.playlist() lookups run in parallel via a
    thread pool (Spotify deprecated their playlist-batch endpoint, so the
    only way to fetch N playlists by ID is N HTTP roundtrips). 4 workers
    cap concurrency so we don't fan out beyond what the FastAPI threadpool
    is comfortable with.
    """
    if _check_rate_limited() > 0:
        return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
    try:
        sp = _sp()
        res = sp.current_user_recently_played(limit=50)
        items = res.get("items", []) if res else []

        # First pass: collect unique playlist URIs in encounter order, capped at limit.
        ordered_uris: list[str] = []
        for item in items:
            ctx = item.get("context") or {}
            if ctx.get("type") != "playlist":
                continue
            uri = ctx.get("uri", "")
            if not uri or uri in ordered_uris:
                continue
            if not (uri.split(":")[-1] if ":" in uri else ""):
                continue
            ordered_uris.append(uri)
            if len(ordered_uris) >= limit:
                break

        def _fetch(uri: str) -> dict:
            pid = uri.split(":")[-1]
            try:
                pdata = sp.playlist(pid, fields="id,name,images,tracks.total,owner.display_name")
                return {
                    "name": pdata.get("name", "") or "Untitled",
                    "uri": uri,
                    "id": pid,
                    "cover": (pdata.get("images") or [{}])[0].get("url"),
                    "track_count": (pdata.get("tracks") or {}).get("total", 0),
                    "owner": (pdata.get("owner") or {}).get("display_name"),
                }
            except Exception as e:
                # Try a tighter retry asking only for the name — some Spotify-
                # editorial playlists return on minimal queries even when full
                # ones 404. If even that fails, label it clearly so the tile
                # doesn't show the raw URI as the name.
                try:
                    pdata = sp.playlist(pid, fields="name")
                    label = pdata.get("name", "") or "Playlist (unavailable)"
                except Exception:
                    label = "Playlist (unavailable)"
                return {
                    "name": label,
                    "uri": uri,
                    "id": pid,
                    "cover": None,
                    "track_count": 0,
                    "owner": None,
                    "_error": type(e).__name__,
                }

        # Sequential fetch with 150ms stagger — avoids the 4-simultaneous-request
        # burst that triggers Spotify's per-Client-ID rate limiter. The playlist
        # cover art fetches are already behind a 120s cache so this path runs
        # infrequently; the latency cost (~600ms for 4 playlists) is acceptable.
        results = []
        for uri in ordered_uris:
            results.append(_fetch(uri))
            _time.sleep(0.15)
        return results
    except Exception as e:
        if _maybe_trip_breaker(e):
            return RATE_LIMITED_SENTINEL  # type: ignore[return-value]
        return None


def _spotify_error_to_dict(e: Exception) -> dict:
    """Map a Spotify SDK exception to a structured agent-friendly dict.
    Without this, write-tool exceptions propagate as a traceback and the
    agent gives up with a generic error to the user."""
    msg = str(e)
    if "No active device" in msg or "NO_ACTIVE_DEVICE" in msg:
        return {
            "error": "no_active_device",
            "message": "Open Spotify and start any track first to register a device, then retry.",
        }
    if "PREMIUM_REQUIRED" in msg or "Premium" in msg:
        return {"error": "premium_required", "message": "Spotify Premium required for playback control."}
    if "404" in msg or "Resource not found" in msg:
        return {"error": "not_found", "message": "Spotify can't access this playlist (likely a Spotify editorial playlist locked to premium). Click Edit on the Moods tab to swap in one of your own playlists."}
    if "Token expired" in msg or "401" in msg:
        _reset_sp_instance()  # force singleton rebuild so next call gets a fresh auth
        return {"error": "auth", "message": "Spotify token expired — reconnect via /setup."}
    return {"error": "spotify_error", "message": msg[:200]}


def run_spotify_tool(name: str, inp: dict):
    # Check the circuit breaker before touching _sp() at all. Public getters
    # all do this; skipping it here would fire extra calls during a 429 backoff
    # window, which can reset the Retry-After clock on some Spotify quota
    # implementations and leave the user locked out longer.
    remaining = _check_rate_limited()
    if remaining > 0:
        import datetime as _dt
        # Py#2: %-I is GNU-only and fails on macOS Python; use %I + lstrip("0")
        retry_at = _dt.datetime.fromtimestamp(_time.time() + remaining).strftime("%I:%M %p").lstrip("0") or "0"
        return {"error": "rate_limited", "message": f"Spotify rate-limited — retry after {retry_at}"}

    sp = _sp()
    if name == "spotify_now_playing":
        return get_now_playing() or {"status": "nothing playing"}
    if name == "spotify_play_pause":
        try:
            current = sp.current_playback()
            if current and current.get("is_playing"):
                sp.pause_playback()
                return {"action": "paused"}
            sp.start_playback()
            return {"action": "playing"}
        except Exception as e:
            if "401" in str(e) or "Token expired" in str(e):
                _reset_sp_instance()
            return _spotify_error_to_dict(e)
    if name == "spotify_skip":
        try:
            sp.next_track()
            return {"action": "skipped"}
        except Exception as e:
            if "401" in str(e) or "Token expired" in str(e):
                _reset_sp_instance()
            return _spotify_error_to_dict(e)
    raise ValueError(f"Unknown spotify tool: {name}")
