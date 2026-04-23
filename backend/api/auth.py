"""
Auth endpoints for Outlook (Microsoft device flow) and Spotify (OAuth callback).
"""

from fastapi import APIRouter
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
        return HTMLResponse(_page(
            "Microsoft Outlook Auth",
            body=f"""
            <p>Open <a href="{result['url']}" target="_blank">{result['url']}</a> and enter this code:</p>
            <h2 style="letter-spacing:.3em;font-family:monospace;font-size:2rem">{result['code']}</h2>
            <p style="color:#888;font-size:.85rem">{result.get('raw','')}</p>
            <p>After signing in, Jarvis will have access to your Outlook email and calendar.</p>
            """,
        ))
    except Exception as e:
        return HTMLResponse(_page(f"⚠️ {e}", success=False))


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
        return HTMLResponse(_page(f"⚠️ {e}", success=False))


@router.get("/spotify/callback")
def spotify_callback(code: str = "", error: str = ""):
    if error:
        return HTMLResponse(_page(f"⚠️ Spotify auth error: {error}", success=False))
    try:
        from tools.spotify import handle_callback
        ok = handle_callback(code)
        if ok:
            return HTMLResponse(_page("✅ Spotify connected! You can close this tab.", success=True))
        return HTMLResponse(_page("⚠️ Token exchange failed — try again.", success=False))
    except Exception as e:
        return HTMLResponse(_page(f"⚠️ {e}", success=False))


@router.get("/spotify/status")
def spotify_status():
    from tools.spotify import is_authenticated
    return {"authenticated": is_authenticated()}


# ── Status overview ───────────────────────────────────────────────────────────

@router.get("/status")
def all_status():
    import os
    from tools.outlook import is_authenticated as ms_ok
    from tools.spotify import is_authenticated as sp_ok

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

    return {
        "claude": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")),
        "outlook": ms_ok(),
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
