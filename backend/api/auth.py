"""
Auth endpoints for Outlook (Microsoft device flow) and Spotify (OAuth callback).
"""

from html import escape as _h

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter(prefix="/auth")


# ── Microsoft / Outlook ───────────────────────────────────────────────────────

@router.get("/microsoft")
def microsoft_auth():
    """
    Start the Microsoft device code flow.
    Open this URL in the browser; it will display a code and login URL.
    """
    try:
        from tools.outlook import start_device_flow
        result = start_device_flow()
        if result.get("already_authenticated"):
            return HTMLResponse(_page("✅ Already authenticated with Microsoft Outlook.", success=True))
        url_safe = _h(str(result.get('url', '')))
        code_safe = _h(str(result.get('code', '')))
        raw_safe = _h(str(result.get('raw', '')))
        return HTMLResponse(_page(
            "Microsoft Outlook Auth",
            body=f"""
            <p>Open <a href="{url_safe}" target="_blank">{url_safe}</a> and enter this code:</p>
            <h2 style="letter-spacing:.3em;font-family:monospace;font-size:2rem">{code_safe}</h2>
            <p style="color:#888;font-size:.85rem">{raw_safe}</p>
            <p>After signing in, Jarvis will have access to your Outlook email and calendar.</p>
            """,
        ))
    except Exception as e:
        err_str = str(e)
        setup_hint = (
            '<p style="margin-top:1rem">Visit <a href="/setup">/setup</a> to enter your Microsoft Client ID.</p>'
            if "MS_CLIENT_ID" in err_str else ""
        )
        return HTMLResponse(_page(f"⚠️ {_h(err_str)}", body=setup_hint, success=False))


@router.get("/microsoft/status")
def microsoft_status():
    from tools.outlook import is_authenticated
    return {"authenticated": is_authenticated()}


# ── Spotify ───────────────────────────────────────────────────────────────────

@router.get("/spotify")
def spotify_auth():
    """Redirect to Spotify authorization page."""
    try:
        from tools.spotify import get_auth_url
        url = get_auth_url()
        return RedirectResponse(url)
    except Exception as e:
        return HTMLResponse(_page(f"⚠️ {_h(str(e))}", success=False))


@router.get("/spotify/callback")
def spotify_callback(code: str = "", error: str = ""):
    if error:
        return HTMLResponse(_page(f"⚠️ Spotify auth error: {_h(str(error))}", success=False))
    try:
        from tools.spotify import handle_callback
        ok = handle_callback(code)
        if ok:
            return HTMLResponse(_page("✅ Spotify connected! You can close this tab.", success=True))
        return HTMLResponse(_page("⚠️ Token exchange failed — try again.", success=False))
    except Exception as e:
        return HTMLResponse(_page(f"⚠️ {_h(str(e))}", success=False))


@router.get("/spotify/status")
def spotify_status():
    from tools.spotify import is_authenticated
    return {"authenticated": is_authenticated()}


# ── Status overview ───────────────────────────────────────────────────────────

# ── Claude credential health probe ────────────────────────────────────────────
# Cache the live-probe result so periodic /auth/status calls from the topbar
# don't burn a request per check. 5 min strikes the right balance: long
# enough to be cheap, short enough that an expired token surfaces quickly.

import time as _t
_CLAUDE_PROBE_CACHE: dict = {"checked_at": 0.0, "ok": None, "error": None}
_CLAUDE_PROBE_TTL = 300.0  # seconds


def _probe_claude(force: bool = False, allow_refresh: bool = True) -> dict:
    """Make a 1-token request to Anthropic to verify credentials are live.

    Returns {ok: bool, error: str | None, checked_at: float}.
    Cached for _CLAUDE_PROBE_TTL seconds unless force=True.

    On a 401, if `allow_refresh=True` we attempt one OAuth refresh and
    retry — so a freshly-expired token heals itself on the next probe
    rather than showing "invalid_credential" until the user notices.

    A successful return DOES NOT just mean "token exists" — it confirms
    Anthropic accepts it. This is the difference between the old
    `bool(env_var_set)` check (which let expired tokens look healthy) and
    a real liveness probe.
    """
    import os
    now = _t.time()
    if not force and _CLAUDE_PROBE_CACHE["checked_at"] and \
       (now - _CLAUDE_PROBE_CACHE["checked_at"]) < _CLAUDE_PROBE_TTL:
        return {
            "ok": _CLAUDE_PROBE_CACHE["ok"],
            "error": _CLAUDE_PROBE_CACHE["error"],
            "checked_at": _CLAUDE_PROBE_CACHE["checked_at"],
            "cached": True,
        }
    raw = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if not raw:
        result = {"ok": False, "error": "no_credential", "checked_at": now}
    else:
        try:
            from agent import jarvis as _jarvis
            # 1-token request — cheapest call that exercises real auth.
            _jarvis.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            )
            result = {"ok": True, "error": None, "checked_at": now}
        except Exception as e:
            msg = str(e)
            if "401" in msg or "authentication_error" in msg or "Invalid authentication" in msg:
                # Try ONE OAuth refresh before reporting invalid. This is
                # the auto-heal path: probe runs every 2 min from the
                # frontend, so an expired token heals on the next tick
                # without any user action.
                if allow_refresh:
                    try:
                        from agent import claude_oauth
                        result_r = claude_oauth.refresh_now(force=True)
                        if result_r.get("ok") and result_r.get("action") == "refreshed":
                            # Recursively re-probe ONCE without allowing
                            # another refresh (avoids infinite loops if
                            # the new token is somehow also bad).
                            return _probe_claude(force=True, allow_refresh=False)
                    except Exception:
                        pass
                code = "invalid_credential"
            elif "429" in msg:
                code = "rate_limited"  # token works but throttled — treat as ok
                _CLAUDE_PROBE_CACHE.update(checked_at=now, ok=True, error=None)
                return {"ok": True, "error": "rate_limited", "checked_at": now, "cached": False}
            else:
                code = "unknown"
            result = {"ok": False, "error": code, "error_detail": msg[:200], "checked_at": now}
    _CLAUDE_PROBE_CACHE.update(checked_at=now, ok=result["ok"], error=result.get("error"))
    return {**result, "cached": False}


@router.get("/anthropic/oauth-status")
def anthropic_oauth_status():
    """Diagnostics: where is the credential stored, when does it expire,
    is the auto-refresher running?"""
    try:
        from agent.claude_oauth import status
        return status()
    except Exception as e:
        return {"error": str(e)}


@router.post("/anthropic/refresh")
def anthropic_force_refresh(request: Request):
    """Force an OAuth refresh now. Useful after manually rotating tokens
    or as a manual unstick if the auto-refresher hasn't fired yet."""
    from api._security import _require_local_origin
    _require_local_origin(request)
    from agent import claude_oauth
    return claude_oauth.refresh_now(force=True)


@router.get("/anthropic/status")
def anthropic_status(force: bool = False):
    """Live credential probe + cached result.
    Call ?force=true to bypass the 5-min cache (e.g. after updating the
    credential via /setup/credentials)."""
    return _probe_claude(force=force)


@router.get("/status")
def all_status():
    import os
    from tools.spotify import is_authenticated as sp_ok

    def _outlook_ok():
        """Check Outlook Classic desktop first; fall back to MS Graph token."""
        try:
            from tools.desktop_apps import _count_outlook_accounts
            counts = _count_outlook_accounts()
            total = sum(counts.get(k, 0) for k in ("exchange", "imap", "pop"))
            if total > 0:
                return True
        except Exception:
            pass
        try:
            from tools.outlook import is_authenticated as ms_ok
            return bool(ms_ok())
        except Exception:
            return False

    def _anki_ok():
        try:
            import httpx
            r = httpx.post(
                os.getenv("ANKICONNECT_URL", "http://localhost:8765"),
                json={"action": "version", "version": 6}, timeout=1,
            )
            return r.status_code == 200
        except Exception:
            return False

    # Use cached live-probe result so /auth/status stays cheap.
    claude_probe = _probe_claude(force=False)
    return {
        "claude": bool(claude_probe.get("ok")),
        "claude_error": claude_probe.get("error"),
        "outlook": _outlook_ok(),
        "spotify": sp_ok(),
        "anki": _anki_ok(),
    }


def _page(title: str, body: str = "", success: bool | None = None) -> str:
    color = "#22c55e" if success else ("#ef4444" if success is False else "#fff")
    return f"""<!DOCTYPE html>
<html>
<head><title>Jarvis Auth</title>
<style>
  body {{ font-family: system-ui; background: #0e0e14; color: #e2e8f0;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ max-width: 480px; padding: 2.5rem; background: #1a1a2e; border-radius: 1rem; }}
  h1 {{ color: {color}; margin-top: 0; }}
  a {{ color: #60a5fa; }}
</style>
</head>
<body><div class="card">
  <h1>{title}</h1>
  {body}
</div></body>
</html>"""
