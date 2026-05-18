"""
/setup — credential setup UI.
A browser form to enter Spotify / Microsoft credentials without editing .env manually.
POST /setup/credentials saves them and triggers the OAuth flow.
"""

import os
import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from api._security import _require_local_origin
from tools.computer import _write_env as _write_env_unsafe

# Sec#9: validate Anthropic token format before writing to .env / Keychain.
# Accepts both API keys (sk-ant-api...) and OAuth tokens (sk-ant-oat...).
# Rejects obviously invalid strings early — catches copy-paste mistakes and
# prompt-injection attempts that try to smuggle env-breaking chars into the
# value (newlines, equals signs, etc. are excluded by the character class).
_TOKEN_RE = re.compile(r"^sk-ant-(api|oat)\d+-[A-Za-z0-9_-]{20,}$")

router = APIRouter()

# Allowlist of env keys this module may write.
# The old _ALLOWED set was defined but never enforced — all writes were
# hardcoded literals so the guard was dead code. Enforcing it here means
# a future refactor that introduces user-controlled key routing is caught
# at the write site rather than silently persisting arbitrary env vars.
_ALLOWED_KEYS: frozenset[str] = frozenset({
    "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REDIRECT_URI",
    "MS_CLIENT_ID", "MS_TENANT_ID",
    "UWORLD_USERNAME", "UWORLD_PASSWORD",
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
})


def _write_env(key: str, value: str) -> None:
    """Write an env key to .env — raises ValueError if key is not allowlisted.

    Wraps tools.computer._write_env with an explicit guard so that if a
    future refactor accidentally passes a user-controlled key here, it fails
    loudly instead of writing arbitrary environment variables to .env.
    """
    if key not in _ALLOWED_KEYS:
        raise ValueError(f"Refusing to write env key not in allowlist: {key}")
    _write_env_unsafe(key, value)


# ── GET /setup ────────────────────────────────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
def setup_page():
    sp_id = bool(os.getenv("SPOTIFY_CLIENT_ID"))
    sp_sec = bool(os.getenv("SPOTIFY_CLIENT_SECRET"))
    ms_id = bool(os.getenv("MS_CLIENT_ID"))
    uw_user = bool(os.getenv("UWORLD_USERNAME"))
    uw_pass = bool(os.getenv("UWORLD_PASSWORD"))

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

    # Live probe — actually try the credential against Anthropic. The old
    # bool(env_var_set) check let expired tokens look healthy until the
    # user tried to chat. /auth/anthropic/status caches the result for
    # 5 min so loading /setup is still fast.
    try:
        from api.auth import _probe_claude
        claude_ok = bool(_probe_claude(force=False).get("ok"))
    except Exception:
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
        uw_user_badge=badge(uw_user),
        uw_pass_badge=badge(uw_pass),
    ))


# ── POST /setup/credentials ───────────────────────────────────────────────────

@router.post("/setup/credentials")
def save_credentials(
    request: Request,
    service: str = Form(...),
    spotify_client_id: str = Form(""),
    spotify_client_secret: str = Form(""),
    ms_client_id: str = Form(""),
    ms_tenant_id: str = Form(""),
    uworld_username: str = Form(""),
    uworld_password: str = Form(""),
    anthropic_token: str = Form(""),
):
    _require_local_origin(request)
    saved = []

    # ── Claude / Anthropic ────────────────────────────────────────────────
    # Accept either an API key (sk-ant-api...) or an OAuth token (sk-ant-oat...).
    # The agent.jarvis client distinguishes them by prefix and uses the
    # right auth header. After writing, we hot-reload the in-memory clients
    # so chat works WITHOUT a backend restart.
    if service == "claude":
        token = anthropic_token.strip()
        if token:
            # Sec#9: reject tokens that don't match the expected format before
            # writing. This catches copy-paste mistakes (e.g. pasting a URL or
            # a truncated token) and prevents env-file injection via embedded
            # newlines or equals signs (the regex character class excludes them).
            if not _TOKEN_RE.match(token):
                return HTMLResponse(
                    "<h2>Invalid token format.</h2>"
                    "<p>Expected <code>sk-ant-api…</code> or <code>sk-ant-oat…</code>. "
                    "<a href='/setup'>Go back</a></p>",
                    status_code=400,
                )
            if token.startswith("sk-ant-oat"):
                _write_env("CLAUDE_CODE_OAUTH_TOKEN", token)
                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
                # Clear the API-key var so it doesn't shadow the new OAuth token
                # (the resolver picks ANTHROPIC_API_KEY first).
                os.environ.pop("ANTHROPIC_API_KEY", None)
                _write_env("ANTHROPIC_API_KEY", "")
                saved.append("CLAUDE_CODE_OAUTH_TOKEN")
            else:
                _write_env("ANTHROPIC_API_KEY", token)
                os.environ["ANTHROPIC_API_KEY"] = token
                saved.append("ANTHROPIC_API_KEY")
            # Hot-reload the Anthropic clients so chat picks up the new
            # credential without a backend restart. Also bust the auth probe
            # cache so /auth/status shows the live result on next call.
            try:
                from agent import jarvis as _jarvis
                _jarvis.reload_anthropic_clients()
            except Exception:
                pass
            try:
                from api.auth import _CLAUDE_PROBE_CACHE
                _CLAUDE_PROBE_CACHE.update(checked_at=0.0, ok=None, error=None)
            except Exception:
                pass
        return RedirectResponse("/setup", status_code=303)

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

    if service == "uworld":
        if uworld_username.strip():
            _write_env("UWORLD_USERNAME", uworld_username.strip())
            os.environ["UWORLD_USERNAME"] = uworld_username.strip()
            saved.append("UWORLD_USERNAME")
        if uworld_password.strip():
            _write_env("UWORLD_PASSWORD", uworld_password.strip())
            os.environ["UWORLD_PASSWORD"] = uworld_password.strip()
            saved.append("UWORLD_PASSWORD")
        # Always redirect back to setup (no separate OAuth flow needed)
        return RedirectResponse("/setup", status_code=303)

    return RedirectResponse("/setup", status_code=303)


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

  <!-- Claude / Anthropic -->
  <div class="card">
    <h2>🤖 Claude (chat)</h2>
    <p>
      Powers the chat panel. Paste either an <strong>API key</strong>
      (<code>sk-ant-api...</code> from <a class="hint-link" href="https://console.anthropic.com/settings/keys" target="_blank">console.anthropic.com</a>)
      OR a <strong>Claude Code OAuth token</strong> (<code>sk-ant-oat...</code>,
      run <code>claude</code> in your terminal and copy the token from
      <code>~/.claude/.credentials.json</code>).
    </p>
    <div class="status-row">
      <span>Auth: {claude_badge}</span>
    </div>
    <form method="post" action="/setup/credentials">
      <input type="hidden" name="service" value="claude">
      <label>API key OR OAuth token</label>
      <input type="password" name="anthropic_token" placeholder="sk-ant-api... or sk-ant-oat..." autocomplete="off">
      <p class="hint">
        Saved to <code>backend/.env</code>. Jarvis hot-reloads the Anthropic
        client in-process so chat works immediately — no backend restart needed.
      </p>
      <button type="submit">Save Claude Credential</button>
    </form>
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

  <!-- UWorld -->
  <div class="card">
    <h2>📚 UWorld QBank</h2>
    <p>
      <strong>Preferred:</strong> log into UWorld in Comet (your default browser) — the scraper will reuse your session.
      No password stored.<br>
      <strong>Fallback:</strong> enter credentials below so Jarvis can log in automatically
      if your Comet session expires.
    </p>
    <div style="background:#1e293b;border:1px solid #f59e0b44;border-radius:.5rem;padding:.75rem 1rem;margin-bottom:1rem;font-size:.82rem">
      <strong style="color:#f59e0b">One-time browser setup:</strong>
      In Comet, go to <strong>View → Developer → Allow JavaScript from Apple Events</strong>.
      Without this, the scraper cannot read page data from UWorld.
    </div>
    <div class="status-row">
      <span>Username: {uw_user_badge}</span>
      <span>Password: {uw_pass_badge}</span>
    </div>
    <form method="post" action="/setup/credentials">
      <input type="hidden" name="service" value="uworld">
      <label>UWorld Username / Email</label>
      <input type="password" name="uworld_username" placeholder="your@email.com" autocomplete="off">
      <p class="hint">Used only if Comet is not logged in. Stored in <code>backend/.env</code> — never sent anywhere.</p>
      <label>UWorld Password</label>
      <input type="password" name="uworld_password" placeholder="UWorld password" autocomplete="new-password">
      <button type="submit">Save UWorld Credentials</button>
    </form>
    <p style="margin-top:1rem;font-size:.8rem;color:#475569">
      After saving, log into UWorld in Comet and click <strong>Refresh</strong> in the QBank widget
      to pull your real test history.
    </p>
  </div>

</div>
</body>
</html>
"""
