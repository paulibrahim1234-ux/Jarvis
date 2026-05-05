"""
Claude OAuth auto-refresh.

Source of truth: macOS Keychain item `Claude Code-credentials` (the same
item Claude Code itself manages). The blob stored there is JSON:

    {
      "claudeAiOauth": {
        "accessToken": "sk-ant-oat01-...",
        "refreshToken": "sk-ant-ort01-...",
        "expiresAt": 1777272019302,    # ms since epoch
        "scopes": [...],
        "subscriptionType": "max",
        ...
      },
      "mcpOAuth": { ... }
    }

This module:
  - Reads the credential blob (Keychain primary, ~/.jarvis/anthropic_oauth.json fallback for non-Mac).
  - Refreshes the access token via console.anthropic.com when it's expired
    or near expiry, persisting the new pair back to all sources.
  - Calls agent.jarvis.reload_anthropic_clients() so the in-process clients
    pick up the new token without a backend restart.
  - Schedules a background thread that proactively refreshes ~30 min before
    expiry so a user who is mid-chat never feels a 401.

Why we don't trust the SDK's own retry: the Anthropic Python SDK has no
built-in OAuth refresh handling — it raises AuthenticationError on 401.
We catch that, refresh, and retry once.

Security notes:
  - Refresh tokens are sensitive. Keychain is encrypted at rest. The
    JSON fallback at ~/.jarvis/anthropic_oauth.json is chmod 600.
  - We never log the token text, only the prefix + expiry time.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoid a circular import at module load time
    pass

log = logging.getLogger("jarvis.claude_oauth")

# ── Constants ────────────────────────────────────────────────────────────────

# Public OAuth client ID for Claude Code (same one the official CLI uses).
CLAUDE_CODE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_ENDPOINT = "https://console.anthropic.com/v1/oauth/token"

# Refresh proactively when there's less than this much time left on the
# access token. 30 min gives plenty of room for a multi-turn chat session.
REFRESH_HEADROOM_SECONDS = 30 * 60

KEYCHAIN_SERVICE = "Claude Code-credentials"

# Filesystem fallback (non-Mac, or if Keychain access is denied).
JSON_FALLBACK_PATH = Path.home() / ".jarvis" / "anthropic_oauth.json"

# Mirror the active access token into backend/.env so the existing env-driven
# resolver in agent.jarvis works without Keychain plumbing on every read.
# Path is derived from this module's location so the backend works under
# any clone path (CI runner, different user account, etc.).
DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"


# ── Lock so concurrent 401s only refresh once ────────────────────────────────

_REFRESH_LOCK = threading.Lock()


# ── Read credential blob (Keychain → JSON fallback → env-only) ───────────────

def _read_keychain() -> Optional[dict]:
    """Return the parsed Keychain blob, or None on any failure (locked,
    missing item, non-Mac, etc.)."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception as e:  # pragma: no cover — Linux dev box, etc.
        log.debug("keychain read failed: %s", e)
        return None


def _read_json_fallback() -> Optional[dict]:
    if not JSON_FALLBACK_PATH.exists():
        return None
    try:
        with JSON_FALLBACK_PATH.open() as f:
            return json.load(f)
    except Exception as e:
        log.warning("json fallback corrupt: %s", e)
        return None


def _current_oauth() -> Optional[dict]:
    """Return the current {accessToken, refreshToken, expiresAt} dict.

    Order of preference: Keychain → JSON fallback → env-only (no refresh
    capability since refresh_token isn't in env by default).
    """
    blob = _read_keychain()
    if blob and isinstance(blob.get("claudeAiOauth"), dict):
        return blob["claudeAiOauth"]
    blob = _read_json_fallback()
    if blob and isinstance(blob.get("claudeAiOauth"), dict):
        return blob["claudeAiOauth"]
    # Env-only — refresh impossible without refresh_token. Return enough
    # info that callers can avoid attempting a refresh.
    access = os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if access:
        return {"accessToken": access, "refreshToken": "", "expiresAt": 0}
    return None


# ── Persist updated tokens everywhere ────────────────────────────────────────

def _write_keychain(blob: dict) -> bool:
    """Update the Keychain item in-place. Returns True on success."""
    try:
        # Need the original `acct` so we update rather than create a new entry.
        meta = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
            capture_output=True, text=True, timeout=5,
        )
        account = ""
        for line in meta.stdout.splitlines():
            line = line.strip()
            if line.startswith('"acct"'):
                val = line.split("=", 1)[1].strip().strip('"')
                if val.startswith("0x"):
                    try:
                        account = bytes.fromhex(val[2:].split(" ")[0]).decode()
                    except Exception:
                        account = ""
                else:
                    account = val
                break
        if not account:
            log.warning("keychain has no acct field; falling back to JSON store")
            return False
        subprocess.run(
            ["security", "add-generic-password", "-U",
             "-s", KEYCHAIN_SERVICE,
             "-a", account,
             "-w", json.dumps(blob, separators=(",", ":"))],
            check=True, timeout=5,
        )
        return True
    except Exception as e:
        log.warning("keychain write failed: %s", e)
        return False


def _write_json_fallback(blob: dict) -> None:
    """Atomic write — never leave the file in a partial state.

    A naive `open('w')` truncates immediately and the json.dump can be
    interrupted by SIGKILL/disk error/etc., leaving a 0-byte file.
    Reading that on next boot raises a JSON parse error, returns None,
    and the refresh token is permanently lost. The temp-file + rename
    dance gives us atomicity on the same filesystem (POSIX rename(2) is
    atomic), so the file is either the old contents or the new — never
    half-written.
    """
    import tempfile
    JSON_FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(JSON_FALLBACK_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(blob, f, separators=(",", ":"))
        os.replace(tmp, JSON_FALLBACK_PATH)
        os.chmod(JSON_FALLBACK_PATH, 0o600)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_dotenv(access_token: str) -> None:
    """Update CLAUDE_CODE_OAUTH_TOKEN= line in backend/.env.
    Idempotent: appends if missing, overwrites if present.

    Defense-in-depth: scrub any newline / CR from the token before writing.
    A literal newline would split the value across env lines and corrupt
    the next variable below it. Anthropic OAuth tokens are URL-safe base64
    so they should never legitimately contain these, but we strip rather
    than trust.
    """
    if not DOTENV_PATH.exists():
        return
    try:
        lines = DOTENV_PATH.read_text().splitlines()
    except Exception:
        return
    safe_token = access_token.replace("\n", "").replace("\r", "")
    new_lines = []
    seen = False
    for line in lines:
        if line.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
            new_lines.append(f"CLAUDE_CODE_OAUTH_TOKEN={safe_token}")
            seen = True
        elif line.startswith("ANTHROPIC_API_KEY="):
            # Make sure the API key var is empty so it doesn't shadow the OAuth token.
            new_lines.append("ANTHROPIC_API_KEY=")
        else:
            new_lines.append(line)
    if not seen:
        new_lines.append(f"CLAUDE_CODE_OAUTH_TOKEN={safe_token}")
    DOTENV_PATH.write_text("\n".join(new_lines) + "\n")
    try:
        os.chmod(DOTENV_PATH, 0o600)
    except Exception:
        pass


def _persist_new_oauth(oauth: dict) -> None:
    """Write the freshly-refreshed oauth dict to Keychain + JSON fallback +
    .env + os.environ. Best-effort; partial failures are logged but not
    raised so a refresh isn't lost just because one sink rejected."""
    # Keychain (preserve mcpOAuth siblings if present).
    existing = _read_keychain() or {}
    existing["claudeAiOauth"] = oauth
    if not _write_keychain(existing):
        # Fall back to JSON-only storage.
        _write_json_fallback({"claudeAiOauth": oauth})
    else:
        # Even when Keychain writes work, also drop a JSON copy so a
        # different machine / restart can survive Keychain unlock issues.
        _write_json_fallback({"claudeAiOauth": oauth})
    # .env mirror.
    _write_dotenv(oauth["accessToken"])
    # Live env so the next env read in the running process sees the new
    # value (without this, _build_anthropic_clients still reads the stale
    # value when called by reload_anthropic_clients()).
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = oauth["accessToken"]
    os.environ.pop("ANTHROPIC_API_KEY", None)


# ── Refresh flow ─────────────────────────────────────────────────────────────

def _post_refresh(refresh_token: str) -> dict:
    """POST to the Anthropic OAuth token endpoint and return the response
    JSON. Raises on any non-200."""
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLAUDE_CODE_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "jarvis-backend-claude-refresh/1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def needs_refresh(oauth: Optional[dict] = None) -> bool:
    """True when access token is missing, expired, or expiring soon."""
    o = oauth or _current_oauth()
    if not o or not o.get("refreshToken"):
        return False  # no refresh token — caller must re-auth manually
    # Access token absent but refresh token present: a refresh *will* succeed,
    # so returning False here would silently skip it and break all API calls.
    if not o.get("accessToken"):
        return True
    expires_at_ms = int(o.get("expiresAt") or 0)
    if expires_at_ms == 0:
        return True
    now_ms = int(time.time() * 1000)
    remaining_s = (expires_at_ms - now_ms) / 1000
    return remaining_s < REFRESH_HEADROOM_SECONDS


def refresh_now(force: bool = False) -> dict:
    """Refresh the access token if needed (or always when force=True).

    Returns a status dict: {ok, action, expires_in?, error?}.
    Single-flight: concurrent callers wait for the first refresh to finish.
    """
    with _REFRESH_LOCK:
        oauth = _current_oauth()
        if not oauth:
            return {"ok": False, "action": "skipped", "error": "no_credential"}
        if not oauth.get("refreshToken"):
            return {"ok": False, "action": "skipped", "error": "no_refresh_token"}
        if not force and not needs_refresh(oauth):
            now_ms = int(time.time() * 1000)
            remaining_s = (int(oauth.get("expiresAt", 0)) - now_ms) / 1000
            return {
                "ok": True,
                "action": "skipped_fresh",
                "remaining_s": remaining_s,
            }
        try:
            data = _post_refresh(oauth["refreshToken"])
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            log.error("OAuth refresh HTTP %s: %s", e.code, body)
            return {"ok": False, "action": "http_error", "status": e.code, "error": body}
        except Exception as e:
            log.error("OAuth refresh exception: %s", e)
            return {"ok": False, "action": "exception", "error": str(e)}

        access = data.get("access_token")
        refresh = data.get("refresh_token") or oauth["refreshToken"]
        expires_in = int(data.get("expires_in") or 0)
        if not access or not expires_in:
            return {"ok": False, "action": "bad_response", "error": "no_access_token"}
        new_oauth = {
            "accessToken": access,
            "refreshToken": refresh,
            "expiresAt": int((time.time() + expires_in) * 1000),
            "scopes": data.get("scope", "").split() if isinstance(data.get("scope"), str) else oauth.get("scopes", []),
            "subscriptionType": oauth.get("subscriptionType"),
            "rateLimitTier": oauth.get("rateLimitTier"),
        }
        _persist_new_oauth(new_oauth)

        # Hot-reload the Anthropic clients so the next call uses the fresh
        # token. Local import to avoid a circular at module-load.
        try:
            from agent import jarvis as _jarvis
            _jarvis.reload_anthropic_clients()
        except Exception as e:
            log.warning("reload_anthropic_clients failed: %s", e)

        # Bust the auth-status probe cache so /auth/status reflects reality.
        try:
            from api.auth import _CLAUDE_PROBE_CACHE
            _CLAUDE_PROBE_CACHE.update(checked_at=0.0, ok=None, error=None)
        except Exception:
            pass

        log.info("OAuth refresh OK — expires in %ds (token prefix=%s...)",
                 expires_in, access[:20])
        return {"ok": True, "action": "refreshed", "expires_in": expires_in}


# ── Auto-refresh when callers see 401 ────────────────────────────────────────

def is_auth_error(exc: BaseException) -> bool:
    """Detect a 401 from the Anthropic SDK."""
    try:
        import anthropic
        if isinstance(exc, anthropic.AuthenticationError):
            return True
    except Exception:
        pass
    msg = str(exc)
    return "401" in msg or "authentication_error" in msg or "Invalid authentication" in msg


def refresh_on_401(exc: BaseException) -> bool:
    """If exc looks like a 401, attempt a refresh. Return True if the
    caller should retry the original request once with the new client."""
    if not is_auth_error(exc):
        return False
    log.info("got 401 — attempting OAuth refresh")
    result = refresh_now(force=True)
    return bool(result.get("ok"))


# ── Background scheduler — fire ~30 min before expiry, on a loop ─────────────

_SCHEDULER_THREAD: Optional[threading.Thread] = None
_SCHEDULER_STOP = threading.Event()


def _scheduler_loop():
    while not _SCHEDULER_STOP.wait(timeout=60):
        try:
            oauth = _current_oauth()
            if not oauth or not oauth.get("refreshToken"):
                continue
            expires_at_ms = int(oauth.get("expiresAt") or 0)
            if expires_at_ms == 0:
                continue
            now_ms = int(time.time() * 1000)
            remaining_s = (expires_at_ms - now_ms) / 1000
            # Refresh once we're inside the headroom window.
            if remaining_s < REFRESH_HEADROOM_SECONDS:
                refresh_now(force=False)
        except Exception as e:
            log.warning("scheduler tick error: %s", e)


def start_background_refresher() -> None:
    """Idempotent: start the watcher thread once.

    Also performs an immediate refresh-if-needed so a backend that's been
    stopped through token expiry comes back healthy on first request.
    """
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
        return

    # Eager initial refresh — handles the case where the user starts the
    # backend after a long absence and the access token is already expired.
    try:
        if needs_refresh():
            refresh_now(force=False)
    except Exception as e:
        log.warning("eager refresh failed: %s", e)

    _SCHEDULER_THREAD = threading.Thread(
        target=_scheduler_loop, name="claude-oauth-refresh", daemon=True,
    )
    _SCHEDULER_THREAD.start()
    log.info("OAuth background refresher started")


def status() -> dict:
    """Public status helper for diagnostics endpoints."""
    oauth = _current_oauth() or {}
    expires_at_ms = int(oauth.get("expiresAt") or 0)
    now_ms = int(time.time() * 1000)
    remaining_s = max(0, (expires_at_ms - now_ms) / 1000) if expires_at_ms else 0
    return {
        "has_credential": bool(oauth.get("accessToken")),
        "has_refresh_token": bool(oauth.get("refreshToken")),
        "expires_at_ms": expires_at_ms,
        "remaining_s": remaining_s,
        "needs_refresh": needs_refresh(oauth),
        "scheduler_running": _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive(),
    }
