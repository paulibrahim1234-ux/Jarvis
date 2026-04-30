<img width="970" height="1508" alt="PNG image" src="https://github.com/user-attachments/assets/f6169621-b40b-43bb-9bf7-3db38fb3c9bc" />
<img width="919" height="419" alt="IMG_6642" src="https://github.com/user-attachments/assets/d2ab51a6-9387-4d29-b2c6-8f991cc38b0c" />

# Jarvis

**A local-first AI dashboard for med students.** Lives on your Mac. Drives your apps. Knows your week.

Jarvis is a personal command center that turns your existing tools — Anki, Outlook, iMessage, Apple Calendar, UWorld, Spotify — into a single dark-mode dashboard, with a Claude-powered agent that can act on your behalf. Open a webpage, get a morning briefing. Click a UWorld test, see exactly which AnKing cards target your wrong answers. Ask Jarvis to find the time of an email's hidden appointment, and it'll open Outlook, read the body, and put it on your calendar.

Built for one med student. Open-sourced because the pattern works.

```
┌─────────────────────────────────────────────────────────────┐
│  Anki  •  Outlook  •  iMessage  •  Calendar  •  UWorld     │
│  Spotify  •  AnKing  •  TrueLearn  •  NBME                 │
└────────────────────────┬────────────────────────────────────┘
                         │  AppleScript / SQLite / browser
                         ▼
                  ┌──────────────┐
                  │  FastAPI     │   Tools, scrapers, cache
                  │  Backend     │
                  └──────┬───────┘
                         │  HTTP
                         ▼
              ┌────────────────────┐
              │  Next.js 16        │   Drag-and-resize widgets
              │  Dashboard + Chat  │   Claude conversational agent
              └────────────────────┘
```

---

## What's in the box

**Widgets that read your real life** — every one of these pulls live data from a real source, not a mock:

| Widget | Source | What it shows |
|---|---|---|
| Calendar | Apple Calendar (AppleScript) | Real events, ISO timestamps, auto-flips horizontal when widened |
| Email | Outlook Classic (AppleScript) | Inbox per account, with full-body read available to the agent |
| Messages | macOS `chat.db` (read-only) | Conversations DESC by latest, in-thread timestamps formatted properly |
| Anki | AnkiConnect | Due, reviewed today, retention %, study streak |
| QBank (UWorld) | UWorld JSON API via Comet session | Real test scores, real question counts, real subjects, click-to-expand wrong-question detail by system |
| Anki Suggestions | Pre-built QID→card index | One-time index of 4000+ AnKing UWorld cards; instant lookup of suspended cards matching your wrong UWorld questions |
| Study Streak | Anki review history | Per-day minutes heatmap |
| Spotify | Spotify desktop (AppleScript) + Web API | Now playing, control, search-and-play |
| NBME Tracker | Local JSON | Manual score logging, percentile and trend |
| Pomodoro | Local | Standard work/break with persistent state |
| Briefing | Aggregator | Morning summary of the day |

**Jarvis the agent** — Claude Opus 4.5 by default (falls back to Haiku on rate-limit). He can search your Outlook for "OIER", read the email body to find a 7:30 AM appointment, create the calendar event, all in one turn. He can play a Spotify track by name, send an iMessage, draft an Outlook reply, look up your Anki retention. The toolbelt grows as the dashboard does. OAuth token auto-refreshes in the background — no manual re-auth on expiry.

---

## Why this is different

- **Local-first**: The agent runs on your Mac. iMessage data is read from your local `chat.db`. Outlook is driven by AppleScript on the Outlook Classic process you already have open. No cloud copies, no third-party data brokers. The only outbound traffic is to APIs you explicitly authenticate (Anthropic, Spotify Web, Microsoft Graph).
- **Reuses sessions**: For UWorld, Jarvis controls your default browser (Comet by default — Chromium-based) via AppleScript and reuses your already-logged-in session. No need to store UWorld credentials. The same trick scrapes Spotify Developer Dashboard and Azure portal credentials when you ask.
- **Med-school specific**: Built around the workflow of clinical rotations and Step 2 prep. AnKing tag-format aware. UWorld + TrueLearn aware. Rotation calendar aware. Grand-rounds aware.
- **Honest about limits**: Not HIPAA-compliant. Not for patient data. Personal academic use only. Privacy details below.

---

## Getting started

> **Don't write code? Follow the [foolproof walkthrough in SETUP.md](SETUP.md)** — every step is a prompt you copy-paste into Claude Code (or Codex). Your job is to click links and answer questions; Claude does the work.

**Prereqs**: macOS, Node 18+, Python 3.11+, [Anki](https://apps.ankiweb.net/) + [AnkiConnect](https://ankiweb.net/shared/info/2055492159), an Anthropic API key **or** Claude Code subscription OAuth token, Outlook Classic (not "New Outlook"), Comet or Chrome as your default browser (for UWorld scraping).

```bash
# Frontend
cd frontend && npm install && npm run dev
# → http://localhost:3000

# Backend (separate terminal)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your keys
uvicorn main:app --reload
# → http://localhost:8000
```

Then visit `http://localhost:8000/setup` in your browser to paste Spotify / Microsoft / Anthropic credentials into a form (which writes them to `backend/.env`, gitignored). Credentials are hot-reloaded — no restart needed after a `/setup` update. Use the `jarvis` CLI (`jarvis restart`, `jarvis status`, `jarvis logs`) once launchd services are installed.

For the macOS-app integrations to work, you'll need to grant Full Disk Access to the Python binary running the backend (so it can read iMessage's `chat.db`) and Automation permissions for the apps Jarvis drives. See [PERMISSIONS.md](PERMISSIONS.md) for the full list.

---

## Architecture

```
jarvis/
├── frontend/                          # Next.js 16 (App Router)
│   ├── src/components/widgets/        # Each widget is a self-contained card
│   ├── src/components/chat/           # The chat panel + tool-call rendering
│   ├── src/lib/api.ts                 # Single typed surface for the backend
│   └── src/lib/calendar.ts            # Time helpers (multi-day-aware bucketing)
├── backend/                           # FastAPI
│   ├── api/                           # Routes (widgets, chat, auth, setup)
│   ├── agent/jarvis.py                # Async Claude agent loop with tool dispatch
│   ├── agent/memory.py                # SQLite-backed conversation + facts memory
│   ├── tools/                         # The agent's toolbelt (one file per integration)
│   │   ├── desktop_apps.py            # Outlook, Spotify, Calendar, Messages — AppleScript
│   │   ├── browser.py                 # Comet/Chrome control; UWorld scraper lives here
│   │   ├── imessage.py                # chat.db read-only queries
│   │   └── anki.py, contacts.py, …    # Plus auxiliary tools
│   └── storage/                       # Persistence (gitignored data files)
└── JarvisNative/                      # Optional Swift sidecar (EventKit calendar writes)
```

The agent loop is async (uses `AsyncAnthropic`) and dispatches tools through `asyncio.to_thread` so a long AppleScript invocation doesn't block other widget polls. Errors return HTTP 200 with a friendly message; chat never 500s.

---

## What's working today

All shipped and live: the widgets above, the agent toolbelt (search Outlook by keyword, read email bodies, create calendar events, find/unsuspend Anki cards by tag, control Spotify, send iMessages), the UWorld scrape pipeline (real test history + per-question wrong QIDs via the gateway-api JSON endpoints), the Anki QID→card index, the morning briefing, ResizeObserver-driven responsive layouts.

---

## Privacy

Jarvis runs entirely on your machine. Personal data — `backend/.env`, `backend/storage/uworld_history.json`, `backend/storage/anki_qid_index.json`, the SQLite chat memory under `~/.jarvis/` — is gitignored and never leaves your device. The repo intentionally does not commit any of those.

Outbound traffic only happens when you use a feature: Claude API for chat, Microsoft Graph for Outlook (if you choose the Graph path over AppleScript), Spotify Web for OAuth. The UWorld scraper makes XHR calls from inside your already-authenticated browser session — same as you'd do clicking around the SPA.

This is a personal tool. Not HIPAA-compliant. Don't use it on a patient-facing machine, and don't paste PHI into the chat.

---

## Roadmap

In flight or imminent:

- Email importance triage → calendar suggestions (school deadline detection)
- Cmd+K command palette
- `/prep [topic]` — 60-second oral presentation skeleton
- `/eod` end-of-day debrief
- Smart morning briefing with weakest-topic Anki seed

Done this past week (real, not roadmap):

- UWorld JSON-API pipeline replacing fragile DOM scraping
- Anki suggestion index (one-time build, instant lookup, doesn't crash Anki)
- Outlook Classic full-body read tool for the agent
- Calendar event creation tool
- Click-to-expand wrong-question detail per UWorld test
- ResizeObserver-driven horizontal calendar week view

---

## Contributing

Forks welcome. The repo is configured to disallow direct pushes to `main` and disallow force-pushes, so collaboration goes through pull requests. Personal data is firewalled out via `.gitignore`; if you contribute, make sure you don't include school/test data, credentials, or course-specific IDs in your patches. The `JARVIS_UWORLD_COURSE_ID` and `NEXT_PUBLIC_UWORLD_COURSE_ID` env vars exist for that reason.

---

## License

[MIT](LICENSE).
