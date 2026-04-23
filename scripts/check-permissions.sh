#!/usr/bin/env bash
# check-permissions.sh — Jarvis macOS permission diagnostic
#
# Non-destructive probes for every macOS permission Jarvis needs.
# Re-runnable. Prints a PASS/FAIL table plus exact fix instructions.
#
# Usage: bash scripts/check-permissions.sh

set -u  # fail on undefined vars; DO NOT set -e so one probe failure doesn't abort
IFS=$'\n\t'

# ── pretty printing ──────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; CYN=$'\033[36m'
    BLD=$'\033[1m'; DIM=$'\033[2m'; RST=$'\033[0m'
else
    RED=""; GRN=""; YLW=""; CYN=""; BLD=""; DIM=""; RST=""
fi

PASS="${GRN}GRANTED${RST}"
FAIL="${RED}MISSING${RST}"
WARN="${YLW}UNKNOWN${RST}"

MISSING_COUNT=0
declare -a FIX_INSTRUCTIONS=()

row() {
    # $1 = status, $2 = permission name, $3 = target
    printf "  %-30s  %s  %s\n" "$2" "$1" "${DIM}${3}${RST}"
}

note_missing() {
    MISSING_COUNT=$((MISSING_COUNT + 1))
    FIX_INSTRUCTIONS+=("$1")
}

# ── binary paths ─────────────────────────────────────────────────────────────
JARVIS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="${JARVIS_ROOT}/backend/.venv/bin/python3.12"
CHAT_DB="${HOME}/Library/Messages/chat.db"

# Resolve the REAL binary that gets exec'd (what FDA must be granted to)
if [[ -L "$VENV_PY" ]]; then
    REAL_PY="$(readlink -f "$VENV_PY" 2>/dev/null || readlink "$VENV_PY")"
else
    REAL_PY="$VENV_PY"
fi

# macOS actually runs Python.app (the framework bundle), not the plain binary.
# Resolve the bundle path so users add the right thing to FDA.
if [[ "$REAL_PY" == */bin/python3.12 ]]; then
    FRAMEWORK_ROOT="${REAL_PY%/bin/python3.12}"
    PYTHON_APP="${FRAMEWORK_ROOT}/Resources/Python.app"
    PYTHON_APP_BIN="${PYTHON_APP}/Contents/MacOS/Python"
else
    PYTHON_APP="(unresolved)"
    PYTHON_APP_BIN="$REAL_PY"
fi

echo
echo "${BLD}${CYN}Jarvis Permission Audit${RST}"
echo "${DIM}$(date)${RST}"
echo

echo "${BLD}Binary paths${RST}"
echo "  venv symlink ........ $VENV_PY"
echo "  symlink target ...... $REAL_PY"
echo "  Python.app bundle ... $PYTHON_APP"
echo "  exec'd binary ....... $PYTHON_APP_BIN"
echo

# ── backend status ───────────────────────────────────────────────────────────
echo "${BLD}Backend status${RST}"
BACKEND_PID="$(launchctl list 2>/dev/null | awk '$3=="com.jarvis.backend"{print $1}')"
if [[ -n "$BACKEND_PID" && "$BACKEND_PID" != "-" ]]; then
    echo "  launchd PID ......... $BACKEND_PID"
    RUNNING_BIN="$(ps -p "$BACKEND_PID" -o command= 2>/dev/null | awk '{print $1}')"
    echo "  running binary ...... $RUNNING_BIN"
else
    echo "  ${YLW}launchd not running — start with: launchctl load ~/Library/LaunchAgents/com.jarvis.backend.plist${RST}"
fi
echo

# ── 1. Full Disk Access (Messages/chat.db) ──────────────────────────────────
echo "${BLD}1. Full Disk Access${RST}"

# 1a. Shell (sqlite3) — informational
if sqlite3 "$CHAT_DB" "SELECT 1" >/dev/null 2>&1; then
    row "$PASS" "FDA: Terminal (sqlite3)" "shell can read chat.db"
else
    row "$FAIL" "FDA: Terminal (sqlite3)" "shell cannot read chat.db"
    note_missing "Terminal: System Settings → Privacy & Security → Full Disk Access → add Terminal"
fi

# 1b. The actual venv Python binary — the one that MATTERS
if [[ -x "$PYTHON_APP_BIN" ]]; then
    PROBE=$("$PYTHON_APP_BIN" - <<'PY' 2>&1
import sqlite3, sys, os
db = os.path.expanduser("~/Library/Messages/chat.db")
try:
    c = sqlite3.connect(db)
    c.execute("SELECT 1 FROM message LIMIT 1").fetchone()
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")
PY
)
    if [[ "$PROBE" == "OK" ]]; then
        row "$PASS" "FDA: venv Python.app" "can read chat.db"
    else
        row "$FAIL" "FDA: venv Python.app" "cannot read chat.db"
        note_missing "Python (backend): System Settings → Privacy & Security → Full Disk Access → click '+' and add:
      ${PYTHON_APP_BIN}
    (TIP: press Cmd+Shift+G in the file picker and paste the path)"
    fi
else
    row "$WARN" "FDA: venv Python.app" "binary not found at $PYTHON_APP_BIN"
fi

# 1b-contacts. AddressBook SQLite — Contacts access for name resolution
AB_DB=$(ls -1 "${HOME}/Library/Application Support/AddressBook/Sources/"*/AddressBook-v22.abcddb 2>/dev/null | head -1)
if [[ -n "$AB_DB" && -r "$AB_DB" ]]; then
    if sqlite3 "$AB_DB" "SELECT count(*) FROM ZABCDRECORD" >/dev/null 2>&1; then
        row "$PASS" "FDA: Contacts (AddressBook)" "can read AddressBook SQLite"
    else
        row "$FAIL" "FDA: Contacts (AddressBook)" "file exists but query blocked"
        note_missing "Contacts DB unreadable. Same FDA grant as chat.db — add the Python.app binary to System Settings → Privacy & Security → Full Disk Access. Deep link: open \"x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles\""
    fi
else
    row "$WARN" "FDA: Contacts (AddressBook)" "no AddressBook-v22.abcddb found (Contacts.app may never have synced)"
fi

# 1c. End-to-end: can the running backend actually return iMessage data?
if command -v curl >/dev/null 2>&1; then
    BACKEND_RESP=$(curl -s -m 5 -o /tmp/jarvis_perm_check_imsg.json -w "%{http_code}" http://127.0.0.1:8000/widgets/imessage 2>/dev/null)
    if [[ "$BACKEND_RESP" == "200" ]]; then
        # Look for available:true OR an error field mentioning chat.db
        if grep -q '"available":true' /tmp/jarvis_perm_check_imsg.json 2>/dev/null; then
            row "$PASS" "Backend /widgets/imessage" "returns live message data"
        elif grep -q "unable to open database" /tmp/jarvis_perm_check_imsg.json 2>/dev/null; then
            row "$FAIL" "Backend /widgets/imessage" "chat.db locked — FDA missing on running Python"
            note_missing "Running backend cannot read chat.db. After granting FDA above, restart: launchctl kickstart -k gui/\$(id -u)/com.jarvis.backend"
        else
            row "$WARN" "Backend /widgets/imessage" "200 but unclear payload (check /tmp/jarvis_perm_check_imsg.json)"
        fi
    else
        row "$WARN" "Backend /widgets/imessage" "HTTP $BACKEND_RESP (is launchd backend running?)"
    fi
    rm -f /tmp/jarvis_perm_check_imsg.json
fi

echo

# ── 2. Automation permissions (AppleScript control) ──────────────────────────
echo "${BLD}2. Automation${RST}"

test_automation() {
    local app="$1"
    local script="$2"
    local out
    out=$(osascript -e "$script" 2>&1)
    if [[ "$out" == *"not allowed"* || "$out" == *"Not authorized"* || "$out" == *"execution error"* ]]; then
        row "$FAIL" "Automation: $app" "osascript blocked"
        note_missing "$app: run \`bash scripts/grant-permissions.sh\` to trigger the Allow dialog. Or open the Automation pane directly:
      open \"x-apple.systempreferences:com.apple.preference.security?Privacy_Automation\"
      then expand Terminal (or Python) and enable $app."
        return 1
    elif [[ -n "$out" ]]; then
        row "$PASS" "Automation: $app" "osascript works"
        return 0
    else
        row "$WARN" "Automation: $app" "empty response — treat as working"
        return 0
    fi
}

test_automation "Microsoft Outlook" 'tell application "Microsoft Outlook" to get name'
test_automation "Spotify"           'tell application "Spotify" to get name'
test_automation "Messages"          'tell application "Messages" to get name'
test_automation "Calendar"          'tell application "Calendar" to count calendars'
test_automation "Mail"              'tell application "Mail" to get name'
test_automation "Finder"            'tell application "Finder" to get name'
test_automation "System Events"     'tell application "System Events" to get name of first process'

echo

# ── 3. Accessibility ────────────────────────────────────────────────────────
echo "${BLD}3. Accessibility (future UI automation)${RST}"

# If any process can enumerate window lists via System Events, accessibility is OK
AX_PROBE=$(osascript -e 'tell application "System Events" to get name of every window of (first process whose frontmost is true)' 2>&1)
if [[ "$AX_PROBE" == *"assistive access"* || "$AX_PROBE" == *"1002"* ]]; then
    row "$FAIL" "Accessibility: Terminal" "not granted"
    note_missing "Accessibility (optional for now): add Terminal at:
      open \"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility\"
    Only needed if/when cliclick or pyautogui UI automation gets added."
else
    row "$PASS" "Accessibility: Terminal" "can read window state"
fi

# Check if cliclick / pyautogui are present (Jarvis doesn't currently use either)
if command -v cliclick >/dev/null 2>&1; then
    row "$PASS" "cliclick installed" "$(command -v cliclick)"
else
    row "${DIM}INFO${RST}" "cliclick" "not installed (not currently required)"
fi

if "$PYTHON_APP_BIN" -c "import pyautogui" 2>/dev/null; then
    row "$PASS" "pyautogui importable" "in venv"
else
    row "${DIM}INFO${RST}" "pyautogui" "not installed (not currently required)"
fi

echo

# ── 4. Summary ───────────────────────────────────────────────────────────────
echo "${BLD}Summary${RST}"
if [[ $MISSING_COUNT -eq 0 ]]; then
    echo "  ${GRN}All checked permissions look good.${RST}"
    echo
    exit 0
fi

echo "  ${RED}${MISSING_COUNT} issue(s) found:${RST}"
echo
i=1
for fix in "${FIX_INSTRUCTIONS[@]}"; do
    echo "  ${BLD}${i}.${RST} $fix"
    i=$((i + 1))
done
echo
echo "  Next steps:"
echo "    1. Run ${BLD}bash scripts/grant-permissions.sh${RST} to trigger Automation dialogs interactively."
echo "    2. Jump straight to a pane with:"
echo "         ${BLD}open \"x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles\"${RST}   (Full Disk Access)"
echo "         ${BLD}open \"x-apple.systempreferences:com.apple.preference.security?Privacy_Automation\"${RST}  (Automation)"
echo "         ${BLD}open \"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility\"${RST} (Accessibility)"
echo "    3. Restart the backend: ${BLD}launchctl kickstart -k gui/\$(id -u)/com.jarvis.backend${RST}"
echo "    4. Re-run this script to confirm."
echo

exit 1
