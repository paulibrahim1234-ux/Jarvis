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
    import spotipy
    return spotipy.Spotify(auth_manager=_auth())


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
    except Exception:
        return None


def get_queue() -> list[dict] | None:
    """Upcoming tracks (requires user-read-playback-state)."""
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
    except Exception:
        return None


def get_playlists(limit: int = 20) -> list[dict] | None:
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
    except Exception:
        return None


def get_recently_played(limit: int = 10) -> list[dict] | None:
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
    except Exception:
        return None


def get_top_tracks(time_range: str = "short_term", limit: int = 8) -> list[dict]:
    """Get user's top tracks for the given time range (short_term/medium_term/long_term)."""
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
    except Exception:
        return []


def get_top_artists(time_range: str = "short_term", limit: int = 8) -> list[dict]:
    """Get user's top artists for the given time range."""
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
    except Exception:
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
    """
    try:
        sp = _sp()
        res = sp.current_user_recently_played(limit=50)
        items = res.get("items", []) if res else []
        seen: dict[str, dict] = {}
        for item in items:
            ctx = item.get("context") or {}
            if ctx.get("type") != "playlist":
                continue
            uri = ctx.get("uri", "")
            if not uri or uri in seen:
                continue
            pid = uri.split(":")[-1] if ":" in uri else ""
            if not pid:
                continue
            try:
                pdata = sp.playlist(pid, fields="id,name,images,tracks.total,owner.display_name")
                seen[uri] = {
                    "name": pdata.get("name", ""),
                    "uri": uri,
                    "id": pid,
                    "cover": (pdata.get("images") or [{}])[0].get("url"),
                    "track_count": (pdata.get("tracks") or {}).get("total", 0),
                    "owner": (pdata.get("owner") or {}).get("display_name"),
                }
            except Exception:
                # Fallback: minimal entry without cover
                seen[uri] = {
                    "name": uri,
                    "uri": uri,
                    "id": pid,
                    "cover": None,
                    "track_count": 0,
                    "owner": None,
                }
            if len(seen) >= limit:
                break
        return list(seen.values())
    except Exception:
        return None


def run_spotify_tool(name: str, inp: dict):
    sp = _sp()
    if name == "spotify_now_playing":
        return get_now_playing() or {"status": "nothing playing"}
    if name == "spotify_play_pause":
        current = sp.current_playback()
        if current and current.get("is_playing"):
            sp.pause_playback()
            return {"action": "paused"}
        sp.start_playback()
        return {"action": "playing"}
    if name == "spotify_skip":
        sp.next_track()
        return {"action": "skipped"}
    raise ValueError(f"Unknown spotify tool: {name}")
