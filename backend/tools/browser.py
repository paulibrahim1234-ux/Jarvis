"""
Browser tools — lets Jarvis control Chrome via AppleScript.

Jarvis can navigate pages, read content, run JS, click elements,
and fill forms — so it can fetch credentials, complete auth flows,
and automate web tasks without the user lifting a finger.
"""

import subprocess
import json


BROWSER_TOOLS = [
    {
        "name": "browser_navigate",
        "description": "Open a URL in the frontmost Chrome window/tab.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_read_page",
        "description": (
            "Read the visible text content and current URL of the active Chrome tab. "
            "Use after navigating to extract credentials, check login state, read page data."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "browser_run_js",
        "description": (
            "Run JavaScript in the active Chrome tab and return the result. "
            "Use to extract specific values: e.g. document.querySelector('#clientId').textContent"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "JavaScript expression or statement(s) to execute. Return value is captured."},
            },
            "required": ["code"],
        },
    },
    {
        "name": "browser_click",
        "description": "Click a page element in Chrome by CSS selector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element to click"},
            },
            "required": ["selector"],
        },
    },
    {
        "name": "browser_fill",
        "description": "Fill an input field in Chrome by CSS selector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of input field"},
                "value": {"type": "string", "description": "Value to type into the field"},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "browser_wait",
        "description": "Wait a number of seconds for a page to load or animation to finish.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "Seconds to wait (max 15)"},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "browser_get_current_url",
        "description": "Get the URL of the current active Chrome tab.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "fetch_spotify_credentials",
        "description": (
            "Automated flow: navigate to Spotify Developer Dashboard, find or create an app, "
            "extract Client ID + Secret, and save them to .env. "
            "User must already be logged into Spotify in Chrome. "
            "Call this when user says 'get my Spotify credentials' or similar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Name of the Spotify app to create or find. Default: 'Jarvis'",
                    "default": "Jarvis",
                },
            },
            "required": [],
        },
    },
    {
        "name": "fetch_azure_client_id",
        "description": (
            "Navigate to Azure App Registrations, find the most recently created app, "
            "and extract the Application (client) ID. Saves it to MS_CLIENT_ID in .env. "
            "User must be logged into portal.azure.com in Chrome."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# ── Chrome AppleScript helpers ────────────────────────────────────────────────

def _chrome_js(code: str, timeout: int = 10) -> str:
    """Run JS in frontmost Chrome tab via AppleScript. Returns result as string."""
    # Wrap in try/catch so errors surface clearly
    safe_code = f"""
(function() {{
  try {{
    return String({code});
  }} catch(e) {{
    return 'ERROR: ' + e.message;
  }}
}})()
""".strip()
    escaped = safe_code.replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Google Chrome" to execute active tab of first window javascript "{escaped}"'
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"AppleScript error: {r.stderr.strip()}")
    return r.stdout.strip()


def _chrome_navigate(url: str):
    script = f'tell application "Google Chrome" to set URL of active tab of first window to "{url}"'
    subprocess.run(["osascript", "-e", script], timeout=10)


def _chrome_get_url() -> str:
    script = 'tell application "Google Chrome" to get URL of active tab of first window'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
    return r.stdout.strip()


def _chrome_get_text() -> str:
    """Get visible text of current page (truncated to 4000 chars)."""
    text = _chrome_js("document.body.innerText")
    return text[:4000]


def _write_env_kv(key: str, value: str):
    """Write KEY=value to backend/.env and os.environ."""
    import os, re
    from pathlib import Path
    env_file = Path(__file__).parent.parent / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    found = False
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if re.match(rf"^{re.escape(key)}\s*=", line):
                lines.append(f'{key}="{value}"')
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f'{key}="{value}"')
    env_file.write_text("\n".join(lines) + "\n")
    os.environ[key] = value


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def run_browser_tool(name: str, inp: dict):
    import time

    if name == "browser_navigate":
        _chrome_navigate(inp["url"])
        time.sleep(2)
        url = _chrome_get_url()
        return {"status": "navigated", "current_url": url}

    if name == "browser_read_page":
        url = _chrome_get_url()
        text = _chrome_get_text()
        return {"url": url, "content": text}

    if name == "browser_run_js":
        result = _chrome_js(inp["code"])
        return {"result": result}

    if name == "browser_click":
        sel = inp["selector"].replace('"', '\\"')
        result = _chrome_js(
            f'(function(){{ var el = document.querySelector("{sel}"); '
            f'if(!el) return "NOT FOUND"; el.click(); return "clicked"; }})()'
        )
        time.sleep(0.8)
        return {"result": result}

    if name == "browser_fill":
        sel = inp["selector"].replace('"', '\\"')
        val = inp["value"].replace('"', '\\"')
        result = _chrome_js(
            f'(function(){{'
            f'  var el = document.querySelector("{sel}");'
            f'  if(!el) return "NOT FOUND";'
            f'  el.focus();'
            f'  el.value = "{val}";'
            f'  el.dispatchEvent(new Event("input", {{bubbles:true}}));'
            f'  el.dispatchEvent(new Event("change", {{bubbles:true}}));'
            f'  return "filled";'
            f'}})()'
        )
        return {"result": result}

    if name == "browser_wait":
        secs = min(float(inp.get("seconds", 2)), 15)
        time.sleep(secs)
        return {"status": f"waited {secs}s"}

    if name == "browser_get_current_url":
        return {"url": _chrome_get_url()}

    if name == "fetch_spotify_credentials":
        return _fetch_spotify_credentials(inp.get("app_name", "Jarvis"))

    if name == "fetch_azure_client_id":
        return _fetch_azure_client_id()

    raise ValueError(f"Unknown browser tool: {name}")


# ── Automated credential flows ────────────────────────────────────────────────

def _fetch_spotify_credentials(app_name: str = "Jarvis") -> dict:
    """
    Full automated flow:
    1. Navigate to Spotify dashboard
    2. Check login state
    3. Create app if needed
    4. Extract client_id + client_secret
    5. Save to .env
    """
    import time

    _chrome_navigate("https://developer.spotify.com/dashboard")
    time.sleep(3)

    url = _chrome_get_url()
    text = _chrome_get_text()

    # Check if we need to log in (Spotify accounts, Facebook, or generic login page)
    _login_signals = ("accounts.spotify.com", "facebook.com/login", "login.spotify", "login?")
    if any(s in url.lower() for s in _login_signals) or (
        "login" in url.lower() and "developer.spotify.com" not in url.lower()
    ):
        return {
            "status": "needs_login",
            "message": (
                "You need to log into Spotify for Developers first. "
                "In Chrome, complete the login (Spotify or Facebook), then say 'fetch spotify credentials' again."
            ),
        }

    # Look for existing app or create one
    # Try to find app link
    existing = _chrome_js(
        f'(function(){{'
        f'  var links = Array.from(document.querySelectorAll("a"));'
        f'  var app = links.find(l => l.textContent.trim().toLowerCase().includes("{app_name.lower()}"));'
        f'  return app ? app.href : "none";'
        f'}})()'
    )

    if existing and existing != "none" and existing != "ERROR":
        _chrome_navigate(existing)
        time.sleep(2)
    else:
        # Try to create a new app
        create_btn = _chrome_js(
            '(function(){'
            '  var btns = Array.from(document.querySelectorAll("button,a"));'
            '  var btn = btns.find(b => b.textContent.toLowerCase().includes("create app") || b.textContent.toLowerCase().includes("create an app"));'
            '  if(btn){ btn.click(); return "clicked"; } return "not found";'
            '})()'
        )
        time.sleep(2)

        if "clicked" in create_btn:
            # Fill app name
            _chrome_js(
                f'(function(){{'
                f'  var inp = document.querySelector("input[name=\\"name\\"],input#name,input[placeholder*=name]");'
                f'  if(inp){{ inp.focus(); inp.value="{app_name}"; inp.dispatchEvent(new Event("input",{{bubbles:true}})); }}'
                f'}})()'
            )
            time.sleep(0.5)

            # Fill redirect URI
            _chrome_js(
                '(function(){'
                '  var inp = document.querySelector("input[name=\\"redirectUris\\"],input[placeholder*=redirect],input[placeholder*=uri]");'
                '  if(inp){ inp.focus(); inp.value="http://127.0.0.1:8000/auth/spotify/callback"; inp.dispatchEvent(new Event("input",{bubbles:true})); }'
                '})()'
            )
            time.sleep(0.5)

            # Accept terms checkbox
            _chrome_js(
                '(function(){'
                '  var cb = document.querySelector("input[type=checkbox]");'
                '  if(cb && !cb.checked){ cb.click(); }'
                '})()'
            )
            time.sleep(0.3)

            # Click Save/Create
            _chrome_js(
                '(function(){'
                '  var btns = Array.from(document.querySelectorAll("button"));'
                '  var btn = btns.find(b => b.textContent.toLowerCase().includes("save") || b.textContent.toLowerCase().includes("create"));'
                '  if(btn){ btn.click(); return "clicked"; } return "not found";'
                '})()'
            )
            time.sleep(3)

    # Now on app detail page — extract client ID
    client_id = _chrome_js(
        '(function(){'
        '  // Try data attribute, then text near "Client ID" label'
        '  var el = document.querySelector("[data-testid=\\"client-id\\"],#client-id,.client-id");'
        '  if(el) return el.textContent.trim();'
        '  // Find by label proximity'
        '  var labels = Array.from(document.querySelectorAll("*"));'
        '  for(var l of labels){'
        '    if(l.children.length === 0 && l.textContent.trim() === "Client ID"){'
        '      var sib = l.parentElement && l.parentElement.nextElementSibling;'
        '      if(sib) return sib.textContent.trim();'
        '    }'
        '  }'
        '  // Fallback: find a 32-char hex string on the page'
        '  var match = document.body.innerText.match(/[0-9a-f]{32}/i);'
        '  return match ? match[0] : "not_found";'
        '})()'
    )

    # Click "Show client secret" if available
    _chrome_js(
        '(function(){'
        '  var btns = Array.from(document.querySelectorAll("button,a"));'
        '  var btn = btns.find(b => b.textContent.toLowerCase().includes("secret") || b.textContent.toLowerCase().includes("show"));'
        '  if(btn){ btn.click(); }'
        '})()'
    )
    time.sleep(1)

    client_secret = _chrome_js(
        '(function(){'
        '  var el = document.querySelector("[data-testid=\\"client-secret\\"],#client-secret,.client-secret");'
        '  if(el) return el.textContent.trim();'
        '  var labels = Array.from(document.querySelectorAll("*"));'
        '  for(var l of labels){'
        '    if(l.children.length === 0 && l.textContent.trim() === "Client secret"){'
        '      var sib = l.parentElement && l.parentElement.nextElementSibling;'
        '      if(sib) return sib.textContent.trim();'
        '    }'
        '  }'
        '  var match = document.body.innerText.match(/[0-9a-f]{32}/gi);'
        '  return match && match.length > 1 ? match[1] : "not_found";'
        '})()'
    )

    results = {}

    if client_id and client_id not in ("not_found", "ERROR", ""):
        _write_env_kv("SPOTIFY_CLIENT_ID", client_id)
        results["SPOTIFY_CLIENT_ID"] = client_id
        _write_env_kv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/auth/spotify/callback")
        results["SPOTIFY_REDIRECT_URI"] = "http://127.0.0.1:8000/auth/spotify/callback"

    if client_secret and client_secret not in ("not_found", "ERROR", ""):
        _write_env_kv("SPOTIFY_CLIENT_SECRET", client_secret)
        results["SPOTIFY_CLIENT_SECRET"] = "saved (hidden)"

    if results:
        return {
            "status": "success",
            "saved": list(results.keys()),
            "client_id": results.get("SPOTIFY_CLIENT_ID", "not extracted — check dashboard manually"),
            "next_step": "Credentials saved. Now go to http://127.0.0.1:8000/auth/spotify to complete OAuth.",
        }

    return {
        "status": "partial",
        "page_text_preview": text[:500],
        "message": "Could not auto-extract credentials. Check the Spotify dashboard tab in Chrome.",
    }


def _fetch_azure_client_id() -> dict:
    """Navigate to Azure App Registrations and extract the client ID."""
    import time

    _chrome_navigate(
        "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
    )
    time.sleep(4)

    url = _chrome_get_url()
    if "login.microsoftonline" in url or "login.microsoft.com" in url:
        return {
            "status": "needs_login",
            "message": "Please log into Azure portal in Chrome, then say 'try again'.",
        }

    # Find first app row
    client_id = _chrome_js(
        '(function(){'
        '  // Look for a GUID pattern (Azure client IDs are GUIDs)'
        '  var match = document.body.innerText.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);'
        '  return match ? match[0] : "not_found";'
        '})()'
    )

    if client_id and client_id != "not_found":
        _write_env_kv("MS_CLIENT_ID", client_id)
        return {
            "status": "success",
            "MS_CLIENT_ID": client_id,
            "next_step": "Client ID saved. Go to http://127.0.0.1:8000/auth/microsoft to complete device flow auth.",
        }

    return {
        "status": "needs_app",
        "message": (
            "No app registrations found. "
            "Create one at https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/CreateApplicationBlade "
            "then say 'get my Azure client ID'."
        ),
    }
