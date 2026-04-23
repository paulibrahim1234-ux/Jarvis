"""
Computer / system tools — lets Jarvis control the Mac.

Permissions needed (grant in System Settings → Privacy & Security):
  - Accessibility  → click, type, AppleScript UI events
  - Screen Recording → take_screenshot
  - Full Disk Access → already granted if iMessage works
"""

import base64
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

# Allowed credential keys (prevents arbitrary env manipulation via chat)
_ALLOWED_CRED_KEYS = {
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REDIRECT_URI",
    "MS_CLIENT_ID",
    "MS_TENANT_ID",
    "ANTHROPIC_API_KEY",
}

_ENV_FILE = Path(__file__).parent.parent / ".env"

COMPUTER_TOOLS = [
    {
        "name": "open_app",
        "description": "Open a macOS application by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "App name as it appears in /Applications, e.g. 'Anki', 'Spotify', 'Safari', 'Mail'",
                }
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "open_url",
        "description": "Open a URL in the default browser.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "run_applescript",
        "description": (
            "Run AppleScript to control macOS apps — Spotify playback, Safari navigation, "
            "Finder, notifications, UI automation, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "AppleScript code to run via osascript"}
            },
            "required": ["script"],
        },
    },
    {
        "name": "save_credential",
        "description": (
            "Save an API credential to the Jarvis .env file so it takes effect immediately. "
            "Allowed keys: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, MS_CLIENT_ID, "
            "MS_TENANT_ID, ANTHROPIC_API_KEY."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Environment variable name"},
                "value": {"type": "string", "description": "Value to save"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the current screen. Returns the image so you can see what's on screen.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "send_notification",
        "description": "Send a macOS notification banner to the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["title", "message"],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Run a whitelisted shell command. Safe operations only: "
            "pip install, brew install, launchctl, curl (GET only), ls, cat on non-sensitive paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "cwd": {"type": "string", "description": "Working directory (optional)"},
            },
            "required": ["command"],
        },
    },
]

# Shell metacharacters that are never allowed in a command string.
# Any command containing these is rejected before further checks.
_SHELL_METACHARACTERS = (";", "&&", "||", "|", ">", ">>", "`", "$(", "<", "\n")

# Allowed programs (argv[0] exact match after shlex tokenisation).
# `killall` and `pkill` intentionally excluded — they can kill security daemons.
_ALLOWED_SHELL_COMMANDS = {
    "pip",
    "pip3",
    "brew",
    "launchctl",
    "curl",
    "ls",
    "cat",
    "echo",
    "python",
    "python3",
    "open",
}


def run_computer_tool(name: str, inp: dict):
    if name == "open_app":
        app = inp["app_name"]
        r = subprocess.run(["open", "-a", app], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {"error": r.stderr.strip() or f"Could not open '{app}'"}
        return {"status": f"Opened {app}"}

    if name == "open_url":
        url = inp["url"]
        subprocess.run(["open", url], timeout=5)
        return {"status": f"Opened {url}"}

    if name == "run_applescript":
        return run_applescript(inp["script"])

    if name == "save_credential":
        key = inp["key"].strip().upper()
        if key not in _ALLOWED_CRED_KEYS:
            return {
                "error": f"{key!r} not in allowed list. Allowed: {sorted(_ALLOWED_CRED_KEYS)}"
            }
        value = inp["value"].strip()
        _write_env(key, value)
        os.environ[key] = value  # live effect without restart
        return {"status": f"Saved {key} to .env and applied to running process"}

    if name == "take_screenshot":
        return _screenshot()

    if name == "send_notification":
        title = inp["title"].replace('"', "'")
        msg = inp["message"].replace('"', "'")
        subprocess.run(
            ["osascript", "-e", f'display notification "{msg}" with title "{title}"'],
            timeout=5,
        )
        return {"status": "Notification sent"}

    if name == "run_shell":
        return _safe_shell(inp["command"], inp.get("cwd"))

    raise ValueError(f"Unknown computer tool: {name}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _screenshot() -> dict:
    """Capture screen → base64 PNG dict suitable for image tool_result content."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        r = subprocess.run(
            ["screencapture", "-x", "-C", tmp],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0:
            return {"error": "screencapture failed — grant Screen Recording in System Settings"}
        with open(tmp, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data},
        }
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def run_applescript(script: str) -> dict:
    """Run an AppleScript via osascript, rejecting dangerous patterns."""
    _APPLESCRIPT_BLOCKED = (
        "do shell script",
        "delete file",
        "eject ",
        'keystroke "',
    )
    script_lower = script.lower()
    for pattern in _APPLESCRIPT_BLOCKED:
        if pattern.lower() in script_lower:
            return {"error": f"blocked: AppleScript contains disallowed pattern: {pattern!r}"}
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return {"error": r.stderr.strip()}
    return {"output": r.stdout.strip() or "(ok)"}


def _safe_shell(command: str, cwd: str | None = None) -> dict:
    # 1. Deny shell metacharacters before any further processing.
    for meta in _SHELL_METACHARACTERS:
        if meta in command:
            return {"error": "blocked: shell metachar"}

    # 2. Tokenise with shlex so we inspect the real argv[0], not a prefix.
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return {"error": f"blocked: could not parse command: {exc}"}

    if not argv:
        return {"error": "blocked: empty command"}

    # 3. Match argv[0] against the allowlist (exact, case-sensitive).
    if argv[0] not in _ALLOWED_SHELL_COMMANDS:
        return {
            "error": (
                f"blocked: command not in allowlist. "
                f"Allowed: {sorted(_ALLOWED_SHELL_COMMANDS)}"
            )
        }

    # 4. Execute without a shell — no metachar expansion possible.
    r = subprocess.run(
        argv, shell=False, capture_output=True, text=True,
        timeout=60, cwd=cwd or None,
    )
    return {
        "stdout": r.stdout.strip()[:2000],
        "stderr": r.stderr.strip()[:500],
        "returncode": r.returncode,
    }


def _write_env(key: str, value: str):
    """Write or update KEY="value" in .env file."""
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
