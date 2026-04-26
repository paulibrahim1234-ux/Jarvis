"""HIPAA boundary helpers for calendar event redaction.

Centralizes the calendar-name allowlist and the redact-in-place behavior so
the dashboard widget endpoint and the LLM dashboard-snapshot use one source
of truth. Calendar event titles can contain patient names; rotation/clinical
calendars must never reach the frontend or the LLM context unredacted.
"""
from __future__ import annotations

from typing import Iterable, MutableMapping

# Calendar names whose event titles/locations must be hidden from the frontend.
# These are the Apple Calendar names plus "Outlook" — Outlook events go through
# this set both because the desktop _outlook_calendar tags every event with
# "Outlook" and because Graph API events are tagged "Outlook" by tools/outlook.
HIDDEN_CALENDARS: frozenset[str] = frozenset(
    {"Rotation", "Subscribed Calendar", "Work", "Outlook"}
)

# Stricter set used for the LLM dashboard snapshot. Currently identical to
# HIDDEN_CALENDARS — kept as a separate name so the two boundaries can drift
# (e.g. add additional calendars only to the LLM context) without touching
# call sites.
LLM_HIDDEN_CALENDARS: frozenset[str] = HIDDEN_CALENDARS


def is_hidden(calendar_name: str | None, hidden: Iterable[str] = HIDDEN_CALENDARS) -> bool:
    """Return True if the given calendar name should be redacted."""
    if not calendar_name:
        return False
    return calendar_name.strip() in hidden


def redact_events_in_place(
    events: list[MutableMapping[str, object]],
    hidden: Iterable[str] = HIDDEN_CALENDARS,
) -> list[MutableMapping[str, object]]:
    """Mutate events whose `calendar` field is in `hidden`: title→"(hidden)", location→"".

    Returns the same list for convenience. Events without a `calendar` field are
    left alone — callers that consume an upstream source which doesn't tag events
    must add the tag before calling this.
    """
    hidden_set = frozenset(hidden)
    for e in events:
        if (e.get("calendar") or "").strip() in hidden_set:
            e["title"] = "(hidden)"
            e["location"] = ""
    return events
