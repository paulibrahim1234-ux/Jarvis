"""
Jarvis agent — Claude-powered brain.
Runs a full tool-use loop until Claude returns a final text response.
Supports image tool results (take_screenshot returns an image block).
Persists conversations + extracts facts via agent.memory.
"""

import asyncio
import json
import logging
import os
import random

import anthropic
from tools import TOOLS, dispatch
from agent import memory

# Module-level logger — avoids re-creating the logger on every chat turn.
# WHY: logging.getLogger() is cheap but not free; creating it inside
# chat_async added microseconds on every call and made the import structure
# harder to follow (stdlib modules belong at the top of the file, not
# inside functions).
_agent_log = logging.getLogger("jarvis.agent")

# Holds strong refs to fire-and-forget background tasks so the event loop
# does not garbage-collect a still-running task. Without this, a task
# created via `asyncio.create_task(...)` and never awaited can be cancelled
# mid-flight if the loop sweeps weak refs (Python 3.10+ behaviour).
# Pattern: _BG_TASKS.add(t); t.add_done_callback(_BG_TASKS.discard)
_BG_TASKS: "set[asyncio.Task]" = set()


def _parse_retry_after(exc: Exception, default: int = 10) -> int:
    """Parse the Retry-After header from a 429 response. Default 10s on parse failure.

    WHY a helper: the primary and Haiku-fallback rate-limit blocks both had
    identical try/except blocks with bare `except Exception: pass` — which
    silently discarded parse errors and obscured why the fallback value was
    used. Extracting to a helper deduplicates the logic, adds a debug log,
    and narrows the except to the types that can actually be raised
    (ValueError/TypeError from int(float(v)), AttributeError from .headers).
    """
    try:
        ra = getattr(exc, "response", None)
        if ra is not None:
            v = ra.headers.get("retry-after")
            if v is not None:
                return int(float(v))
    except (ValueError, TypeError, AttributeError):
        _agent_log.debug("Retry-After parse failed for exception: %r", exc)
    return default

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

BASE_SYSTEM_PROMPT = """<identity>
You are Jarvis, a personal copilot for a medical student (MS3, currently on surgery rotation). You run on the user's Mac with deep tool access — Outlook Classic, Apple Calendar, Messages (iMessage), Anki, Spotify, the file system, AppleScript, and the default browser (Comet). You are the trusted right-hand to a busy person under time pressure — be efficient, warm, and confident.
Never say "I'm just an AI" — you're Jarvis, the user's assistant. Match their tempo, skip filler, never patronize.
</identity>

<tool_use_policy>
ABSOLUTE RULE: For ANY question about live state — calendar, email, music, iMessage, Anki, files —
you MUST call the relevant tool. NEVER answer such questions from training data or memory.
If you are even slightly uncertain whether a question touches live state, call the tool anyway.

EXAMPLES OF PROPER TOOL ROUTING (these patterns ALWAYS require a tool call):
- "What's in my inbox?" → outlook_get_inbox or outlook_search_inbox
- "Any new emails?" → outlook_get_inbox
- "Did Dr. Smith email me?" → outlook_search_inbox with query="Dr. Smith"
- "Anything urgent today?" → CHAIN: calendar_get_events + outlook_search_inbox (call both in parallel)
- "Any urgent emails today?" → outlook_search_inbox
- "What time is my workout?" → calendar_get_events
- "What's my next event?" → calendar_get_events (single tool, fastest)
- "What's on my calendar this week?" → calendar_get_events with days=7
- "Any rotation this morning?" → calendar_get_events
- "What's playing on Spotify?" → spotify_get_track
- "Is something playing?" → spotify_get_track
- "Did Rish text me back?" → messages_get_recent with contact="Rish"
- "Did anyone text me?" → messages_get_recent (check recent contacts)
- "Any unread from school?" → outlook_search_inbox with query="rowan.edu"
- "What did school send me yesterday?" → outlook_search_inbox with query="rowan", natural_query="school emails received yesterday — use received_iso to rank most recent first from the prior day"
- "Any emails this morning?" → outlook_search_inbox with query="", natural_query="emails received this morning — use received_iso to filter to today's AM hours"
- "How many Anki cards do I have due?" → anki_get_stats
- "Any cards tagged cardiology?" → anki_find_cards with query="tag:UWorld::Cardiology"

Tool priority order:
1. calendar_get_events — for "what's on my calendar", "next event", "tomorrow's schedule", rotation times
2. outlook_search_inbox THEN outlook_read_email — for finding and reading emails. Always search first, then read.
3. outlook_get_inbox — for browsing the latest inbox messages without a specific keyword
4. messages_get_recent — for reading iMessages from a contact
5. messages_send — for sending iMessages (CONFIRM with user before sending)
6. spotify_get_track — for "what's playing", current music state
7. spotify_play_search — for "play [song/artist]"
8. anki_get_stats / anki_find_cards — for flashcard and study state

CHAIN POLICY: When a query needs multiple tools, call them in parallel where possible
(use multiple tool_use blocks in a single response — do not wait for one to finish before starting another).
Example for "Anything urgent today?": emit calendar_get_events AND outlook_search_inbox together.

Chaining rules:
- outlook_search_inbox → outlook_read_email: search first to find IDs, then read for full body
- ALWAYS confirm before any write action (send email, send iMessage, create event)
- After write actions, briefly confirm what changed ("Sent.", "Added 'X' to School calendar Tue 2pm.")
- If a tool errors: READ the error. Permission denied = ask user to grant Full Disk Access. App closed = tell user to open it. Never give up silently.

Context rules:
- If the user says "what's on my calendar" → call calendar_get_events (not the dashboard snapshot)
- If the user says "any unread email" → call outlook_get_inbox or outlook_search_inbox
- If the user is vague ("look up the thing about Tuesday") → ask ONE clarifying question rather than guessing
- For Anki: the user has 174+ pending UWorld-mapped cards; check anki_find_cards before assuming nothing to study
- For calendar: check BOTH rotation calendar and School calendar; rotation events often start 5-6 AM
- PHI guardrail: don't log patient identifiers into long-term memory. Clinical vocabulary (differentials, procedures, "the ICU case") is fine — actual MRNs, patient IDs, DOBs are not.
</tool_use_policy>

<style>
Match length to the question:
- Chitchat / yes-no / quick lookups: 1-3 sentences
- Live state queries ("what's on my calendar?", "any unread email?"): tight paragraph
- Analysis / teaching (differentials, mechanisms, "explain X", "compare A vs B"): go long with headings and bullets — don't cramp a real answer

Tone: warm but efficient. Contractions fine. Emojis only if user uses them first.
Numbers and times: 12-hour with AM/PM, dates as "Apr 29" not "2026-04-29".
Cite sources: "Per your School calendar: …" not "I believe…"
Confident: state what you did or will do; don't hedge with "I think" when a tool just gave you the answer.
</style>

<reminders>
ALWAYS call tools for live data. NEVER fabricate calendar/email/music/Anki/iMessage state.
When chaining: read intermediate results before acting, recover from errors, never silently give up.
For calendar: always call calendar_get_events — don't answer from the dashboard snapshot alone.
For email: search first (outlook_search_inbox), then read (outlook_read_email).
Confirm before send (email/iMessage). Draft → user approves → send.

FINAL MANDATE — re-read before every response:
NEVER answer questions about live state from memory. Even if you think you know the answer,
call the tool. The user prefers correct tool-use over fast generic answers.
When unsure if a tool exists for a question — try the closest one rather than guessing.
Inferential queries ("anything urgent?", "did anyone text me?", "what time is X?") ALWAYS
require tool calls — they are not small talk and must never be answered from training data.
</reminders>"""


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

    # A4: reject stale/deleted conversation IDs before touching the DB so the
    # user gets a clear actionable message instead of a generic 500 from the
    # FK constraint that append_message would raise.
    if conversation_id and not memory.conversation_exists(conversation_id):
        return ("Conversation not found — it may have been deleted. Start a new chat.", "")

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
    db_history = memory.get_recent_messages(conversation_id, limit=25)
    # Use DB history when present (source of truth); fall back to request payload.
    # Copy db_history into a new list so subsequent appends (tool-result
    # roundtrips) don't mutate the slice returned by get_recent_messages,
    # which could corrupt the in-process cache on concurrent conversations.
    all_messages = list(db_history) if db_history else list(messages)

    # ── Dashboard + facts + breadcrumbs ──
    try:
        dashboard = await memory.dashboard_snapshot_async()
    except Exception as exc:
        # WHY log vs. swallow: the root cause (network, import error, etc.)
        # is invisible to ops if we pass silently. Warning level keeps it out
        # of the error budget but still queryable in logs.
        _agent_log.warning("dashboard_snapshot failed: %s", exc)
        dashboard = "(dashboard snapshot failed)"
    top_facts = memory.get_top_facts(limit=10)
    breadcrumbs = memory.get_recent_tool_breadcrumbs(conversation_id, limit=10)
    system_prompt = memory.build_system_prompt(
        BASE_SYSTEM_PROMPT, dashboard, top_facts, breadcrumbs=breadcrumbs
    )

    # Default: Opus 4.5 — smarter multi-step reasoning and richer
    # answers than Sonnet. Opus has tighter rate limits, so the
    # RateLimitError handler below cascades to Haiku-4.5 on 429s.
    # Override per-request via the `model` query param on /chat, or
    # globally via the JARVIS_MODEL env var.
    model = model_override or os.getenv("JARVIS_MODEL", "claude-opus-4-5-20251101")

    final_text = ""
    # OS3: track stop_reason / last tool error so the fallback message is
    # specific instead of "please try again".
    last_stop_reason: str = ""
    last_tool_error: str | None = None
    # OS4: track which model actually answered (Haiku fallback footnote).
    actual_model: str = model
    rate_limited: bool = False
    # OS5: track tool names called this turn for cross-turn breadcrumbs.
    tool_calls_this_turn: list[str] = []

    # WHY return-type annotations on inner functions: makes it explicit that
    # _create_with_recovery can return None (rate-limited signal) vs. a real
    # Message; _call_and_log always returns a Message. Aids static analysis
    # and documents the contract without changing runtime behaviour.
    async def _create_with_recovery() -> anthropic.types.Message | None:
        """Wrap async_client.messages.create with the two flaky-cases we
        actually see in this app: OAuth-token-expired 401 (refresh + retry
        once) and rate-limit 429 (Retry-After-aware backoff + Haiku fallback).

        Returns the API response on success, None on rate-limit so the
        outer loop can surface a friendly message to the user.

        Side-effects: updates `actual_model` to the model that actually
        produced a reply (used by OS4 to footnote Haiku fallbacks)."""
        nonlocal actual_model, rate_limited
        # system_prompt is now a list of content blocks from build_system_prompt()
        kwargs = dict(
            model=model,
            max_tokens=8192,
            system=system_prompt,
            tools=TOOLS,
            messages=all_messages,
            extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"},
        )

        async def _call_and_log(m: str, kw: dict) -> anthropic.types.Message:
            """Call messages.create and log token usage including cache hits."""
            resp = await async_client.messages.create(**kw)
            if hasattr(resp, "usage"):
                _agent_log.info(
                    "tokens: input=%s output=%s cache_read=%s cache_write=%s model=%s",
                    getattr(resp.usage, "input_tokens", 0),
                    getattr(resp.usage, "output_tokens", 0),
                    getattr(resp.usage, "cache_read_input_tokens", 0),
                    getattr(resp.usage, "cache_creation_input_tokens", 0),
                    m,
                )
            return resp

        try:
            actual_model = model
            return await _call_and_log(model, kwargs)
        except anthropic.AuthenticationError as e:
            # WHY no `jarvis as _self`: the 401-retry path uses the closure-captured
            # `async_client` directly; the self-import was unused (ruff F401).
            from agent import claude_oauth
            # A5: refresh_on_401 calls urllib.request.urlopen (blocking I/O);
            # run it in a thread so we don't stall the FastAPI event loop.
            if await asyncio.to_thread(claude_oauth.refresh_on_401, e):
                # Use module-level reference so reload_anthropic_clients()
                # update is visible (closure would hold the pre-refresh binding).
                actual_model = model
                return await _call_and_log(model, {**kwargs, "model": model})
            raise
        except anthropic.RateLimitError as e:
            # Parse Retry-After header to avoid hammering the API too soon.
            # WHY _parse_retry_after: deduplicates the identical block in the
            # Haiku-fallback path and replaces bare `except Exception: pass`
            # with a targeted except + debug log.
            retry_after = _parse_retry_after(e, default=10)
            sleep_secs = min(retry_after, 60) + random.uniform(0, 1)
            _agent_log.warning(
                "rate_limit on %s — sleeping %.1fs before Haiku fallback", model, sleep_secs
            )
            await asyncio.sleep(sleep_secs)

            # Try ONE fallback to Haiku (cheaper/looser limits) before giving up.
            fallback_model = os.getenv("JARVIS_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
            if fallback_model != model:
                try:
                    actual_model = fallback_model
                    return await _call_and_log(fallback_model, {**kwargs, "model": fallback_model})
                except anthropic.AuthenticationError:
                    raise  # A3: auth errors must surface, not be masked as rate-limit
                except anthropic.RateLimitError as e2:
                    # Both models rate limited — log and surface clean error.
                    # WHY _parse_retry_after: same deduplication as primary block.
                    retry_after2 = _parse_retry_after(e2, default=60)
                    _agent_log.warning(
                        "rate_limit on fallback %s too — retry-after %ss", fallback_model, retry_after2
                    )
                except Exception:
                    pass
            rate_limited = True
            return None  # signal: "rate limited, no recovery"

    for _ in range(25):  # max 25 tool-use rounds
        response = await _create_with_recovery()
        if response is None:
            # A2: use the actual model variable, not a hardcoded model name.
            final_text = (
                f"Hit the Anthropic rate limit on this account — give it a "
                f"minute and try again. (Tried {model} then Haiku; both throttled.)"
            )
            break

        last_stop_reason = response.stop_reason or ""

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text
                    break
            # W4: warn when the model answered without calling any tool this
            # turn. On inferential live-state queries this is a compliance
            # failure — log the user query (truncated) so we can mine for
            # system-prompt failures later.
            if not tool_calls_this_turn:
                last_user_q = ""
                for m in reversed(all_messages):
                    if m.get("role") == "user":
                        c = m.get("content") or ""
                        last_user_q = c if isinstance(c, str) else str(c)
                        break
                _agent_log.warning(
                    "end_turn with NO tool calls — possible system-prompt compliance failure. "
                    "query=%r",
                    last_user_q[:200],
                )
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls_this_turn.append(block.name)
                    try:
                        # Tool dispatch is sync (subprocess/AppleScript) — run
                        # in a thread so we don't block the event loop here.
                        result = await asyncio.to_thread(dispatch, block.name, block.input)
                    except Exception as e:
                        result = {"error": str(e)}
                        last_tool_error = f"{block.name}: {e}"

                    if isinstance(result, dict) and result.get("error"):
                        last_tool_error = f"{block.name}: {result['error']}"

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

    # OS3: branch the fallback message by what actually went wrong instead
    # of the bare "please try again".
    if not final_text:
        if last_stop_reason == "max_tokens":
            final_text = (
                "My response got cut off mid-thought (max_tokens reached). "
                "Try asking for a shorter or more specific answer."
            )
        elif last_stop_reason == "pause_turn":
            final_text = (
                "I paused thinking partway through — please ask again with "
                "a bit more detail so I can resume."
            )
        elif last_tool_error:
            final_text = (
                f"I tried but a tool failed: {last_tool_error}. "
                f"Check the relevant app is open and try again."
            )
        else:
            final_text = (
                f"I couldn't complete that (stop_reason={last_stop_reason or 'unknown'}). "
                "Try rephrasing or asking for one piece at a time."
            )

    # OS4: if the requested model differed from the model that actually
    # produced this reply (and a real reply was produced — not the
    # rate-limit fallback string), footnote the user so they know we
    # answered with the cheaper backup.
    if (
        final_text
        and not rate_limited
        and actual_model
        and actual_model != model
    ):
        final_text = f"{final_text}\n\n_(Opus was rate-limited — answered with Haiku.)_"

    # Persist assistant reply.
    memory.append_message(conversation_id, "assistant", final_text)

    # OS5: persist a one-line breadcrumb of which tools we called this
    # turn. Dedupe consecutive identical names so chains like
    # outlook_search → outlook_search → outlook_read collapse to
    # "outlook_search, outlook_read". This row is filtered out of the
    # API replay history (see memory.get_recent_messages) but surfaces
    # in the next turn's system prompt so the model knows what it just
    # looked up — addresses the "open it" / "what about the next one"
    # case where the agent re-searches for state it already has.
    if tool_calls_this_turn:
        seen: list[str] = []
        for name in tool_calls_this_turn:
            if not seen or seen[-1] != name:
                seen.append(name)
        if seen:
            memory.append_tool_summary(conversation_id, "called: " + ", ".join(seen))

    # Refresh last_used_at on surfaced facts.
    memory.touch_facts([])  # no-op placeholder; facts are touched when created

    # Fire-and-forget fact extraction — runs in a thread so the sync
    # Anthropic call inside doesn't block the event loop. Wrapped in
    # asyncio.wait_for(timeout=30s) so a flaky network or stuck SDK call
    # doesn't pile up dangling tasks on the event loop indefinitely.
    try:
        last_user = ""
        # Walk all_messages (DB-sourced) in reverse to find the last user
        # turn — short frontend reconnect payloads (messages) only contain
        # the latest exchange and give Haiku wrong context for fact extraction.
        for lu in reversed(all_messages):
            if lu.get("role") == "user":
                c = lu.get("content") or ""
                last_user = c if isinstance(c, str) else str(c)
                break
        if last_user:
            async def _timed_extract():
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(memory.extract_facts_async, last_user, final_text),
                        timeout=30.0,
                    )
                except (asyncio.TimeoutError, Exception):
                    # Best-effort; never break the chat reply over fact extraction.
                    pass
            # Hold a strong ref so the loop doesn't GC the task mid-flight.
            _t = asyncio.create_task(_timed_extract())
            _BG_TASKS.add(_t)
            _t.add_done_callback(_BG_TASKS.discard)
    except Exception:
        pass

    return final_text, conversation_id


# Sync chat() wrapper removed — it called asyncio.run() which raises
# RuntimeError when invoked from a context with a running event loop.
# No callers exist; all call sites use chat_async directly.
