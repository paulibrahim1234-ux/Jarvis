"""
Triage agent — chief-of-staff style 4-tier classification of unread email + iMessage.

WHY a separate module: the system prompt is large (1.5K tokens) and benefits from
prompt caching when called repeatedly. Keeping it isolated also lets us evolve the
classifier independently of the main jarvis.py loop.
"""

import json
import os
import anthropic
from datetime import datetime

# We import the sync client from jarvis instead of building a duplicate so
# that credential changes (via /setup) propagate to both code paths at once.
# The triage call is sync so we never need the async variant here.
from agent import jarvis as _jarvis

# 4-tier classification prompt written for Paul's MS3/surgery context.
# Kept as a module-level constant so Python's module cache holds it in memory —
# no disk read overhead on repeated calls — and the Anthropic prompt-caching
# header can reuse the exact same bytes across requests.
TRIAGE_SYSTEM = '''<role>
You are a personal chief of staff for a busy medical student (MS3, surgery rotation).
Triage incoming email + iMessage into 4 tiers and produce DRAFT replies for action_required items.
</role>

<tiers>
1. skip — noreply, automated alerts, marketing, promo (Grubhub/DoorDash/etc)
2. info_only — CC\'d, FYI, receipts, group chatter without direct ask
3. meeting_info — has Zoom/Teams/Meet URL or date+meeting context
4. action_required — direct asks awaiting your reply
</tiers>

<persona>
User: Paul Ibrahim, MS3.
Tone: concise, contractions, no purple prose, no signoff.
For scheduling: propose 2 specific times, stop.
</persona>

<output_schema>
Return STRICT JSON matching:
{
  "skip_count": int,
  "skip_senders": [str],
  "info_only": [{"sender": str, "subject": str, "summary": str}],
  "meeting_info": [{"sender": str, "subject": str, "datetime_hint": str, "needs_calendar_check": bool}],
  "action_required": [{"sender": str, "subject_or_thread": str, "excerpt": str, "draft_reply": str, "channel": "email"|"imessage"}],
  "stale": [{"sender": str, "subject_or_thread": str, "days_stale": int, "channel": "email"|"imessage"}]
}
Output ONLY the JSON object — no markdown fences, no explanation.
</output_schema>
'''

# Empty-result shape returned when there is nothing to triage or on hard failures.
# Having a single canonical empty is safer than constructing ad-hoc dicts in
# multiple catch branches — callers copy() it to prevent accidental shared mutation.
_EMPTY_RESULT: dict = {
    "skip_count": 0,
    "skip_senders": [],
    "info_only": [],
    "meeting_info": [],
    "action_required": [],
    "stale": [],
}


def _build_user_message(email_payload: dict, imessage_payload: dict) -> str:
    """Serialize the two data payloads into the user-turn content string.

    WHY stringify rather than pass JSON dicts: Anthropic messages expect
    a text string in the user content block. Compact JSON keeps token
    count low; the model is instructed to return strict JSON so we can
    json.loads() the reply without post-processing.
    """
    today = datetime.now().strftime("%Y-%m-%d %A")
    return json.dumps({
        "today": today,
        "email": email_payload,
        "imessage": imessage_payload,
    }, default=str)


def compute_triage(email_payload: dict, imessage_payload: dict) -> dict:
    """Classify email + iMessage via the Anthropic API and return structured triage data.

    Uses prompt caching on the large TRIAGE_SYSTEM block (1h TTL) so repeated
    5-minute cache misses from the widget endpoint hit Anthropic's cache instead
    of burning full input tokens every time.

    Returns the canonical _EMPTY_RESULT shape on JSON parse failure so the
    frontend always receives a well-typed object and never has to guard against
    missing keys.
    """
    # Reuse the module-level sync client from jarvis so credential updates
    # via /setup are reflected here without a backend restart.
    client = _jarvis.client

    user_content = _build_user_message(email_payload, imessage_payload)

    # WHY cache_control on the system block: TRIAGE_SYSTEM is ~600 tokens and
    # identical across every call. With ephemeral caching at a 1h TTL
    # (requires the extended-cache-ttl beta header below) Anthropic stores the
    # KV once per hour and charges ~10% of input cost on cache hits.
    # The user content block changes every call so it must NOT carry cache_control.
    response = client.messages.create(
        model="claude-opus-4-5-20251101",
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": TRIAGE_SYSTEM,
                # WHY ephemeral + extended-cache-ttl: the widget refreshes every
                # 5 min (300s TTL in _cached). Without the 1h extended TTL the
                # default 5-min Anthropic cache would expire between widget polls
                # and we'd pay full prompt cost every refresh cycle.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": user_content}
        ],
        # WHY extra_headers: the 1h extended cache TTL is behind an Anthropic
        # beta as of 2025-04. Without it cache lifetime is 5 min — fine but
        # slightly wasteful since our own _cached TTL is also 5 min.
        extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"},
    )

    raw_text = response.content[0].text.strip()

    # Strip optional markdown fences that some model versions emit despite the
    # instruction — ``` or ```json wrappers cause json.loads to fail.
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[-1]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        # Return a partial result with an error key rather than propagating.
        # The endpoint wraps this in its own try/except too, but belt-and-suspenders.
        result = dict(_EMPTY_RESULT)
        result["error"] = f"JSON parse failed: {str(exc)[:120]} | raw: {raw_text[:200]}"
        return result
