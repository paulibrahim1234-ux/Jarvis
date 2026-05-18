"""
Jarvis backend — FastAPI entry point.

Production: cd backend && .venv/bin/python3 main.py
Dev (hot-reload): cd backend && JARVIS_DEV=1 .venv/bin/python3 main.py
  OR:             cd backend && .venv/bin/python3 -m uvicorn main:app --reload --port 8000

IMPORTANT: Backend has NO hot-reload in production mode.
After editing any backend .py file, restart with:
  kill <pid>  (or Ctrl-C) then re-run.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# Dedicated executor for slow AppleScript warmup tasks so they never compete
# with FastAPI's default threadpool during startup.
_WARMUP_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jarvis-warmup")
# Strong reference to the warmup future so it isn't discarded; also lets us
# log unexpected failures (the previous code dropped the future on the
# floor, so any AppleScript regression silently swallowed its traceback).
_WARMUP_FUTURE = None


def _run_warmup():
    """Populate caches for the four slowest endpoints in the background.

    Called once at startup via asyncio.get_event_loop().run_in_executor so
    it never blocks the event loop or steals threads from request handling.
    Each compute function is guarded by its own Semaphore inside _cached(),
    so duplicate in-flight calls are harmlessly dropped.
    """
    try:
        from api.widgets import (
            _compute_calendar,
            _compute_email,
            _compute_email_folders,
            _compute_study_streak_days,
            _cached,
            _SEM_CALENDAR,
            _SEM_EMAIL,
            _SEM_EMAIL_FOLDERS,
            _SEM_STUDY_STREAK,
        )
        import concurrent.futures

        tasks = [
            # WHY 60 (not 600): the /widgets/calendar endpoint calls
            # _cached("calendar", 60, ...).  A mismatched startup TTL meant a
            # stale empty result (e.g. from an icalBuddy race at startup) would
            # survive for 10 minutes instead of expiring in 60 s when the
            # endpoint next recomputes it, causing "0 events today" all morning.
            #
            # WHY sem=None for calendar: _SEM_CALENDAR is designed to prevent
            # N concurrent HTTP requests from stacking up AppleScript calls.
            # The warmup runs exactly once at startup — no concurrent pressure.
            # Passing _SEM_CALENDAR here caused _compute_calendar (which spawns
            # its own internal ThreadPoolExecutor for Outlook + AppleScript) to
            # hold the semaphore for up to 18 s.  During that window every SWR
            # background refresh attempt saw the sem locked (blocking=False →
            # skip) and gave up, leaving the stale empty cache entry forever.
            # Using None lets warmup compute freely while the endpoint's own
            # _cached calls still use _SEM_CALENDAR normally.
            ("calendar",      60,   _compute_calendar,         None),
            ("email::::",     60,   lambda: _compute_email(),  _SEM_EMAIL),
            ("email_folders", 300,  _compute_email_folders,    _SEM_EMAIL_FOLDERS),
            ("study_streak",  1800, _compute_study_streak_days, _SEM_STUDY_STREAK),
        ]

        # Run all four AppleScript calls in parallel, capped at 4 workers.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futs = [
                pool.submit(_cached, key, ttl, fn, sem)
                for key, ttl, fn, sem in tasks
            ]
            concurrent.futures.wait(futs, timeout=60)

        # Warm /widgets/briefing — this is the most expensive endpoint
        # (parallel Anthropic calls + multiple AppleScript fetches, ~3-5s
        # cold). Calling the route handler directly populates its top-level
        # `_CACHE["briefing_full_v1"]` so the user's first dashboard mount
        # serves from cache. The Response stub is throwaway — handler only
        # uses it to set Cache-Control which is irrelevant during warmup.
        try:
            from api.widgets import briefing_widget as _briefing_widget
            from fastapi import Response as _Response
            _briefing_widget(_Response())
        except Exception:
            pass
    except Exception:
        # Warmup is best-effort; never crash the server.
        pass


def _on_warmup_done(fut):
    """Surface warmup failures so silent regressions are visible in logs."""
    try:
        exc = fut.exception()
    except Exception:
        return
    if exc is not None:
        try:
            import logging
            logging.getLogger("jarvis.startup").warning(
                "Warmup future failed: %r", exc
            )
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kick off cache warmup without blocking server startup.
    global _WARMUP_FUTURE
    loop = asyncio.get_running_loop()
    _WARMUP_FUTURE = loop.run_in_executor(_WARMUP_EXECUTOR, _run_warmup)
    _WARMUP_FUTURE.add_done_callback(_on_warmup_done)

    # Start the Claude OAuth auto-refresher. This:
    #   1. Eagerly refreshes the access token RIGHT NOW if it's expired
    #      or near expiry (within 30 min) — handles the "backend boots
    #      after a long absence" case so chat is healthy from request 1.
    #   2. Launches a daemon thread that polls every 60s and proactively
    #      refreshes when there's <30 min of headroom left, so a user
    #      mid-chat never feels a 401.
    # The eager part runs synchronously here (uses Keychain + a single
    # HTTPS POST — fast, ~300 ms). The thread is a daemon so backend
    # shutdown doesn't hang on it.
    try:
        from agent.claude_oauth import start_background_refresher
        start_background_refresher()
    except Exception:
        # Best-effort. If Keychain access is denied or refresh fails,
        # the existing /auth/anthropic/status probe still surfaces the
        # problem and the user can update the token via /setup.
        pass

    yield
    _WARMUP_EXECUTOR.shutdown(wait=False)


app = FastAPI(title="Jarvis", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.chat import router as chat_router
from api.widgets import router as widgets_router
from api.auth import router as auth_router
from api.setup import router as setup_router
from api.apps import router as apps_router
from api.voice import router as voice_router

app.include_router(chat_router)
app.include_router(widgets_router)
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(apps_router)
app.include_router(voice_router)


@app.get("/health")
async def health():
    """Fast health probe — must respond within the frontend's 1.5s timeout.

    Rules:
    - AnkiConnect HTTP check is capped at 500ms; returns False on timeout.
    - Outlook/Spotify probes run in a threadpool with a 400ms limit each.
    - No AppleScript is ever invoked here.
    """
    import httpx

    anki_ok = False
    try:
        # asyncio-native HTTP call so it doesn't block the event loop.
        async with httpx.AsyncClient() as client:
            r = await asyncio.wait_for(
                client.post(
                    os.getenv("ANKICONNECT_URL", "http://localhost:8765"),
                    json={"action": "version", "version": 6},
                    timeout=0.5,
                ),
                timeout=0.5,
            )
            anki_ok = r.status_code == 200
    except Exception:
        pass

    # Auth checks run in a threadpool so I/O doesn't touch the event loop.
    # Outlook check: prefer desktop AppleScript account count (fast, no OAuth
    # needed) so health reflects Outlook Classic being open and signed in.
    # Falls back to MS Graph token check when desktop call fails.
    def _auth_checks():
        from tools.spotify import is_authenticated as _sp_ok
        outlook_ok = False
        try:
            from tools.desktop_apps import _count_outlook_accounts
            counts = _count_outlook_accounts()
            total = sum(counts.get(k, 0) for k in ("exchange", "imap", "pop"))
            outlook_ok = total > 0
        except Exception:
            try:
                from tools.outlook import is_authenticated as _ms_ok
                outlook_ok = bool(_ms_ok())
            except Exception:
                pass
        return outlook_ok, bool(_sp_ok())

    loop = asyncio.get_running_loop()
    outlook_ok = False
    spotify_ok = False
    try:
        outlook_ok, spotify_ok = await asyncio.wait_for(
            loop.run_in_executor(None, _auth_checks),
            timeout=1.0,
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "claude": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")),
        "anki": anki_ok,
        "outlook": outlook_ok,
        "spotify": spotify_ok,
    }


if __name__ == "__main__":
    import uvicorn
    dev_mode = os.getenv("JARVIS_DEV", "").strip() in ("1", "true", "yes")
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=dev_mode,
        reload_dirs=["./"] if dev_mode else None,
    )
