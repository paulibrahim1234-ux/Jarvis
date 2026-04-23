#!/usr/bin/env bash
# grant-permissions.sh — trigger every macOS Automation dialog Jarvis needs
#
# macOS only prompts for Automation permission the FIRST time a script tries
# to control an app. This script pokes every app Jarvis uses so all dialogs
# fire in one sitting — click Allow on each.
#
# Usage: bash scripts/grant-permissions.sh
#
# Full Disk Access cannot be granted programmatically by design. This script
# opens the FDA pane in System Settings and prints the exact path to add.

set -u
IFS=$'\n\t'

if [[ -t 1 ]]; then
    GRN=$'\033[32m'; YLW=$'\033[33m'; CYN=$'\033[36m'; BLD=$'\033[1m'; RST=$'\033[0m'
else
    GRN=""; YLW=""; CYN=""; BLD=""; RST=""
fi

JARVIS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="${JARVIS_ROOT}/backend/.venv/bin/python3.12"
REAL_PY="$(readlink -f "$VENV_PY" 2>/dev/null || readlink "$VENV_PY" || echo "$VENV_PY")"
FRAMEWORK_ROOT="${REAL_PY%/bin/python3.12}"
PYTHON_APP_BIN="${FRAMEWORK_ROOT}/Resources/Python.app/Contents/MacOS/Python"

echo
echo "${BLD}${CYN}Jarvis Permission Granter${RST}"
echo
echo "This will:"
echo "  1. Trigger Automation dialogs for Outlook, Spotify, Messages, Calendar,"
echo "     Mail, Finder, System Events — click Allow on each popup."
echo "  2. Open System Settings to the Full Disk Access pane so you can add"
echo "     the Python binary (it can't be added programmatically)."
echo
read -r -p "Continue? [y/N] " ans
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# ── 1. Automation — poke each app ────────────────────────────────────────────
echo
echo "${BLD}Triggering Automation dialogs...${RST}"
echo "${YLW}Click Allow on each popup. If an app isn't installed, errors are safe to ignore.${RST}"
echo

poke() {
    local app="$1"
    local script="$2"
    echo -n "  Poking ${app}... "
    # Run in background with 3s timeout so a hung dialog doesn't block subsequent apps.
    # osascript will block until the dialog is dismissed; that's fine — we WANT the
    # user to see and click Allow.
    local out
    out=$(osascript -e "$script" 2>&1)
    if [[ "$out" == *"not allowed"* || "$out" == *"Not authorized"* ]]; then
        echo "${YLW}blocked (dialog shown or denied)${RST}"
    elif [[ "$out" == *"execution error"* ]]; then
        echo "${YLW}${out}${RST}"
    else
        echo "${GRN}ok${RST}"
    fi
}

poke "Microsoft Outlook" 'tell application "Microsoft Outlook" to get name'
poke "Spotify"           'tell application "Spotify" to get name'
poke "Messages"          'tell application "Messages" to get name'
poke "Calendar"          'tell application "Calendar" to count calendars'
poke "Mail"              'tell application "Mail" to get name'
poke "Finder"            'tell application "Finder" to get name of startup disk'
poke "System Events"     'tell application "System Events" to get name of first process'

echo
echo "${BLD}If no dialogs appeared${RST} (e.g. you previously clicked Deny), open the"
echo "Automation pane directly and toggle each app under Terminal / Python:"
echo "  ${BLD}open \"x-apple.systempreferences:com.apple.preference.security?Privacy_Automation\"${RST}"
echo
echo "To fully reset a single app's dialog state, e.g. Outlook:"
echo "  ${BLD}tccutil reset AppleEvents com.microsoft.Outlook${RST}"
echo "  then re-run this script."

# ── 2. Full Disk Access — manual step, but we open the pane ─────────────────
echo
echo "${BLD}Full Disk Access (manual)${RST}"
echo
echo "  macOS requires you to add this binary to Full Disk Access by hand:"
echo
echo "    ${BLD}${PYTHON_APP_BIN}${RST}"
echo
echo "  This single FDA grant unlocks BOTH:"
echo "    - ${BLD}~/Library/Messages/chat.db${RST}              (iMessage reads)"
echo "    - ${BLD}~/Library/Application Support/AddressBook/${RST} (Contacts name resolution)"
echo
echo "  In the FDA pane:"
echo "    1. Click the '+' button."
echo "    2. Press ${BLD}Cmd+Shift+G${RST} in the file picker."
echo "    3. Paste the path above and press Return."
echo "    4. Toggle the new entry ON."
echo "    5. Also add Terminal (so shell scripts and sqlite3 can read both DBs)."
echo

# Copy the path to clipboard for convenience
if command -v pbcopy >/dev/null 2>&1; then
    printf '%s' "$PYTHON_APP_BIN" | pbcopy
    echo "  ${GRN}Path copied to clipboard.${RST}"
fi

read -r -p "Press Return to open the Full Disk Access pane in System Settings..."
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"

echo
echo "${BLD}After granting FDA, restart the backend:${RST}"
echo "  launchctl kickstart -k gui/\$(id -u)/com.jarvis.backend"
echo
echo "${BLD}Then re-verify with:${RST}"
echo "  bash scripts/check-permissions.sh"
echo
