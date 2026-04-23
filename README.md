# Jarvis — Personal Med Student Dashboard

A local-first, AI-powered command center for medical students. Jarvis brings your study tools, schedule, messages, and a conversational AI agent into one dark-mode dashboard.

---

## What it does

- **Widgets** — study streak heatmap, Anki stats, QBank performance, NBME score tracker, Pomodoro timer, calendar, email, messages, Spotify
- **Drag & resize layout** — rearrange widgets freely; toggle any widget on/off; layout persists in localStorage
- **Jarvis chatbot** — conversational agent that can take actions on your behalf (draft emails, check your Anki stats, tell you what to study next)
- **Morning briefing** — opens with a natural-language summary of your day
- **Smart study loop** — nightly scrape of UWorld/TrueLearn → identify weak topics → unsuspend matching AnKing cards in Anki

---

## Architecture

```
jarvis/
├── frontend/          # Next.js 15 — dashboard UI, widgets, chatbot interface
└── backend/           # Python (FastAPI) — agent brain, tool integrations, scrapers
```

The chatbot is backed by Claude (Anthropic API) running as an agent with tool access. The dashboard widgets are the read layer; the chatbot is the write layer.

---

## Integrations

| Integration | How |
|---|---|
| Anki | AnkiConnect HTTP API (local) |
| Outlook / Calendar | Microsoft Graph API |
| iMessage | macOS SQLite database (read-only) |
| UWorld / TrueLearn | Nightly browser automation |
| Spotify | Spotify Web API |

> **Privacy note:** Jarvis runs entirely on your local machine. No data leaves your device except to the services you explicitly authenticate (Outlook, Spotify, Anthropic API). No patient data, no clinical records, not HIPAA-compliant — personal study use only.

---

## Getting started

### Prerequisites

- Node.js 18+
- Python 3.11+
- [Anki](https://apps.ankiweb.net/) with [AnkiConnect](https://ankiweb.net/shared/info/2055492159) installed
- Anthropic API key

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
uvicorn main:app --reload
# → http://localhost:8000
```

### Config

Copy `jarvis.config.example.ts` (coming soon) to `jarvis.config.ts` and fill in your rotation name, shelf date, and which contacts to show in the messages widget. No personal info is hardcoded anywhere in the repo.

---

## Features in progress

- [ ] Backend FastAPI server + Claude agent wiring
- [ ] AnkiConnect tool (stats, unsuspend, search by tag)
- [ ] Microsoft Graph tool (read mail, draft replies, read calendar)
- [ ] iMessage read tool (local SQLite)
- [ ] UWorld/TrueLearn nightly scraper
- [ ] Spotify playback tool
- [ ] `/prep [topic]` chatbot command — 60-second oral presentation skeleton
- [ ] `/eod` end-of-day debrief
- [ ] Cmd+K command palette
- [ ] Smart morning briefing (Anki due count, weakest topic, weather, urgent messages)

---

## Open source

Contributions welcome. If you adapt this for your own rotation or school, keep personal data out of the repo — use the config file pattern for anything user-specific.

MIT License
