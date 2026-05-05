"""
Browser tools — lets Jarvis control a Chromium-based browser via AppleScript.

Jarvis can navigate pages, read content, run JS, click elements,
and fill forms — so it can fetch credentials, complete auth flows,
and automate web tasks without the user lifting a finger.

Browser selection: reads JARVIS_BROWSER env var (default "Comet").
Override: export JARVIS_BROWSER="Google Chrome" to use Chrome instead.
"""

import os
import subprocess
import json

# ── Browser app name ──────────────────────────────────────────────────────────
# Reads JARVIS_BROWSER from env at module load.  Default is "Comet" because
# the user runs Perplexity Comet as their default browser.
# To use Chrome instead: set JARVIS_BROWSER=Google Chrome in backend/.env
BROWSER_APP: str = os.environ.get("JARVIS_BROWSER", "Comet").strip() or "Comet"


BROWSER_TOOLS = [
    {
        "name": "browser_navigate",
        "description": "Open a URL in the frontmost browser window/tab (default: Comet).",
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
            "Read the visible text content and current URL of the active browser tab (default: Comet). "
            "Use after navigating to extract credentials, check login state, read page data."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "browser_run_js",
        "description": (
            "Run JavaScript in the active browser tab (default: Comet) and return the result. "
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
        "description": "Click a page element in the browser by CSS selector.",
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
        "description": "Fill an input field in the browser by CSS selector.",
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
        "description": "Get the URL of the current active browser tab (default: Comet).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "fetch_spotify_credentials",
        "description": (
            "Automated flow: navigate to Spotify Developer Dashboard, find or create an app, "
            "extract Client ID + Secret, and save them to .env. "
            f"User must already be logged into Spotify in {BROWSER_APP}. "
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
            f"User must be logged into portal.azure.com in {BROWSER_APP}."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "uworld_scrape_history",
        "description": (
            "Scrape UWorld QBank test history from the logged-in browser session "
            f"({BROWSER_APP}). Reads sessionStorage authInfo from an open UWorld tab, "
            "calls the gateway-api to fetch completed test records and per-test wrong "
            "question IDs, and persists results to uworld_history.json. "
            "User must be logged into UWorld in the browser."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# ── Chrome AppleScript helpers ────────────────────────────────────────────────

def _chrome_js(code: str, timeout: int = 10) -> str:
    """Run JS in frontmost Chrome tab via AppleScript. Returns result as string."""
    # Wrap in try/catch so errors surface clearly
    safe_code = (
        "(function() {"
        "  try {"
        f"    return String({code});"
        "  } catch(e) {"
        "    return 'ERROR: ' + e.message;"
        "  }"
        "})()"
    )
    # AppleScript string literals cannot contain literal newlines or unescaped quotes/backslashes.
    escaped = (
        safe_code
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    script = f'tell application "{BROWSER_APP}" to execute active tab of first window javascript "{escaped}"'
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        err = r.stderr.strip()
        # Surface a clear actionable message for the "JavaScript from Apple Events" error
        if "JavaScript through AppleScript is turned off" in err or "Allow JavaScript from Apple Events" in err:
            raise RuntimeError(
                f"{BROWSER_APP} has JavaScript from Apple Events disabled. "
                f"To fix: in {BROWSER_APP}, go to View > Developer > Allow JavaScript from Apple Events, "
                f"then try again."
            )
        raise RuntimeError(f"AppleScript error ({BROWSER_APP}): {err}")
    return r.stdout.strip()


def _chrome_navigate(url: str):
    # "set URL of active tab" BLOCKS until the page fully loads — it hangs
    # indefinitely on complex SPAs like UWorld's courseapp.
    # "open location" returns immediately after dispatching navigation.
    # We call it twice with a 1s pause to ensure Comet focuses the tab.
    if not url or '\n' in url or '\r' in url:
        raise ValueError('invalid URL: contains newlines')
    if not url.startswith(('http://', 'https://', 'about:', 'chrome://', 'file://')):
        raise ValueError(f'invalid URL scheme: {url!r}')
    safe = url.replace('\\', '\\\\').replace('"', '\\"')
    script = f'tell application "{BROWSER_APP}" to open location "{safe}"'
    subprocess.run(["osascript", "-e", script], timeout=10)


def _chrome_get_url() -> str:
    script = f'tell application "{BROWSER_APP}" to get URL of active tab of first window'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


def _chrome_get_text() -> str:
    """Get visible text of current page (truncated to 4000 chars)."""
    text = _chrome_js("document.body.innerText")
    return text[:4000]


def _switch_to_tab_containing(domain: str) -> bool:
    """Find the first open tab whose URL contains `domain` and make it the active tab.

    Returns True if a matching tab was found and activated, False otherwise.
    Uses AppleScript written to a temp file to avoid multi-line -e quoting issues
    when called from a background thread.
    """
    import tempfile, os as _os
    domain = domain.replace("\\", "").replace('"', "").replace("'", "")
    script = (
        f'tell application "{BROWSER_APP}"\n'
        f'  repeat with w from 1 to count of windows\n'
        f'    repeat with t from 1 to count of tabs of window w\n'
        f'      if URL of tab t of window w contains "{domain}" then\n'
        f'        set active tab index of window w to t\n'
        f'        set index of window w to 1\n'
        f'        return "found"\n'
        f'      end if\n'
        f'    end repeat\n'
        f'  end repeat\n'
        f'  return "not_found"\n'
        f'end tell\n'
    )
    fd, tmp = tempfile.mkstemp(suffix=".applescript")
    try:
        with _os.fdopen(fd, "w") as f:
            f.write(script)
        r = subprocess.run(["osascript", tmp], capture_output=True, text=True, timeout=15)
        return r.stdout.strip() == "found"
    except Exception:
        return False
    finally:
        try:
            _os.unlink(tmp)
        except OSError:
            pass


def _write_env_kv(key: str, value: str):
    """Write KEY=value to backend/.env and os.environ.

    Delegates to computer._write_env which holds _ENV_WRITE_LOCK so
    concurrent browser credential flows don't race on the same file.
    """
    import os
    from tools.computer import _write_env
    _write_env(key, value)
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
        # json.dumps emits a JS-safe string literal (handles backslash, quotes,
        # newlines, control chars) — safer than the prior char-replace escape
        # which left newlines in the selector capable of breaking out of the
        # JS string literal.
        sel = json.dumps(inp["selector"])
        result = _chrome_js(
            f'(function(){{ var el = document.querySelector({sel}); '
            f'if(!el) return "NOT FOUND"; el.click(); return "clicked"; }})()'
        )
        time.sleep(0.8)
        return {"result": result}

    if name == "browser_fill":
        sel = json.dumps(inp["selector"])
        val = json.dumps(inp["value"])
        result = _chrome_js(
            f'(function(){{'
            f'  var el = document.querySelector({sel});'
            f'  if(!el) return "NOT FOUND";'
            f'  el.focus();'
            f'  el.value = {val};'
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

    if name == "uworld_scrape_history":
        return _uworld_scrape_history()

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
    # Try to find app link.
    # Use json.dumps to safely escape app_name into a JS string literal —
    # otherwise an attacker-controlled name like `"); evil(); //` would
    # break out of the literal and run arbitrary JavaScript in Comet.
    needle = json.dumps(app_name.lower())
    existing = _chrome_js(
        f'(function(){{'
        f'  var links = Array.from(document.querySelectorAll("a"));'
        f'  var needle = {needle};'
        f'  var app = links.find(l => l.textContent.trim().toLowerCase().includes(needle));'
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
            name_lit = json.dumps(app_name)
            _chrome_js(
                f'(function(){{'
                f'  var inp = document.querySelector("input[name=\\"name\\"],input#name,input[placeholder*=name]");'
                f'  if(inp){{ inp.focus(); inp.value={name_lit}; inp.dispatchEvent(new Event("input",{{bubbles:true}})); }}'
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
        "message": f"Could not auto-extract credentials. Check the Spotify dashboard tab in {BROWSER_APP}.",
    }


def _uw_tab_js(script_lines: str, win_idx: int, tab_idx: int, timeout: int = 15) -> str:
    """Run JS on a specific Comet tab (by window/tab index, 1-based).

    Uses AppleScript written to a temp file to avoid multi-line -e quoting issues.
    Returns the result string (stripped), or empty string on error.
    """
    import tempfile, os as _os

    # The JS is injected into an AppleScript string literal: escape backslashes,
    # double-quotes, and newlines so AppleScript doesn't choke.
    safe_code = (
        "(function() {"
        "  try {"
        f"    return String({script_lines});"
        "  } catch(e) {"
        "    return 'ERROR: ' + e.message;"
        "  }"
        "})()"
    )
    escaped = (
        safe_code
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    as_script = (
        f'tell application "{BROWSER_APP}"\n'
        f'  execute tab {tab_idx} of window {win_idx} javascript "{escaped}"\n'
        f'end tell\n'
    )
    fd, tmp = tempfile.mkstemp(suffix=".applescript")
    try:
        with _os.fdopen(fd, "w") as f:
            f.write(as_script)
        r = subprocess.run(["osascript", tmp], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""
    finally:
        try:
            _os.unlink(tmp)
        except OSError:
            pass


def _uw_find_tab(url_fragment: str) -> tuple[int, int] | None:
    """Find a Comet tab whose URL contains url_fragment.

    Returns (window_index, tab_index) — both 1-based — or None if not found.
    Uses AppleScript written to a temp file for reliability.
    """
    import tempfile, os as _os
    url_fragment = url_fragment.replace("\\", "").replace('"', "").replace("'", "")
    as_script = (
        f'tell application "{BROWSER_APP}"\n'
        f'  repeat with wi from 1 to count of windows\n'
        f'    repeat with ti from 1 to count of tabs of window wi\n'
        f'      if URL of tab ti of window wi contains "{url_fragment}" then\n'
        f'        return (wi as string) & "," & (ti as string)\n'
        f'      end if\n'
        f'    end repeat\n'
        f'  end repeat\n'
        f'  return ""\n'
        f'end tell\n'
    )
    fd, tmp = tempfile.mkstemp(suffix=".applescript")
    try:
        with _os.fdopen(fd, "w") as f:
            f.write(as_script)
        r = subprocess.run(["osascript", tmp], capture_output=True, text=True, timeout=15)
        val = r.stdout.strip()
        if "," in val:
            parts = val.split(",")
            return (int(parts[0]), int(parts[1]))
        return None
    except Exception:
        return None
    finally:
        try:
            _os.unlink(tmp)
        except OSError:
            pass


def _uw_set_tab_url(win_idx: int, tab_idx: int, url: str):
    """Navigate a specific Comet tab to url (non-blocking)."""
    import tempfile, os as _os

    # Guard against AppleScript injection: this URL flows from a backend POST
    # (trust boundary is here), so a crafted URL containing " or a newline would
    # break out of the AppleScript string literal and run arbitrary code.
    # Sibling _chrome_navigate validates; keep both consistent.
    if not url.startswith(("http://", "https://")):
        return
    if any(c in url for c in ('"', '\r', '\n')):
        return

    as_script = (
        f'tell application "{BROWSER_APP}"\n'
        f'  set URL of tab {tab_idx} of window {win_idx} to "{url}"\n'
        f'end tell\n'
    )
    fd, tmp = tempfile.mkstemp(suffix=".applescript")
    try:
        with _os.fdopen(fd, "w") as f:
            f.write(as_script)
        subprocess.run(["osascript", tmp], capture_output=True, timeout=10)
    except Exception:
        pass
    finally:
        try:
            _os.unlink(tmp)
        except OSError:
            pass


def _uw_get_tab_url(win_idx: int, tab_idx: int) -> str:
    """Return the current URL of a specific Comet tab."""
    import tempfile, os as _os

    as_script = (
        f'tell application "{BROWSER_APP}"\n'
        f'  return URL of tab {tab_idx} of window {win_idx}\n'
        f'end tell\n'
    )
    fd, tmp = tempfile.mkstemp(suffix=".applescript")
    try:
        with _os.fdopen(fd, "w") as f:
            f.write(as_script)
        r = subprocess.run(["osascript", tmp], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""
    finally:
        try:
            _os.unlink(tmp)
        except OSError:
            pass


def _uworld_scrape_history() -> dict:
    """
    Scrape UWorld test history from the logged-in browser session.

    Auth mechanism (verified 2026-04-26 via live reverse engineering):
    UWorld SPA stores its API credentials in sessionStorage["authInfo"] on tabs
    that have fully loaded (dashboard, results pages). The structure is:
      {at, rt, apiSubKey, isFpStudent, hasLpAccess, topLevelProductId, configId, ...}

    All gateway-api.uworld.com calls require THREE headers:
      Authorization: Bearer <authInfo.at>
      api-uwsub-key: <authInfo.apiSubKey>
      config-parameters: JSON.stringify({configId, deviceTypeId:1, topLevelProductId})

    The uw_at_config cookie's .at token alone is NOT enough — it lacks QBankAPI scope.
    The sessionStorage.authInfo.at is a DIFFERENT token with the correct scope.
    Use synchronous XHR (not fetch) — fetch with cross-origin + custom headers triggers
    CORS preflight which UWorld's server blocks; sync XHR bypasses preflight check.

    Flow:
    1. Find a tab that has authInfo in sessionStorage (dashboard/results tabs do;
       home "/" and "previoustests" tabs often don't).
    2. If none found: navigate active tab to /dashboard/{courseId} and wait.
    3. Call GetTestRecords/2/0 to get all test history.
    4. For each of the last JARVIS_UWORLD_RESULTS_LIMIT completed tests, call
       GetTestRecordDetails/{testId} for wrong QIDs.
    5. Persist atomically to uworld_history.json.

    Real API field names (verified live):
      GetTestRecords response is a list of objects with:
        id (testId int), isEnded (bool), totalQuestions (int),
        totalQuestionCorrect (int), superDivisionName (subject string),
        subDivisionName (subsystem string), topicName (topic string),
        scoreData (object with score int 0-100), dateEnded (str like "Apr 07, 2026 4:55 PM"),
        qbankId (int, 2 for Step 2), percentile (float)
      GetTestRecordDetails response is an object with:
        score (int 0-100), totalQuestions, totalQuestionsCorrect, totalQuestionsIncorrect,
        testQuestionInfoList: list of questions with:
          questionId (int), isCorrect (bool), isIncorrect (bool), isOmitted (bool),
          subject (str), system (str), topic (str), topicAttribute (str),
          userAnswer (int)
    """
    import time
    import os
    import json as _json
    import logging
    import re as _re
    import tempfile as _tf
    from pathlib import Path as _Path

    log = logging.getLogger("jarvis.uworld")

    UWORLD_APP_BASE = "https://apps.uworld.com/courseapp/usmle/v50/en-US"
    HISTORY_PATH = _Path(__file__).resolve().parent.parent / "storage" / "uworld_history.json"
    _UWORLD_APP_DOMAIN = "apps.uworld.com"
    COURSE_ID = os.environ.get("JARVIS_UWORLD_COURSE_ID", "14842106")
    QBANK_ID = os.environ.get("JARVIS_UWORLD_QBANK_ID", "2")

    # How many tests to pull detail for per refresh (env knob, default 10)
    # Bumped from 10 to 100 — a previous bug cleared most users' wrong
    # records, and a 10-test limit meant a single Refresh wouldn't
    # repopulate the backlog. 100 covers the typical 3-month UWorld
    # workload with headroom; override via JARVIS_UWORLD_RESULTS_LIMIT.
    _results_limit = int(os.environ.get("JARVIS_UWORLD_RESULTS_LIMIT", "100"))

    # ── Helper: persist history atomically ──────────────────────────────────
    def _persist(payload: dict):
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = _tf.mkstemp(dir=str(HISTORY_PATH.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                _json.dump(payload, f, indent=2)
            os.replace(tmp, str(HISTORY_PATH))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── Helper: load existing history ────────────────────────────────────────
    def _load_existing() -> dict:
        if HISTORY_PATH.exists():
            try:
                with HISTORY_PATH.open() as f:
                    return _json.load(f)
            except Exception:
                pass
        return {}

    # ── Helper: scan all UWorld tabs, return [(wi, ti, url, has_authinfo), ...] ────
    def _scan_uw_tabs() -> list[tuple[int, int, str, bool]]:
        as_script = (
            f'tell application "{BROWSER_APP}"\n'
            f'  set out to ""\n'
            f'  repeat with w from 1 to count of windows\n'
            f'    repeat with t from 1 to count of tabs of window w\n'
            f'      if URL of tab t of window w contains "uworld.com" then\n'
            f'        set out to out & (w as string) & "," & (t as string) & "," & URL of tab t of window w & "\\n"\n'
            f'      end if\n'
            f'    end repeat\n'
            f'  end repeat\n'
            f'  return out\n'
            f'end tell\n'
        )
        fd, tmp = _tf.mkstemp(suffix=".applescript")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(as_script)
            r = subprocess.run(["osascript", tmp], capture_output=True, text=True, timeout=15)
            result = []
            for line in r.stdout.strip().splitlines():
                parts = line.strip().split(",", 2)
                if len(parts) == 3:
                    try:
                        result.append((int(parts[0]), int(parts[1]), parts[2], False))
                    except ValueError:
                        pass
            return result
        except Exception:
            return []
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── Helper: check which tabs have authInfo in sessionStorage ──────────────
    def _find_authinfo_tab(tabs: list[tuple[int, int, str, bool]]) -> tuple[int, int, dict] | None:
        """Return (wi, ti, authInfo dict) for first tab with sessionStorage.authInfo, or None."""
        CHECK_JS = (
            '(function(){'
            '  var ai=sessionStorage.getItem("authInfo");'
            '  if(!ai) return "";'
            '  try{ var p=JSON.parse(ai); return p.at&&p.apiSubKey?ai:""; }catch(e){ return ""; }'
            '})()'
        )
        for wi, ti, url, _ in tabs:
            raw = _uw_tab_js(CHECK_JS, wi, ti, timeout=8)
            if raw and raw.strip() and raw.strip() != "null" and raw.strip() != "":
                try:
                    ai = _json.loads(raw.strip())
                    if ai.get("at") and ai.get("apiSubKey"):
                        log.info(f"[uworld] Found authInfo in tab w{wi}t{ti}: {url[:60]}")
                        return (wi, ti, ai)
                except Exception:
                    pass
        return None

    # ── Helper: XHR API call using authInfo headers (sync XHR via page context) ──
    def _uw_api_call(endpoint: str, tab_wi: int, tab_ti: int,
                     authinfo: dict, timeout: int = 25) -> dict | list:
        """Call a gateway-api endpoint using the authInfo credentials.

        Required headers (verified live):
          Authorization: Bearer <at>
          api-uwsub-key: <apiSubKey>
          config-parameters: JSON of {configId, deviceTypeId:1, topLevelProductId}

        Uses synchronous XHR (not fetch) — fetch triggers CORS preflight for
        custom headers; sync XHR does not.
        """
        at = authinfo.get("at", "")
        api_sub_key = authinfo.get("apiSubKey", "")
        config_id = authinfo.get("configId", 7)
        top_prod_id = authinfo.get("topLevelProductId", 1)
        config_params = _json.dumps({
            "configId": config_id,
            "deviceTypeId": 1,
            "topLevelProductId": top_prod_id,
        })
        # Produce JS-string-safe literals by JSON-encoding each value and then
        # stripping the surrounding double-quotes.  Applying an additional
        # backslash+quote escape on top of config_params (already JSON) would
        # double-escape any embedded backslashes or quotes in string values.
        at_escaped = _json.dumps(at)[1:-1]
        subkey_escaped = _json.dumps(api_sub_key)[1:-1]
        config_escaped = _json.dumps(config_params)[1:-1]
        # endpoint uses the same json.dumps approach; additionally strip embedded
        # newlines that would break the single-line x.open() JS call at runtime.
        endpoint_escaped = _json.dumps(endpoint.replace('\n', '').replace('\r', ''))[1:-1]

        js = (
            f'(function(){{'
            f'  try{{'
            f'    var x=new XMLHttpRequest();'
            f'    x.open("GET","{endpoint_escaped}",false);'
            f'    x.setRequestHeader("Authorization","Bearer {at_escaped}");'
            f'    x.setRequestHeader("api-uwsub-key","{subkey_escaped}");'
            f'    x.setRequestHeader("config-parameters","{config_escaped}");'
            f'    x.setRequestHeader("Accept","application/json");'
            f'    x.setRequestHeader("Content-Type","text/json");'
            f'    x.send();'
            f'    if(x.status>=200&&x.status<300) return x.responseText;'
            f'    return JSON.stringify({{_error:"HTTP "+x.status,body:x.responseText.slice(0,300)}});'
            f'  }}catch(e){{return JSON.stringify({{_error:String(e)}});}}'
            f'}})()'
        )
        raw = _uw_tab_js(js, tab_wi, tab_ti, timeout=timeout)
        if not raw:
            return {"_error": "empty_response"}
        try:
            return _json.loads(raw)
        except Exception:
            return {"_error": f"parse_fail: {raw[:200]}"}

    # ── Step 1: find a tab with authInfo in sessionStorage ───────────────────
    uw_tabs = _scan_uw_tabs()
    log.info(f"[uworld] Found {len(uw_tabs)} UWorld tab(s)")

    auth_tab = _find_authinfo_tab(uw_tabs)

    if not auth_tab:
        # No tab has authInfo yet — navigate to dashboard to trigger auth
        log.info("[uworld] No tab with authInfo found. Navigating to dashboard...")
        # Prefer an existing UWorld tab to navigate, else use active tab
        if uw_tabs:
            wi0, ti0, url0, _ = uw_tabs[0]
            _uw_set_tab_url(wi0, ti0, f"{UWORLD_APP_BASE}/dashboard/{COURSE_ID}")
        else:
            _chrome_navigate(f"{UWORLD_APP_BASE}/dashboard/{COURSE_ID}")
        time.sleep(6)
        # Re-scan
        uw_tabs = _scan_uw_tabs()
        auth_tab = _find_authinfo_tab(uw_tabs)

    if not auth_tab:
        existing = _load_existing()
        return {
            "status": "auth_required",
            "sessions": existing.get("sessions", []),
            "weak_topics": existing.get("weak_topics", []),
            "incorrect": existing.get("incorrect", []),
            "source": "cache",
            "message": (
                f"UWorld authInfo not found in any open {BROWSER_APP} tab. "
                f"Please open {BROWSER_APP}, navigate to https://apps.uworld.com/courseapp/usmle/v50/en-US/dashboard/{COURSE_ID} "
                f"and wait for it to fully load, then click Refresh."
            ),
        }

    wi, ti, authinfo = auth_tab
    log.info(f"[uworld] Using tab w{wi}t{ti} with authInfo (at_len={len(authinfo.get('at',''))}, apiSubKey_len={len(authinfo.get('apiSubKey',''))})")

    # ── Step 2: GetTestRecords — fetch all test history ───────────────────────
    api_records = _uw_api_call(
        f"https://gateway-api.uworld.com/api/qbank/GetTestRecords/{QBANK_ID}/0",
        wi, ti, authinfo, timeout=25,
    )

    if isinstance(api_records, dict) and "_error" in api_records:
        log.warning(f"[uworld] GetTestRecords failed: {api_records}")
        existing = _load_existing()
        err = str(api_records.get("_error", "unknown"))
        # Give the user an actionable message instead of "HTTP 401". This
        # is the most common failure mode and was being misread as a code
        # bug ("are these bugs we added?") when it's just a stale browser
        # session.
        if "401" in err or "Unauthorized" in err.lower():
            msg = (
                "UWorld session expired. Open https://www.uworld.com in "
                f"{BROWSER_APP} and log back in, then click Refresh. "
                "(Showing your last cached data in the meantime.)"
            )
            status = "logged_out"
        elif "403" in err:
            msg = (
                f"UWorld blocked the request (403). Try opening UWorld in "
                f"{BROWSER_APP} fresh, then Refresh."
            )
            status = "logged_out"
        else:
            msg = f"UWorld scrape failed: {err}. Showing cached data."
            status = "error"
        return {
            "status": status,
            "sessions": existing.get("sessions", []),
            "weak_topics": existing.get("weak_topics", []),
            "incorrect": existing.get("incorrect", []),
            "source": "cache",
            "message": msg,
        }

    if not isinstance(api_records, list):
        log.warning(f"[uworld] GetTestRecords returned unexpected type: {type(api_records)}")
        existing = _load_existing()
        return {
            "status": "error",
            "sessions": existing.get("sessions", []),
            "source": "cache",
            "message": f"Unexpected API response type: {type(api_records).__name__}",
        }

    log.info(f"[uworld] GetTestRecords returned {len(api_records)} records")

    # ── Step 3: Parse sessions from API response ──────────────────────────────
    # Real field names (verified 2026-04-26 from live API response):
    #   id (int, the testId), isEnded (bool), totalQuestions (int),
    #   totalQuestionCorrect (int), superDivisionName (subject), subDivisionName,
    #   topicName, dateEnded (str "Apr 07, 2026 4:55 PM"), scoreData.score (int 0-100)
    import datetime as _dt

    api_sessions: list[dict] = []
    for idx, rec in enumerate(api_records):
        if not rec.get("isEnded"):
            continue  # skip in-progress tests

        test_id = str(rec.get("id") or "")
        if not test_id:
            continue

        total_val = rec.get("totalQuestions") or 0
        correct_val = rec.get("totalQuestionCorrect") or 0

        # Score: from scoreData.score (0-100 int) or calculate from correct/total
        score_data = rec.get("scoreData") or {}
        score_val = score_data.get("score") if isinstance(score_data, dict) else None
        if score_val is None and total_val:
            score_val = round(correct_val / total_val * 100)
        if score_val is None:
            score_val = 0
        try:
            score = int(score_val)
        except Exception:
            score = 0

        # Topics: superDivisionName is the subject (e.g. "Surgery"), subDivisionName is subsystem
        subject = rec.get("superDivisionName") or rec.get("subDivisionName") or ""
        topic = rec.get("topicName") or ""
        topics: list[str] = []
        if subject and subject.lower() not in ("all", ""):
            topics.append(subject)
        if topic and topic.lower() not in ("multiple", "all", "") and topic not in topics:
            topics.append(topic)
        if not topics:
            topics = [subject or "UWorld"]

        # Date: API returns "Apr 07, 2026 4:55 PM" — keep as-is or normalize
        end_date = rec.get("dateEnded") or rec.get("dateStarted") or ""
        fmt_date = end_date
        try:
            # Parse "Apr 07, 2026 4:55 PM" → "Apr 7, 2026"
            # %-d is a GNU libc extension that fails on some macOS Python builds.
            d = _dt.datetime.strptime(end_date[:12].strip(), "%b %d, %Y")
            fmt_date = f"{d.strftime('%b')} {d.day}, {d.year}"
        except Exception:
            try:
                # ISO fallback
                d = _dt.datetime.fromisoformat(end_date[:10])
                fmt_date = f"{d.strftime('%b')} {d.day}, {d.year}"
            except Exception:
                pass

        api_sessions.append({
            "id": f"s{idx+1}",
            "platform": "uworld",
            "date": fmt_date,
            "score": score,
            "total": int(total_val),      # REAL question count from API
            "correct": int(correct_val),  # REAL correct count
            "topics": topics,             # REAL topics from API
            "test_id": test_id,
            # Per-test session has no inherent sequence — leave null. The
            # field is only meaningful on individual incorrect question
            # records (set per-q below as their 1-based position in the
            # testQuestionInfoList). Old code wrote percentile here which
            # made downstream URL construction land on the loading screen.
            "test_seq": None,
            "results_url": (
                f"{UWORLD_APP_BASE}/performance/test/results/{COURSE_ID}/{test_id}/0"
            ),
        })

    log.info(f"[uworld] Parsed {len(api_sessions)} completed sessions from API")

    # ── Step 4: GetTestRecordDetails — get per-test wrong QIDs ───────────────
    existing_data = _load_existing()
    existing_incorrects: list[dict] = existing_data.get("incorrect", [])

    # NOTE: an earlier version cleared records with bogus test_seq (>40,
    # the legacy percentile bug) to force re-scrape. That nuked ~70
    # sessions worth of wrongs because the scraper's per-tick limit
    # (_results_limit, default 10) couldn't refetch them all in one run,
    # leaving the user with empty wrong-question lists for almost every
    # session. The migration is REMOVED — bogus test_seq values are now
    # sanitized at read time in _load_uworld_data() and the per-question
    # URL falls back to the test overview when seq is invalid. Going
    # forward, new scrapes get correct test_seq; old data degrades
    # gracefully without losing the wrongs themselves.

    # Index by test_id to skip already-cached tests (incremental).
    # Build from BOTH incorrect entries AND the "scraped_test_ids" set that
    # tracks sessions which were fetched but had 0 wrong answers. Without
    # this second source, sessions with all-correct answers would never
    # appear in existing_test_ids and would be re-fetched on every refresh.
    scraped_test_ids_cached: set[str] = {
        str(t) for t in existing_data.get("scraped_test_ids", []) if t
    }
    existing_test_ids: set[str] = {
        str(i.get("test_id", "")) for i in existing_incorrects if i.get("test_id")
    } | scraped_test_ids_cached
    existing_qids: set[str] = {str(i.get("uworld_qid", "")) for i in existing_incorrects}
    new_incorrects: list[dict] = list(existing_incorrects)
    # Track all test_ids whose details we've fetched (regardless of wrong-answer count)
    scraped_test_ids: set[str] = set(scraped_test_ids_cached)

    partial = False
    results_scraped = 0

    log.info(f"[uworld] existing_test_ids size: {len(existing_test_ids)} (from {len(existing_incorrects)} incorrects + {len(scraped_test_ids_cached)} zero-wrong sessions)")

    # Sort sessions by ACTUAL date descending (most recent first), cap at limit.
    # ⚠️ Bug history: this used to be a string sort on `s.get("date","")`,
    # but the date format is "Apr 29, 2026" / "Oct 9, 2025" — lexicographically
    # "Oct..." > "Mar..." > "Apr..." (because 'O' > 'M' > 'A'), so the most
    # recent April 2026 sessions ended up at the bottom of the sort. With a
    # low _results_limit (e.g. .env had 25), the top of the sort was all
    # already-scraped 2025 sessions, so 0 new details would be fetched and
    # recent tests' wrongs never made it into the database. Parse to a real
    # datetime first, then sort.
    def _parse_session_date(s: dict) -> _dt.datetime:
        raw = (s.get("date") or "").strip()
        for fmt in ("%b %d, %Y", "%b %-d, %Y"):
            try:
                return _dt.datetime.strptime(raw, fmt)
            except Exception:
                pass
        # Sentinel: unparseable dates go to the end (oldest position).
        return _dt.datetime.min
    sessions_to_scrape = sorted(api_sessions, key=_parse_session_date, reverse=True)[:_results_limit]

    for i, sess in enumerate(sessions_to_scrape):
        test_id = sess.get("test_id", "")
        skip = test_id in existing_test_ids
        log.info(f"[uworld] iter {i}/{len(sessions_to_scrape)} test_id={test_id!r} skip={skip}")
        if not test_id:
            continue
        if skip:
            continue

        try:
            detail = _uw_api_call(
                f"https://gateway-api.uworld.com/api/qbank/GetTestRecordDetails/{test_id}",
                wi, ti, authinfo, timeout=30,
            )
        except Exception as exc:
            log.warning(f"[uworld] GetTestRecordDetails/{test_id} exception: {exc}")
            partial = True
            time.sleep(0.3)
            continue
        if isinstance(detail, dict) and "_error" in detail:
            log.warning(f"[uworld] GetTestRecordDetails/{test_id} failed: {detail}")
            partial = True
            # Small delay before next attempt
            time.sleep(0.3)
            continue

        # Real response: dict with testQuestionInfoList array
        # Fields per question: questionId, isCorrect, isIncorrect, isOmitted,
        #   subject, system, topic, topicAttribute, userAnswer
        if isinstance(detail, dict):
            q_list = detail.get("testQuestionInfoList") or []
        elif isinstance(detail, list):
            q_list = detail
        else:
            q_list = []

        wrong_count = 0
        # 1-based enumerate so test_seq matches the URL pattern UWorld
        # uses for individual-question deep-links:
        #   /performance/test/results/{course}/{test_id}/{seq}
        # Where seq is the question's position in the test (1..N).
        for seq, q in enumerate(q_list, start=1):
            if not isinstance(q, dict):
                continue
            qid = str(q.get("questionId") or q.get("qId") or q.get("id") or "")
            if not qid:
                continue
            # Use isIncorrect flag (not negation of isCorrect) for clarity
            is_incorrect = bool(q.get("isIncorrect") or (not q.get("isCorrect") and not q.get("isOmitted")))
            if not is_incorrect:
                continue
            if qid in existing_qids:
                continue

            new_incorrects.append({
                "uworld_qid": qid,
                "uworld_topic": q.get("system") or q.get("subject") or "",
                "uworld_system": q.get("system") or "",
                "uworld_category": q.get("topicAttribute") or "",
                "uworld_topic_name": q.get("topic") or "",
                "missed_at": sess.get("date", ""),
                "test_id": test_id,
                # Position in the test (1-based). Replaces the prior bug
                # where this was the session-level percentile.
                "test_seq": seq,
            })
            existing_qids.add(qid)
            wrong_count += 1

        log.info(f"[uworld] Test {test_id}: {wrong_count} new wrong QIDs from {len(q_list)} questions")
        results_scraped += 1
        existing_test_ids.add(test_id)
        # Track as scraped even if 0 wrong answers — prevents re-fetching
        # on every refresh for sessions that have all-correct answers.
        scraped_test_ids.add(test_id)
        time.sleep(0.2)  # polite delay between requests

    # ── Step 5: Persist and return ────────────────────────────────────────────
    payload = {
        "sessions": api_sessions,
        "weak_topics": [],
        "incorrect": new_incorrects,
        # Persist ALL scraped test_ids (not just ones with wrongs) so
        # incremental refresh skips them on future runs.
        "scraped_test_ids": sorted(scraped_test_ids),
        "scraped_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "scraped_from": f"https://gateway-api.uworld.com/api/qbank/GetTestRecords/{QBANK_ID}/0",
        "partial": partial,
    }
    _persist(payload)

    new_qid_count = len(new_incorrects) - len(existing_incorrects)
    msg = (
        f"API scrape: {len(api_sessions)} session(s). "
        f"Details fetched for {results_scraped} test(s). "
        f"{len(new_incorrects)} total wrong QIDs ({new_qid_count} new)."
    )
    if partial:
        msg += " Some per-test details failed (partial=true)."

    return {
        "status": "ok",
        "sessions": api_sessions,
        "weak_topics": [],
        "incorrect": new_incorrects,
        "incorrect_count": len(new_incorrects),
        "partial": partial,
        "source": "scraped",
        "message": msg,
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
            "message": f"Please log into Azure portal in {BROWSER_APP}, then say 'try again'.",
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
