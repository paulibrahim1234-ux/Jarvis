# Jarvis macOS Permissions

Jarvis runs as a background service (launchd) and needs several macOS privacy
permissions to work. This doc lists every permission, how to grant it, how to
verify it, and what breaks if it's missing.

The **only** critical fact: macOS scopes permissions per-binary. The Python
that `launchctl` runs is **not** the Terminal you typed `python3` into. You
must grant permission to the binary the launchd job actually exec's.

## Quick audit

```bash
cd ~/jarvis
bash scripts/check-permissions.sh    # non-destructive diagnostic
bash scripts/grant-permissions.sh    # triggers all Automation dialogs
```

If the audit is green, you're done. If not, follow the fixes it prints.

## The binary that matters

The venv symlink resolves like this:

```
~/jarvis/backend/.venv/bin/python3.12
  → /opt/homebrew/opt/python@3.12/bin/python3.12
  → /opt/homebrew/Cellar/python@3.12/3.12.12_2/Frameworks/Python.framework/Versions/3.12/bin/python3.12
```

But macOS actually exec's the framework's `Python.app` bundle:

```
/opt/homebrew/Cellar/python@3.12/3.12.12_2/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python
```

That last path is what goes in Full Disk Access. Confirm with:

```bash
ps -p $(launchctl list | awk '$3=="com.jarvis.backend"{print $1}') -o command=
```

Because this path changes with every Homebrew Python upgrade (the `3.12.12_2`
version segment), re-run `scripts/check-permissions.sh` after any
`brew upgrade python@3.12` — you'll need to re-add the new binary to FDA.

## Permission matrix

Each row below has four columns that matter:
- **What it's for** — the tool/endpoint that depends on it
- **How to grant** — the exact System Settings path (deep link in `grant-permissions.sh`)
- **How to verify** — a one-line shell command that probes the permission non-destructively
- **What breaks if missing** — so you know the cost of skipping

### 1. Full Disk Access — iMessage SQLite
- **What it's for:** Reading `~/Library/Messages/chat.db` for `/widgets/imessage`, `_imessage_recent`, `_imessage_unread`.
- **How to grant:** System Settings → Privacy & Security → Full Disk Access → `+` → Cmd+Shift+G → paste the Python.app binary path (and also add Terminal).
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`
- **How to verify:** `sqlite3 ~/Library/Messages/chat.db "SELECT 1 FROM message LIMIT 1;"` prints `1`.
- **What breaks without it:** iMessage widget returns `available:false`; the chat.db probe fails with `unable to open database file`; all iMessage backend tools silently return empty.

### 2. Full Disk Access — Contacts SQLite
- **What it's for:** Reading the AddressBook SQLite store under `~/Library/Application Support/AddressBook/` for contact name resolution in iMessage, Outlook, and the chatbot.
- **How to grant:** Same FDA pane as above — the single FDA grant on the Python.app bundle + Terminal covers both chat.db and AddressBook.
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`
- **How to verify:** `ls ~/Library/Application\ Support/AddressBook/Sources/*/AddressBook-v22.abcddb 2>/dev/null | head -1` returns a path (meaning the directory is readable); a deeper probe is `sqlite3 "$(ls ~/Library/Application\ Support/AddressBook/Sources/*/AddressBook-v22.abcddb | head -1)" "SELECT count(*) FROM ZABCDRECORD;"` which prints an integer.
- **What breaks without it:** Contact names never resolve — iMessage widget shows raw phone numbers / Apple IDs; chatbot "message <name>" lookups fail.

### 3. Automation — Microsoft Outlook
- **What it's for:** `_outlook_inbox`, `_outlook_calendar`, `_outlook_send` and the Outlook widget.
- **How to grant:** First AppleScript call triggers the Allow dialog; otherwise System Settings → Privacy & Security → Automation → find Terminal (and/or Python) → enable Microsoft Outlook.
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"`
- **How to verify:** `osascript -e 'tell application "Microsoft Outlook" to return name'` returns `Microsoft Outlook`.
- **What breaks without it:** Outlook osascript fails with `-1743 Not authorized to send Apple events`; email + calendar widgets go dark.

### 4. Automation — Apple Mail
- **What it's for:** `_mail_inbox` (fallback when user hasn't wired Outlook).
- **How to grant:** Automation dialog on first call, or Settings → Privacy → Automation → Terminal → enable Mail.
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"`
- **How to verify:** `osascript -e 'tell application "Mail" to return name'` returns `Mail`.
- **What breaks without it:** `_mail_inbox` errors with `-1743`. Outlook users are unaffected.

### 5. Automation — Calendar.app
- **What it's for:** `_calendar_events`, `/widgets/apple-calendar`.
- **How to grant:** Automation dialog on first call, or Settings → Privacy → Automation → Terminal → enable Calendar.
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"`
- **How to verify:** `osascript -e 'tell application "Calendar" to count calendars'` returns an integer.
- **What breaks without it:** apple-calendar widget stays empty; event-read/create tools error with `-1743`.

### 6. Automation — Messages.app (send)
- **What it's for:** `_messages_send`, `_messages_recent` (the send path — read path goes through FDA on chat.db).
- **How to grant:** Automation dialog on first call, or Settings → Privacy → Automation → Terminal → enable Messages.
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"`
- **How to verify:** `osascript -e 'tell application "Messages" to return name'` returns `Messages`.
- **What breaks without it:** sending iMessages from the chatbot fails (reading still works via FDA).

### 7. Automation — Spotify
- **What it's for:** Now-playing widget, play/pause/skip control from chatbot.
- **How to grant:** Automation dialog on first call, or Settings → Privacy → Automation → Terminal → enable Spotify.
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"`
- **How to verify:** `osascript -e 'tell application "Spotify" to return name'` returns `Spotify` (requires Spotify to be installed — errors harmlessly otherwise).
- **What breaks without it:** Spotify widget cannot read track state; playback-control chatbot commands silently fail.

### 8. Automation — Finder & System Events (internal helpers)
- **What it's for:** Opening files/folders from the agent; window listing via `tell application "System Events"`.
- **How to grant:** Automation dialog on first call, or Settings → Privacy → Automation → Terminal → enable Finder and System Events.
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"`
- **How to verify:** `osascript -e 'tell application "Finder" to return name'` and `osascript -e 'tell application "System Events" to return name of first process'`.
- **What breaks without it:** Agent can't open Finder windows; window enumeration fails.

### 9. Accessibility (optional — not used today)
- **What it's for:** Future cliclick / pyautogui UI scripting. Jarvis does not use these yet.
- **How to grant:** System Settings → Privacy & Security → Accessibility → `+` → add Terminal (or the Python.app binary).
  Deep link: `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"`
- **How to verify:** `osascript -e 'tell application "System Events" to get name of every window of (first process whose frontmost is true)'` — errors with `1002 / assistive access` if denied.
- **What breaks without it:** Nothing current. Will break future UI-automation features.

> Contacts.app AppleScript automation is intentionally NOT used — the backend reads the AddressBook SQLite store directly under FDA (row 2 above). This is faster and avoids a second Automation grant.

## Step-by-step: first install

1. **Install Python and dependencies** (assumed done — Homebrew `python@3.12`
   and `~/jarvis/backend/.venv`).
2. **Run `bash scripts/grant-permissions.sh`.** This pokes every Automation
   target so the permission dialogs fire back-to-back. Click **Allow** on
   each. If an app isn't installed on this machine (e.g., Mail), osascript
   just errors and the script moves on — harmless.
3. **Full Disk Access is manual.** The grant script ends by opening the FDA
   pane and copying the Python.app bundle path to your clipboard. In the
   pane, click `+`, press **Cmd+Shift+G**, paste, press Return, and toggle
   the new entry ON. Also add **Terminal** while you're there (so `sqlite3`
   and ad-hoc `python3` commands from a shell can read `chat.db`).
4. **Restart the backend** so the new FDA grant takes effect:
   ```bash
   launchctl kickstart -k gui/$(id -u)/com.jarvis.backend
   ```
5. **Re-run `bash scripts/check-permissions.sh`.** All rows should say
   GRANTED.

## Verification

Every permission has a non-destructive probe in `scripts/check-permissions.sh`:

| Permission | Probe |
|------------|-------|
| FDA (shell) | `sqlite3 ~/Library/Messages/chat.db "SELECT 1"` |
| FDA (venv Python) | Python opens `chat.db` and runs `SELECT 1 FROM message LIMIT 1` |
| FDA (backend end-to-end) | `curl -s http://127.0.0.1:8000/widgets/imessage` returns `"available":true` |
| Automation: *App* | `osascript -e 'tell application "App" to get name'` |
| Accessibility | `osascript -e 'tell application "System Events" to get name of every window of ...'` |

## Common failure modes

### "unable to open database file" from `/widgets/imessage`

Cause: FDA granted to Terminal or to a different Python, but not to the
Python.app bundle that launchd actually exec's. After `brew upgrade
python@3.12` the bundle path changes and you need to re-add it.

Fix: check-permissions.sh prints the exact path; paste it into FDA; restart
the backend.

### AppleScript returns `execution error: Not authorized to send Apple events`

Cause: Automation permission for that specific app pair (Terminal → Outlook,
or Python → Spotify) was denied, or the dialog was never seen.

Fix: Open System Settings → Privacy & Security → Automation. Find Terminal
in the list, expand it, and enable the target app. Or: run
`scripts/grant-permissions.sh`, which re-triggers the dialog. If the dialog
doesn't appear, reset the specific entry:
```bash
tccutil reset AppleEvents com.apple.Terminal
```

### Permissions work in Terminal but not from launchd

launchd jobs inherit the permissions of the binary they exec, not the user's
shell. If Automation works when you run uvicorn manually from Terminal but
not when launchd starts it, grant the Automation permission to
**`/opt/homebrew/Cellar/python@3.12/.../Python.app`** specifically (not
Terminal). This rarely comes up because macOS generally applies the same
user-level permissions.

### Brew upgraded Python; permissions silently broke

Homebrew Python upgrades replace the versioned path. FDA is tied to the
specific bundle path, so after an upgrade the new Python.app has no FDA
and `/widgets/imessage` starts failing.

Fix: run `scripts/check-permissions.sh` — it prints the new path. Remove the
stale entry from FDA, add the new one, kickstart the backend.

## What the scripts do

- **`scripts/check-permissions.sh`** — resolves the real Python binary,
  probes each permission, prints a pass/fail table, and prints exact fix
  instructions for anything missing. Idempotent.
- **`scripts/grant-permissions.sh`** — interactively pokes every Automation
  target app so their permission dialogs fire in sequence. Then opens the
  FDA pane with the Python.app path on the clipboard. Nothing destructive.

Both scripts can be re-run safely at any time.
