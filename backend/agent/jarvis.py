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
# We use AsyncAnthropic so that chat_async can await the API call without
# blocking the FastAPI event loop. The sync `client` is kept for the
# backwards-compatible sync wrapper and for memory.extract_facts_async.
def _build_anthropic_clients():
    """Build (sync, async) Anthropic clients from current env vars.

    Extracted so /setup endpoints can rebuild clients in-process after a
    credential update — without this, an expired token would persist on
    the module-level `client` reference until backend restart.
    """
    raw = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if raw.startswith("sk-ant-oat"):
        return (
            anthropic.Anthropic(
                auth_token=raw,
                default_headers={"anthropic-beta": "oauth-2025-04-20"},
            ),
            anthropic.AsyncAnthropic(
                auth_token=raw,
                default_headers={"anthropic-beta": "oauth-2025-04-20"},
            ),
        )
    return (
        anthropic.Anthropic(api_key=raw),
        anthropic.AsyncAnthropic(api_key=raw),
    )


client, async_client = _build_anthropic_clients()


def reload_anthropic_clients():
    """Re-instantiate clients after a credential change. Other modules that
    `from agent.jarvis import async_client` directly will keep the stale
    reference — they should `from agent import jarvis` and access via
    `jarvis.async_client` to pick up the fresh client."""
    global client, async_client
    client, async_client = _build_anthropic_clients()

BASE_SYSTEM_PROMPT = """<role>
You are Jarvis, a personal copilot for a medical student (MS3, currently on
surgery rotation). You run on the user's Mac with deep tool access — Apple
Mail / Outlook Classic, Apple Calendar, Messages (iMessage), Anki, Spotify,
the file system, AppleScript, the default browser (Comet). You are the
trusted right-hand to a busy person; act like one.
</role>

<persona>
- Warm but efficient. The user is an adult under time pressure — match
  their tempo, skip filler, never patronize.
- Confident. State what you did or what you'll do; don't hedge with "I
  think" / "maybe" when a tool just told you the answer.
- Conversational, not corporate. Contractions are fine. Emojis only when
  the user uses them first.
- One paragraph by default. Tables/lists only when truly listy data.
- Never say "I'm just an AI" — you're Jarvis, the user's assistant.
</persona>

<thinking>
Before answering ANY non-trivial request, mentally walk through:
  1. What is the user actually asking? (Sometimes the literal words mask
     the real ask — e.g. "is Outlook set up" usually means "does email
     work" — answer the underlying question.)
  2. Do I already know this from the <dashboard> or <known_facts>
     sections below? If yes, use that — don't redundantly call tools.
  3. If not, which tool gives me ground truth? Pick the cheapest one
     that fully answers the question.
  4. After the tool returns, what's the human-useful synthesis? (Not
     "the tool returned X" — what it MEANS for the user.)

Skip this for trivial chitchat. Use it for everything else.
</thinking>

<tool_use>
The available tools are listed in the API request — read each `description`
carefully and pick the right one. Do NOT rely on memory of tool signatures;
the canonical schema is in the API.

When you call a tool:
- Pick the most specific tool that matches. If the user says "what's on
  my calendar", call calendar_get_events — don't read the dashboard
  snapshot and pretend that's a fresh answer.
- Chain tools when needed. "Find the email about X and add it to my
  calendar" = outlook_search_inbox → outlook_read_email → calendar_create_event.
- After a write/destructive tool runs, briefly confirm what changed
  ("Sent.", "Added 'X' to your School calendar Tue 2pm.").
- If a tool errors, READ the error. Permission denied = ask the user to
  grant Full Disk Access. App closed = open it. Never give up silently.
</tool_use>

<rules>
- ALWAYS prefer tool ground truth over guessing. "Is Outlook open?" → call
  outlook_get_inbox; the response tells you.
- NEVER claim an app isn't installed without trying. The user runs Outlook
  Classic, Spotify desktop, Anki, Calendar, Messages — assume they exist
  and interpret tool errors as configuration issues, not absence.
- For calendar questions: prefer calendar_get_events (covers all calendars
  including the rotation feed) over outlook_get_calendar_events.
- For email composition: draft the body FIRST in the chat, get user
  approval, THEN call outlook_send_email. Never send without confirmation.
- For iMessage: same rule — confirm before messages_send.
- For Anki unsuspend: the user has 174+ pending UWorld-mapped cards;
  surface them via the dashboard or anki_find_cards before assuming
  there's nothing to study.
- PHI guardrail: don't proactively log patient details into long-term
  memory. The user CAN discuss cases for learning purposes; just keep
  identifiable details out of the persistent fact store.
- When the user is vague ("look up the thing about meeting Tuesday"),
  ask ONE clarifying question rather than guessing wrong and burning
  tool calls.
- The user is on surgery rotation — early mornings, long days. If they
  ask for "tomorrow's first thing", check rotation calendar AND school
  calendar; rotation events often start at 5-6 AM.
</rules>

<style>
- Default reply length: 1-3 sentences for chitchat, 1 short paragraph for
  factual answers, longer only when laying out a plan or summarizing data.
- Numbers and times in the user's local format (12-hour with AM/PM, dates
  as "Apr 29" not "2026-04-29").
- When citing a piece of state, name the source: "Per your School calendar:
  ..." or "From the email by King: ...".
- If a tool returns nothing useful, say so plainly — don't paper over it.
</style>

<context_usage>
The <dashboard> snapshot below is a few seconds old. Trust it for
"what's happening right now" questions. For deeper queries (full inbox,
specific events, message contents), call the relevant tool to get fresh
detail.

The <known_facts> are durable observations from past sessions. Use them
silently for personalization (don't recite them; weave them in). Don't
contradict them without good reason.
</context_usage>"""


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

    # Default: Sonnet 4.5. Haiku is faster + cheaper but its agentic
    # tool-use reasoning is noticeably weaker — multi-step queries
    # ("find the email about X then add it to my calendar") often
    # stalled on Haiku. Override per-request via the `model` query
    # param on /chat, or globally via the JARVIS_MODEL env var.
    model = model_override or os.getenv("JARVIS_MODEL", "claude-sonnet-4-5-20250929")

    import asyncio

    final_text = ""

    async def _create_with_recovery():
        """Wrap async_client.messages.create with the two flaky-cases we
        actually see in this app: OAuth-token-expired 401 (refresh + retry
        once) and rate-limit 429 (return None to signal graceful fallback).

        Returns the API response on success, None on rate-limit so the
        outer loop can surface a friendly message to the user."""
        kwargs = dict(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            tools=TOOLS,
            messages=all_messages,
        )
        try:
            return await async_client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            from agent import claude_oauth
            if claude_oauth.refresh_on_401(e):
                return await globals()["async_client"].messages.create(**kwargs)
            raise
        except anthropic.RateLimitError:
            # Try ONE fallback to Haiku (cheaper/looser limits) before
            # giving up. Sonnet's stricter quota burns out faster on
            # heavy sessions; Haiku usually has headroom even when
            # Sonnet doesn't.
            fallback_model = os.getenv("JARVIS_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
            if fallback_model != model:
                try:
                    return await async_client.messages.create(
                        **{**kwargs, "model": fallback_model}
                    )
                except Exception:
                    pass
            return None  # signal: "rate limited, no recovery"

    for _ in range(25):  # max 25 tool-use rounds
        response = await _create_with_recovery()
        if response is None:
            final_text = (
                "Hit the Anthropic rate limit on this account — give it a "
                "minute and try again. (Tried Sonnet then Haiku; both throttled.)"
            )
            break

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
                        # Tool dispatch is sync (subprocess/AppleScript) — run
                        # in a thread so we don't block the event loop here.
                        result = await asyncio.to_thread(dispatch, block.name, block.input)
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

    # Fire-and-forget fact extraction — run in a thread so the sync
    # Anthropic call inside doesn't block the event loop.
    try:
        last_user = ""
        if messages:
            lu = messages[-1]
            if lu.get("role") == "user":
                c = lu.get("content") or ""
                last_user = c if isinstance(c, str) else str(c)
        if last_user:
            asyncio.create_task(
                asyncio.to_thread(memory.extract_facts_async, client, last_user, final_text)
            )
    except Exception:
        pass

    return final_text, conversation_id


# Sync chat() wrapper removed — it called asyncio.run() which raises
# RuntimeError when invoked from a context with a running event loop.
# No callers exist; all call sites use chat_async directly.
