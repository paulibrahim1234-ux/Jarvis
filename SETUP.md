# Jarvis Setup — Foolproof Walkthrough

This guide is for someone who just bought Claude Code (or Codex) and wants Jarvis running on their Mac. **You don't need to know how to code.** Your job is to copy-paste prompts and click links. Claude does the work.

> **Time required:** 15–25 minutes the first time. Maybe 5 minutes if you've done it before.
> **What you need:** A Mac, Claude Code installed (or Codex), and **either** an active Claude subscription **or** a separate Anthropic API key. Most people have the subscription — Phase 3 covers both.

---

## How to read this guide

- Text in **gray boxes labeled "Copy this prompt"** goes directly into Claude Code or Codex.
- After pasting, hit Enter and let Claude work. Don't interrupt unless something looks broken.
- If Claude asks a question, answer it.
- If something fails, jump to [Troubleshooting](#troubleshooting) at the end and paste the relevant prompt.

You will spend most of your time **waiting for Claude** and **clicking links**. That's it.

---

## Phase 0 — Before you start

You need these one-time things:

1. **Claude Code installed** — get it from https://claude.com/code. Sign in with your Claude account (Claude Pro or Claude Max subscription works fine; an Anthropic API key also works).
2. **A GitHub account** — sign up free at https://github.com if you don't have one.
3. **An Apple ID with admin rights on your Mac** — needed to install apps and grant permissions later.

You do NOT need: Homebrew, Node, Python, Anki, or any developer tools pre-installed. Claude will handle all of that. You **also don't need to buy an API key** if you already have a Claude subscription — your subscription covers what Jarvis sends to Claude. Phase 3 has a path for each.

---

## Phase 1 — Get the code onto your Mac

**Open Claude Code** (or Codex). Open Terminal too (Spotlight `Cmd+Space`, type "Terminal", hit Enter). In Terminal, type `cd ~` and hit Enter so you're in your home folder. Then run Claude Code from that folder by typing `claude` and hitting Enter.

> **Copy this prompt**
>
> ```
> Please set up Jarvis on this Mac. The repo is at https://github.com/paulibrahim1234-ux/Jarvis.
>
> 1. Clone it into ~/jarvis using git.
> 2. If git isn't installed, install it via xcode-select first.
> 3. After cloning, list the top-level files so I can confirm.
> 4. Don't install dependencies yet — that's the next prompt. Just clone and report.
> ```

**What Claude will do:** clone the repo, install Xcode Command Line Tools if needed (a system dialog may pop up — click "Install" and wait), and show you the folder contents.

**You'll know it worked when:** Claude tells you it sees folders named `frontend`, `backend`, `JarvisNative`, etc.

---

## Phase 2 — Install everything Jarvis needs

> **Copy this prompt**
>
> ```
> Install all of Jarvis's prerequisites on my Mac. I'm in ~/jarvis.
>
> Please install (skip any that are already installed):
> - Homebrew (https://brew.sh)
> - Node.js 20+
> - Python 3.12+
> - Anki desktop (https://apps.ankiweb.net)
> - AnkiConnect plugin (Anki addon code 2055492159 — open Anki, Tools → Add-ons → Get Add-ons, paste the code, restart Anki)
>
> Also:
> - In ~/jarvis/frontend, run `npm install`.
> - In ~/jarvis/backend, create a Python virtualenv at .venv and run `pip install -r requirements.txt` inside it.
>
> When done, run `node --version`, `python3 --version`, and confirm both venv and node_modules exist. Tell me which step failed if any.
> ```

**What Claude will do:** install Homebrew (you may need to enter your Mac password once — it's safe), install Node and Python, open Anki and walk you through installing the AnkiConnect add-on, install all npm and pip packages.

**Manual step you may have to do:** if Anki opens for the first time and asks for an account, just close that window — you can use it offline. The AnkiConnect add-on requires Anki to restart; let Claude or yourself restart it.

**You'll know it worked when:** Claude says all four installs succeeded and confirms node and python versions.

---

## Phase 3 — Give Jarvis your Anthropic credentials

Jarvis needs to talk to Claude (Anthropic). There are **two ways** to do this — pick whichever describes you.

> **Note for Codex users**: Codex (OpenAI) can run all the setup commands in this guide, but it can't replace the Anthropic credential Jarvis needs at runtime. The Jarvis backend itself uses Claude. So even if you use Codex to set things up, you still need a Claude subscription or Anthropic API key for the backend.

---

### Path A — You have a Claude subscription (most people)

This is the path if you signed up for Claude Pro or Claude Max and use Claude Code by signing in with that account. You **do not need to buy an API key separately**. Your subscription pays for the model calls Jarvis makes.

> **Copy this prompt**
>
> ```
> I have a Claude subscription (Pro or Max). My Claude Code CLI is already signed in to my account. I want Jarvis to use my subscription too — no separate API key.
>
> Please:
> 1. Find my Claude Code OAuth token. Try in this order:
>    a. Run `printenv CLAUDE_CODE_OAUTH_TOKEN` — if it returns a value starting with sk-ant-oat-, use that.
>    b. If empty, try the macOS Keychain: `security find-generic-password -a $USER -s "Claude Code-credentials" -w 2>/dev/null` (the entry name varies by version — also try "claude-code", "claude.ai-credentials").
>    c. If empty, check ~/.claude/credentials.json or ~/.config/claude/credentials.json.
>    d. If still empty, tell me to run `claude /login` in a new terminal, then re-run this prompt.
> 2. Once you have the token (it starts with sk-ant-oat-), copy ~/jarvis/backend/.env.example to ~/jarvis/backend/.env if it doesn't exist, then add or replace the line: CLAUDE_CODE_OAUTH_TOKEN=<token>
> 3. Make sure ANTHROPIC_API_KEY is empty or commented out (Jarvis prefers the OAuth token if both are set).
> 4. Don't print the token back. Confirm it's saved and that backend/.env is gitignored (run `git check-ignore -v backend/.env`).
> 5. Tell me to move on to Phase 4.
> ```

**Why this works:** Jarvis's backend auto-detects whether the credential is an OAuth token (starts with `sk-ant-oat-`) or an API key (starts with `sk-ant-api-`) and adds the right Bearer header + OAuth beta flag. Subscription users never need the Anthropic Console.

**Heads-up:** If you ever uninstall Claude Code or sign out, the token rotates and Jarvis chat will stop working. Re-run the prompt above to refresh.

---

### Path B — You have a separate Anthropic API key

This is the path if you went to console.anthropic.com and created an API key (pay-as-you-go billing, separate from any subscription). You'll see usage charges per token.

**Manual step:**

1. Go to https://console.anthropic.com/settings/keys.
2. Click **Create Key**, name it "Jarvis", copy the key (starts with `sk-ant-api-`).
3. Keep that key handy — paste it into the next prompt.

> **Copy this prompt** (replace `PASTE_KEY_HERE` with your real key)
>
> ```
> I have an Anthropic API key (not a subscription). Please save it to ~/jarvis/backend/.env so Jarvis can use it.
>
> The key is: PASTE_KEY_HERE
>
> Steps:
> 1. Copy ~/jarvis/backend/.env.example to ~/jarvis/backend/.env if it doesn't exist.
> 2. Set the line ANTHROPIC_API_KEY= to my key.
> 3. Make sure CLAUDE_CODE_OAUTH_TOKEN is empty or commented out so it doesn't override.
> 4. Don't print the key back — just confirm it's set.
> 5. Verify backend/.env is gitignored (run `git check-ignore -v backend/.env`).
> ```

**You'll know it worked (either path):** Claude confirms the credential is saved and that backend/.env is gitignored. After Phase 4, the dashboard's chat panel will respond. If it says "No Anthropic credentials found," re-run the prompt for your path.

---

## Phase 4 — Start Jarvis (first boot)

> **Copy this prompt**
>
> ```
> Please start Jarvis. I want both the backend and the frontend running.
>
> Steps:
> 1. Start the backend: from ~/jarvis/backend, with the venv activated, run `uvicorn main:app --reload` in the background.
> 2. Wait 3 seconds, then curl http://localhost:8000/health and show me the output.
> 3. Start the frontend: from ~/jarvis/frontend, run `npm run dev` in the background.
> 4. Wait 5 seconds, then curl http://localhost:3000 and confirm it returns HTML.
> 5. Tell me both are running. Don't open my browser yet.
> ```

**What you'll do:** open Comet (or Chrome/Safari) yourself and visit `http://localhost:3000`. You should see the Jarvis dashboard.

**You'll know it worked when:** the dashboard loads with widgets visible. Some widgets will say "not connected" — that's normal and we'll fix it next.

---

## Phase 5 — Grant macOS permissions

For the Outlook, iMessage, Calendar, and Spotify widgets to actually read your data, macOS needs to give Jarvis permission. The first time the backend tries to read iMessage, macOS will pop up a permission dialog.

> **Copy this prompt**
>
> ```
> Walk me through granting Jarvis the macOS permissions it needs.
>
> 1. Open the file ~/jarvis/PERMISSIONS.md and read it.
> 2. Tell me, in plain English, exactly which checkboxes I need to flip in System Settings → Privacy & Security. List each app or service one at a time.
> 3. After I do each one, ask me "done?" before moving to the next.
> 4. The most important one is Full Disk Access for the Python binary that's running the backend. Find that exact path and give it to me.
> ```

**What you'll do:** open System Settings → Privacy & Security → Full Disk Access, click `+`, paste the path Claude gave you, hit Enter, toggle ON. Repeat for Automation if needed.

**You'll know it worked when:** refreshing `http://localhost:3000`, the Messages widget shows real conversations.

---

## Phase 6 — Optional: Spotify Web API

If you want Jarvis to control Spotify with full features (search, play playlists), you need a free Spotify Developer app. Skip this section if you don't care.

**Manual step:**

1. Go to https://developer.spotify.com/dashboard.
2. Click **Create app**, name it "Jarvis", any description, no website needed.
3. **Redirect URI**: paste exactly `http://127.0.0.1:8000/auth/spotify/callback`.
4. Save. On the app page, copy your **Client ID** and **Client Secret** (click "View client secret").

> **Copy this prompt** (replace `CLIENT_ID` and `CLIENT_SECRET`)
>
> ```
> Save my Spotify Web API credentials.
>
> Client ID: CLIENT_ID
> Client Secret: CLIENT_SECRET
>
> Open http://localhost:8000/setup in my default browser, then walk me through pasting them into the Spotify section. Or write them to ~/jarvis/backend/.env directly if that's easier.
>
> After saving, restart the backend so the new credentials load. Confirm by curling http://localhost:8000/health and checking that "spotify" is true.
> ```

**You'll know it worked when:** the Spotify widget shows your currently playing track and the "Connect Web API" button no longer errors.

---

## Phase 7 — Optional: UWorld scrape (medical students)

This pulls your real UWorld test history into the QBank widget and maps wrong questions to AnKing cards. Only useful if you're a med student using UWorld.

**Manual step:**

1. Open Comet (or your default browser) and log into https://www.uworld.com. Make sure you stay logged in.
2. Find your **course ID** in the URL of your dashboard. After login, the URL looks like `https://apps.uworld.com/courseapp/usmle/v50/en-US/dashboard/12345678` — that 8-digit number is your course ID.

> **Copy this prompt** (replace `MY_COURSE_ID`)
>
> ```
> Configure UWorld for Jarvis.
>
> 1. My UWorld course ID is MY_COURSE_ID. Add it to ~/jarvis/backend/.env as JARVIS_UWORLD_COURSE_ID and to ~/jarvis/frontend/.env.local as NEXT_PUBLIC_UWORLD_COURSE_ID.
> 2. Restart the backend.
> 3. Make sure I'm logged into UWorld in my default browser (Comet, Chrome, whatever) — open https://apps.uworld.com/courseapp/usmle/v50/en-US/previoustests/MY_COURSE_ID for me.
> 4. Trigger a scrape: curl -X POST http://localhost:8000/widgets/uworld/refresh
> 5. Show me how many sessions and how many wrong questions came back.
> ```

**You'll know it worked when:** Claude reports "scraped 50+ sessions, 200+ wrong QIDs" or similar. The QBank widget on the dashboard now shows your real test history.

---

## Phase 8 — Optional: Anki suggestion index (med students)

After UWorld is scraping, run this once to build the Anki QID → card index. It walks your AnKing deck once (~30 seconds) and never bothers Anki again.

> **Copy this prompt**
>
> ```
> Build the Jarvis Anki suggestion index. I have AnKing Step 2 v12 installed in Anki.
>
> 1. Make sure Anki is open and AnkiConnect is responding (curl http://localhost:8765 with a version request).
> 2. POST to http://localhost:8000/widgets/anki/build-index to start the build.
> 3. Poll http://localhost:8000/widgets/anki/build-index/status every 5 seconds until "running" is false.
> 4. Tell me the final index size and whether it succeeded.
>
> If Anki says "collection is not available" mid-build, that's a transient — the build retries automatically with backoff.
> ```

**You'll know it worked when:** Claude reports an index of ~4000 entries built. After this, clicking on any UWorld test in the dashboard shows the wrong-question detail with matching Anki cards.

---

## Phase 9 — Test the agent

> **Copy this prompt**
>
> ```
> Open http://localhost:3000 in my browser if it's not already open. Then test the chat panel:
>
> 1. Tell me to type "hi" into the chat panel and report what Jarvis says.
> 2. Then tell me to type "what's on my calendar tomorrow" and report what Jarvis says.
> 3. If either fails, look at the backend logs at ~/Library/Logs/jarvis-backend.err.log and explain what went wrong.
> ```

**You'll know it worked when:** Jarvis replies in plain English to both prompts. Calendar reply will list real events (assuming you have Apple Calendar populated).

---

## You're done

The dashboard is at http://localhost:3000 and stays running as long as both servers are alive. To start Jarvis after a reboot, just run this prompt:

> **Copy this prompt**
>
> ```
> Start Jarvis. Run the backend (uvicorn main:app --reload from ~/jarvis/backend with venv) and the frontend (npm run dev from ~/jarvis/frontend) in the background. Confirm both are healthy by curling /health and / respectively.
> ```

Or set up the launchd service for auto-start on login (advanced, skip for now).

---

## Troubleshooting

If anything looks broken, paste one of these:

### "Backend not responding"

> ```
> Jarvis backend isn't responding. Diagnose:
> 1. Check if anything is listening on port 8000 (lsof -nP -iTCP:8000 -sTCP:LISTEN).
> 2. Check ~/Library/Logs/jarvis-backend.err.log tail for errors.
> 3. Try restarting via launchctl kickstart -k gui/$(id -u)/com.jarvis.backend (if installed) or by running uvicorn manually.
> 4. Tell me the root cause and the fix.
> ```

### "Spotify says client ID invalid"

> ```
> Spotify is rejecting Jarvis with "client ID invalid". Help me diagnose:
> 1. Print the redirect_uri from ~/jarvis/backend/.env.
> 2. Walk me to https://developer.spotify.com/dashboard, into my Jarvis app, into Settings, into Redirect URIs.
> 3. Confirm the redirect URI in my Spotify app exactly matches the one in .env.
> 4. If they don't match, tell me which one to fix.
> ```

### "UWorld scrape returns logged_out"

> ```
> Jarvis says my UWorld session is expired. Help me fix:
> 1. Tell me to open Comet (or my default browser) and re-log in to https://apps.uworld.com.
> 2. Once I confirm I'm in, retry the scrape (curl -X POST http://localhost:8000/widgets/uworld/refresh).
> 3. Show me the result.
> ```

### "Anki suggestions widget shows nothing"

> ```
> The Anki suggestions widget is empty. Diagnose:
> 1. curl http://localhost:8000/widgets/anki/suggestions and show me the response.
> 2. If "needs_index_build" is true, run the index build (Phase 8).
> 3. If suggestions count is 0 but qid_count > 0, that means none of my wrong UWorld questions match suspended cards in my AnKing deck — could be I've already unsuspended them. Confirm or refute that.
> ```

### "Anki itself froze"

> ```
> Anki is showing "Application Not Responding". Help:
> 1. Wait 60 seconds — sometimes Anki recovers from a busy AnkiConnect query.
> 2. If still frozen, force-quit Anki (Option-Cmd-Esc) and reopen it.
> 3. Confirm AnkiConnect is responding (curl http://localhost:8765 with version action).
> 4. Don't trigger any Anki-related Jarvis features until version returns OK.
> ```

### "Everything is broken, start over"

> ```
> Restart Jarvis from scratch. 
> 1. Kill any running uvicorn processes (lsof -nP -iTCP:8000 -sTCP:LISTEN -t | xargs -r kill).
> 2. Kill any running next dev processes (pgrep -f "next dev" | xargs -r kill).
> 3. Wait 2 seconds.
> 4. Start the backend, then the frontend, in that order.
> 5. Curl /health and /, confirm both up.
> ```

---

## Updating Jarvis later

Pull new commits and reinstall any new dependencies in one step:

> **Copy this prompt**
>
> ```
> Update Jarvis to the latest version from GitHub.
>
> 1. cd ~/jarvis
> 2. git fetch origin && git status — tell me if there are uncommitted local changes. If so, ask me what to do with them.
> 3. If clean, git pull --ff-only origin main.
> 4. Run npm install in frontend (in case package.json changed).
> 5. Run pip install -r requirements.txt in backend's venv (in case Python deps changed).
> 6. Restart both servers.
> 7. Tell me what changed in the new commits (git log --oneline previous_HEAD..new_HEAD).
> ```

That's it. The dashboard is yours.
