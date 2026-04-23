"""
Jarvis agent — Claude-powered brain.
Runs a full tool-use loop until Claude returns a final text response.
Supports image tool results (take_screenshot returns an image block).
Persists conversations + extracts facts via agent.memory.
"""

import json
import os
import anthropic
from tools import TOOLS, dispatch
from agent import memory

# OAuth tokens (sk-ant-oat...) need Bearer auth + oauth beta header.
# API keys (sk-ant-api...) use x-api-key.
_raw = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or ""
if _raw.startswith("sk-ant-oat"):
    client = anthropic.Anthropic(
        auth_token=_raw,
        default_headers={"anthropic-beta": "oauth-2025-04-20"},
    )
else:
    client = anthropic.Anthropic(api_key=_raw)

BASE_SYSTEM_PROMPT = """You are Jarvis, a personal AI assistant for a medical student (MS3, surgery rotation). You control their Mac directly — no OAuth or Azure setup needed for most things.

## Email (desktop apps — NO Azure/OAuth needed)
- mail_get_inbox(limit) — Apple Mail inbox (works for school email, Gmail, iCloud — USE THIS FIRST)
- outlook_get_inbox(limit) — Microsoft Outlook.app inbox (fallback)
- outlook_get_calendar_events(days) — upcoming events from Outlook.app
- outlook_send_email(to, subject, body) — send via Outlook.app

## Spotify (desktop app — NO OAuth needed)
- spotify_get_track() — current track, artist, state
- spotify_play_pause() — toggle play/pause
- spotify_next_track() / spotify_prev_track()
- spotify_set_volume(volume 0-100)
- spotify_play_search(query) — search and play by name

## Apple Calendar
- calendar_get_events(days) — all calendars, upcoming events

## Messages
- messages_send(to, message) — send iMessage/SMS
- messages_get_recent(contact, limit) — read conversation

## Anki
- anki_get_stats / anki_find_cards / anki_unsuspend_cards

## Mac control
- open_app(app_name) — open any app
- open_url(url) — open URL in browser
- run_applescript(script) — raw AppleScript
- take_screenshot() — see what's on screen
- send_notification(title, message) — macOS banner
- run_shell(command) — safe shell commands
- save_credential(key, value) — write to .env

## Browser (Chrome via AppleScript)
- browser_navigate / browser_read_page / browser_run_js / browser_click / browser_fill
- fetch_spotify_credentials() — auto-extract Spotify Client ID + Secret from dashboard
- fetch_azure_client_id() — auto-extract Azure client ID

## Rules — CRITICAL
- **ALWAYS use tools to answer** — don't guess about state. If user asks "is Outlook setup", CALL outlook_get_inbox to find out. If user says "outlook", ASK what they want done OR call open_app("Microsoft Outlook") to open it.
- **NEVER claim an app "isn't installed" without checking** — the user's Mac has Outlook, Spotify, Anki, Calendar, Messages all installed. If a tool errors, interpret it (permissions, app closed), don't assume uninstalled.
- **Calendar question → call calendar_get_events OR outlook_get_calendar_events** — don't just answer from memory.
- **Use known_facts and the dashboard snapshot** in the system prompt to personalize responses. The user has persistent memory across sessions — leverage it.
- Be concise. User is busy.
- NEVER access PHI.
- Confirm before sending emails or messages.
"""


async def chat_async(
    messages: list[dict],
    conversation_id: str | None = None,
    model_override: str | None = None,
) -> tuple[str, str]:
    """
    Run the agent loop. Returns (reply_text, conversation_id).
    - Creates a conversation if conversation_id is None.
    - Persists incoming user message + final assistant reply.
    - Injects dashboard snapshot + top facts into the system prompt.
    - Kicks off async fact extraction after the reply.
    """
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")):
        return (
            "⚠️ No Anthropic credentials found. "
            "Set ANTHROPIC_API_KEY in backend/.env or CLAUDE_CODE_OAUTH_TOKEN in your shell.",
            conversation_id or "",
        )

    # ── Conversation bootstrap ──
    if not conversation_id:
        conv = memory.create_conversation()
        conversation_id = conv["id"]

    # Persist the latest user message from the incoming payload.
    # Frontend sends full history; DB already has older turns, so only persist the final user turn.
    if messages:
        last = messages[-1]
        if last.get("role") == "user":
            content = last.get("content") or ""
            if isinstance(content, list):
                # defensive — flatten to text
                content = " ".join(
                    (c.get("text", "") if isinstance(c, dict) else str(c))
                    for c in content
                )
            memory.append_message(conversation_id, "user", str(content))

    # ── Build context: prefer DB history if frontend sent a short payload ──
    db_history = memory.get_recent_messages(conversation_id, limit=40)
    # Use DB history when present (source of truth); fall back to request payload.
    all_messages = db_history if db_history else list(messages)

    # ── Dashboard + facts ──
    try:
        dashboard = await memory.dashboard_snapshot_async()
    except Exception:
        dashboard = "(dashboard snapshot failed)"
    top_facts = memory.get_top_facts(limit=10)
    system_prompt = memory.build_system_prompt(BASE_SYSTEM_PROMPT, dashboard, top_facts)

    model = model_override or os.getenv("JARVIS_MODEL", "claude-haiku-4-5-20251001")

    final_text = ""
    for _ in range(25):  # max 25 tool-use rounds
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            tools=TOOLS,
            messages=all_messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
                    break
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    try:
                        result = dispatch(block.name, block.input)
                    except Exception as e:
                        result = {"error": str(e)}

                    if isinstance(result, dict) and result.get("type") == "image":
                        content = [result]
                    else:
                        content = json.dumps(result, default=str)

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                        }
                    )

            all_messages.append({"role": "assistant", "content": response.content})
            all_messages.append({"role": "user", "content": tool_results})
        else:
            break

    if not final_text:
        final_text = "I couldn't complete that — please try again."

    # Persist assistant reply.
    memory.append_message(conversation_id, "assistant", final_text)

    # Refresh last_used_at on surfaced facts.
    memory.touch_facts([])  # no-op placeholder; facts are touched when created

    # Fire-and-forget fact extraction.
    try:
        last_user = ""
        if messages:
            lu = messages[-1]
            if lu.get("role") == "user":
                c = lu.get("content") or ""
                last_user = c if isinstance(c, str) else str(c)
        if last_user:
            memory.extract_facts_async(client, last_user, final_text)
    except Exception:
        pass

    return final_text, conversation_id


def chat(messages: list[dict]) -> str:
    """Backwards-compatible sync wrapper (no conversation_id)."""
    import asyncio

    reply, _ = asyncio.run(chat_async(messages))
    return reply
