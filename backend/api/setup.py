"""
/setup — credential setup UI.
A browser form to enter Spotify / Microsoft credentials without editing .env manually.
POST /setup/credentials saves them and triggers the OAuth flow.
"""

import os
import re
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

_ENV_FILE = Path(__file__).parent.parent / ".env"

_ALLOWED = {
    "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI",
    "MS_CLIENT_ID", "MS_TENANT_ID",
}


# ── GET /setup ────────────────────────────────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
def setup_page():
    sp_id = bool(os.getenv("SPOTIFY_CLIENT_ID"))
    sp_sec = bool(os.getenv("SPOTIFY_CLIENT_SECRET"))
    ms_id = bool(os.getenv("MS_CLIENT_ID"))

    try:
        from tools.spotify import is_authenticated as sp_auth
        sp_ok = sp_auth()
    except Exception:
        sp_ok = False

    try:
        from tools.outlook import is_authenticated as ms_auth
        ms_ok = ms_auth()
    except Exception:
        ms_ok = False

    try:
        import httpx
        r = httpx.post(
            os.getenv("ANKICONNECT_URL", "http://localhost:8765"),
            json={"action": "version", "version": 6}, timeout=1,
        )
        anki_ok = r.status_code == 200
    except Exception:
        anki_ok = False

    claude_ok = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN"))

    def badge(ok: bool) -> str:
        return (
            '<span style="color:#22c55e">✅ Connected</span>'
            if ok else
            '<span style="color:#f59e0b">⚠️ Not set</span>'
        )

    return HTMLResponse(_PAGE.format(
        sp_id_badge=badge(sp_id),
        sp_sec_badge=badge(sp_sec),
        sp_auth_badge=badge(sp_ok),
        ms_id_badge=badge(ms_id),
        ms_auth_badge=badge(ms_ok),
        anki_badge=badge(anki_ok),
        claude_badge=badge(claude_ok),
        sp_id_val="" if not sp_id else "••••••••",
        sp_sec_val="" if not sp_sec else "••••••••",
        ms_id_val="" if not ms_id else "••••••••",
    ))


# ── POST /setup/credentials ───────────────────────────────────────────────────

@router.post("/setup/credentials")
def save_credentials(
    service: str = Form(...),
    spotify_client_id: str = Form(""),
    spotify_client_secret: str = Form(""),
    ms_client_id: str = Form(""),
    ms_tenant_id: str = Form(""),
):
    saved = []

    if service == "spotify":
        if spotify_client_id.strip():
            _write_env("SPOTIFY_CLIENT_ID", spotify_client_id.strip())
            os.environ["SPOTIFY_CLIENT_ID"] = spotify_client_id.strip()
            saved.append("SPOTIFY_CLIENT_ID")
        if spotify_client_secret.strip():
            _write_env("SPOTIFY_CLIENT_SECRET", spotify_client_secret.strip())
            os.environ["SPOTIFY_CLIENT_SECRET"] = spotify_client_secret.strip()
            saved.append("SPOTIFY_CLIENT_SECRET")
        if saved:
            return RedirectResponse("/auth/spotify", status_code=303)

    if service == "microsoft":
        if ms_client_id.strip():
            _write_env("MS_CLIENT_ID", ms_client_id.strip())
            os.environ["MS_CLIENT_ID"] = ms_client_id.strip()
            saved.append("MS_CLIENT_ID")
        if ms_tenant_id.strip():
            _write_env("MS_TENANT_ID", ms_tenant_id.strip())
            os.environ["MS_TENANT_ID"] = ms_tenant_id.strip()
            saved.append("MS_TENANT_ID")
        if saved:
            return RedirectResponse("/auth/microsoft", status_code=303)

    return RedirectResponse("/setup", status_code=303)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_env(key: str, value: str):
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    found = False
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            if re.match(rf"^{re.escape(key)}\s*=", line):
                lines.append(f'{key}="{value}"')
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f'{key}="{value}"')
    _ENV_FILE.write_text("\n".join(lines) + "\n")


# ── HTML template ─────────────────────────────────────────────────────────────

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jarvis Setup</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    background: #0e0e14;
    color: #e2e8f0;
    margin: 0;
    min-height: 100vh;
    padding: 2rem 1rem;
  }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .25rem; }}
  .sub {{ color: #64748b; margin-bottom: 2rem; font-size: .9rem; }}
  .card {{
    background: #1a1a2e;
    border: 1px solid #2d2d44;
    border-radius: .75rem;
    padding: 1.5rem;
    margin-bottom: 1.25rem;
  }}
  .card h2 {{ margin: 0 0 .25rem; font-size: 1.05rem; display: flex; align-items: center; gap: .5rem; }}
  .card p {{ color: #94a3b8; font-size: .85rem; margin: .25rem 0 1rem; }}
  .status-row {{ display: flex; gap: 1.5rem; margin-bottom: 1rem; font-size: .85rem; }}
  label {{ display: block; font-size: .8rem; color: #94a3b8; margin-bottom: .3rem; }}
  input[type=text], input[type=password] {{
    width: 100%;
    padding: .5rem .75rem;
    background: #0e0e14;
    border: 1px solid #2d2d44;
    border-radius: .4rem;
    color: #e2e8f0;
    font-size: .9rem;
    margin-bottom: .75rem;
    outline: none;
  }}
  input:focus {{ border-color: #6366f1; }}
  .hint {{ font-size: .75rem; color: #475569; margin-top: -.5rem; margin-bottom: .75rem; }}
  a.hint-link {{ color: #60a5fa; }}
  button {{
    background: #6366f1;
    color: #fff;
    border: none;
    border-radius: .4rem;
    padding: .55rem 1.25rem;
    font-size: .9rem;
    cursor: pointer;
    font-weight: 500;
  }}
  button:hover {{ background: #4f46e5; }}
  .anki-steps {{ list-style: decimal; padding-left: 1.2rem; color: #94a3b8; font-size: .85rem; line-height: 1.8; }}
  .anki-steps code {{
    background: #0e0e14;
    border: 1px solid #2d2d44;
    border-radius: .25rem;
    padding: .1rem .35rem;
    font-family: monospace;
    font-size: .8rem;
  }}
  .section-ok {{ opacity: .6; }}
</style>
</head>
<body>
<div class="container">
  <h1>⚡ Jarvis Setup</h1>
  <p class="sub">Configure integrations. Credentials are saved to <code>backend/.env</code> and never leave your machine.</p>

  <!-- Status overview -->
  <div class="card">
    <h2>Status</h2>
    <div class="status-row">
      <span>🤖 Claude: {claude_badge}</span>
      <span>🎵 Spotify: {sp_auth_badge}</span>
      <span>📧 Microsoft: {ms_auth_badge}</span>
      <span>🃏 Anki: {anki_badge}</span>
    </div>
  </div>

  <!-- Spotify -->
  <div class="card">
    <h2>🎵 Spotify</h2>
    <p>Create a free app at Spotify for Developers to get your Client ID and Secret.</p>
    <div class="status-row">
      <span>Client ID: {sp_id_badge}</span>
      <span>Secret: {sp_sec_badge}</span>
      <span>OAuth: {sp_auth_badge}</span>
    </div>
    <form method="post" action="/setup/credentials">
      <input type="hidden" name="service" value="spotify">
      <label>Client ID</label>
      <input type="password" name="spotify_client_id" placeholder="Paste Spotify Client ID" autocomplete="off">
      <p class="hint">
        Get it at <a class="hint-link" href="https://developer.spotify.com/dashboard" target="_blank">developer.spotify.com/dashboard</a>
        → Create App → set Redirect URI to <code>http://127.0.0.1:8000/auth/spotify/callback</code>
        (Spotify rejects <code>localhost</code> since 2025 — must use the IP form <code>127.0.0.1</code>)
      </p>
      <label>Client Secret</label>
      <input type="password" name="spotify_client_secret" placeholder="Paste Spotify Client Secret" autocomplete="off">
      <button type="submit">Save &amp; Connect Spotify →</button>
    </form>
  </div>

  <!-- Microsoft / Outlook — macOS-native by default, Azure optional -->
  <div class="card">
    <h2>📧 Microsoft / Outlook</h2>
    <p>
      <strong>No credentials required.</strong> Jarvis reads Outlook mail + calendar directly from
      the macOS Outlook app (or Apple Mail / Apple Calendar — whichever has your account synced)
      via AppleScript. Just make sure the app is <em>open and logged in</em>.
    </p>
    <p class="hint" style="margin-top:6px">
      Verify: <code>osascript -e 'tell application "Microsoft Outlook" to return name of first mail account'</code>
      should print your account name. If you see an Automation-permission prompt, click OK — that's the one-time grant.
    </p>
    <details style="margin-top:10px">
      <summary style="cursor:pointer;color:#94a3b8">Optional: Azure AD app (for richer Graph access if you have it)</summary>
      <div class="status-row" style="margin-top:10px">
        <span>Client ID: {ms_id_badge}</span>
        <span>OAuth: {ms_auth_badge}</span>
      </div>
      <form method="post" action="/setup/credentials">
        <input type="hidden" name="service" value="microsoft">
        <label>Azure App Client ID</label>
        <input type="password" name="ms_client_id" placeholder="Paste Azure Application (client) ID" autocomplete="off">
        <p class="hint">
          Get it at <a class="hint-link" href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank">portal.azure.com</a>
          → App registrations → New → Accounts in any org → add Mobile/Desktop redirect
          <code>https://login.microsoftonline.com/common/oauth2/nativeclient</code>
          → API permissions → add Mail.Read, Mail.Send, Calendars.Read (delegated).
          Many school/work tenants block this — the macOS path above is always available.
        </p>
        <label>Tenant ID (leave blank for personal/any account)</label>
        <input type="text" name="ms_tenant_id" placeholder="common" autocomplete="off">
        <button type="submit">Save &amp; Connect Microsoft →</button>
      </form>
    </details>
  </div>

  <!-- Anki -->
  <div class="card">
    <h2>🃏 Anki</h2>
    <p>No credentials needed — Anki uses a local add-on.</p>
    <ol class="anki-steps">
      <li>Open <strong>Anki</strong></li>
      <li>Tools → Add-ons → Get Add-ons → enter code <code>2055492159</code></li>
      <li>Restart Anki</li>
      <li>Status above should turn green automatically</li>
    </ol>
    <p style="font-size:.8rem;color:#475569">AnkiConnect runs on port 8765. Make sure no other process is using it.</p>
  </div>

  <!-- iMessage -->
  <div class="card">
    <h2>💬 iMessage</h2>
    <p>No credentials needed — reads your local Messages database.</p>
    <ol class="anki-steps">
      <li>System Settings → Privacy &amp; Security → Full Disk Access</li>
      <li>Add Terminal (or your Python interpreter) to the list</li>
    </ol>
  </div>

</div>
</body>
</html>
"""
