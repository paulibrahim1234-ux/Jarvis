"""
Jarvis backend — FastAPI entry point.
Run: cd backend && source .venv/bin/activate && uvicorn main:app --reload
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
            ("calendar",      90,   _compute_calendar,         _SEM_CALENDAR),
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
    except Exception:
        # Warmup is best-effort; never crash the server.
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kick off cache warmup without blocking server startup.
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_WARMUP_EXECUTOR, _run_warmup)
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

app.include_router(chat_router)
app.include_router(widgets_router)
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(apps_router)


@app.get("/health")
async def health():
    """Fast health probe — must respond within the frontend's 1.5s timeout.

    Rules:
    - AnkiConnect HTTP check is capped at 500ms; returns False on timeout.
    - Outlook/Spotify probes run in a threadpool with a 400ms limit each.
    - No AppleScript is ever invoked here.
    """
    import httpx
    import concurrent.futures

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

    # Auth checks are pure token-file reads — fast. Run them in a threadpool
    # so any accidental I/O doesn't touch the event loop, and cap at 400ms.
    def _auth_checks():
        from tools.outlook import is_authenticated as _ms_ok
        from tools.spotify import is_authenticated as _sp_ok
        return bool(_ms_ok()), bool(_sp_ok())

    loop = asyncio.get_event_loop()
    outlook_ok = False
    spotify_ok = False
    try:
        outlook_ok, spotify_ok = await asyncio.wait_for(
            loop.run_in_executor(None, _auth_checks),
            timeout=0.4,
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
