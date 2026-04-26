"""HIPAA boundary regression tests for calendar redaction.

Covers:
1. The shared hipaa.redact_events_in_place helper.
2. The widgets._compute_calendar Graph API fallback path — titles for events
   on hidden calendars must be replaced with "(hidden)" and locations cleared
   before reaching the frontend, just like the desktop path.
3. The agent.memory.dashboard_snapshot_async LLM-context filter — Outlook-
   tagged events must NOT surface as the "Next event" line, regardless of
   whether the desktop or Graph API path produced them.

Run with: cd backend && source .venv/bin/activate && python test_hipaa_redaction.py
"""

import asyncio
import sys
from unittest.mock import patch, MagicMock


def test_redact_helper_basic():
    from hipaa import redact_events_in_place, HIDDEN_CALENDARS
    events = [
        {"title": "Patient Smith — H&P", "calendar": "Rotation", "location": "Room 4B"},
        {"title": "1:1 with advisor", "calendar": "Personal", "location": "Cafe"},
        {"title": "On-call", "calendar": "Work", "location": "Hospital"},
    ]
    redact_events_in_place(events)
    assert events[0]["title"] == "(hidden)"
    assert events[0]["location"] == ""
    assert events[1]["title"] == "1:1 with advisor"
    assert events[1]["location"] == "Cafe"
    assert events[2]["title"] == "(hidden)"
    assert "Outlook" in HIDDEN_CALENDARS, "Outlook must be redacted by default per user HIPAA boundary"
    print("✓ test_redact_helper_basic")


def test_redact_helper_handles_missing_calendar_field():
    from hipaa import redact_events_in_place
    events = [{"title": "Untagged event", "location": "TBD"}]
    redact_events_in_place(events)
    assert events[0]["title"] == "Untagged event", "events without a calendar field should not be touched"
    print("✓ test_redact_helper_handles_missing_calendar_field")


def test_is_hidden_helper():
    from hipaa import is_hidden, HIDDEN_CALENDARS
    assert is_hidden("Rotation")
    assert is_hidden(" Work ")  # whitespace tolerated
    assert is_hidden("Outlook")
    assert not is_hidden("Personal")
    assert not is_hidden(None)
    assert not is_hidden("")
    # Verify the legacy hidden-set members are all still redacted.
    for name in ("Rotation", "Subscribed Calendar", "Work"):
        assert name in HIDDEN_CALENDARS
    print("✓ test_is_hidden_helper")


def test_compute_calendar_graph_api_path_redacts():
    """Desktop sources return nothing → Graph API fallback fires → titles must be redacted."""
    sys.modules.pop("backend.api.widgets", None)
    from api import widgets

    fake_graph_payload = {
        "events": [
            # Tagged "Outlook" by the patched outlook tool — must be redacted.
            {"title": "Patient Doe — discharge planning", "calendar": "Outlook",
             "start": "Mon Apr 27 9:00:00 AM", "end": "10:00", "location": "Ward 7"},
            # Even if a non-hidden tag slipped through, leave it alone.
            {"title": "Standup", "calendar": "Personal",
             "start": "Mon Apr 27 11:00:00 AM", "end": "11:15", "location": "Zoom"},
        ]
    }

    with patch.object(widgets, "_outlook_calendar", return_value={"events": []}), \
         patch.object(widgets, "_calendar_events", return_value={"events": []}), \
         patch("tools.outlook.is_authenticated", return_value=True), \
         patch("tools.outlook.run_outlook_tool", return_value=fake_graph_payload):
        result = widgets._compute_calendar()

    assert result is not None, "graph_api fallback should have produced a payload"
    assert result["source"] == "graph_api"
    titles = [e["title"] for e in result["events"]]
    locations = [e["location"] for e in result["events"]]
    assert "(hidden)" in titles, f"rotation/Outlook event was not redacted: {titles}"
    assert "Patient Doe — discharge planning" not in titles, "PHI title leaked through Graph API path"
    # Hidden event must also have its location cleared.
    hidden_idx = titles.index("(hidden)")
    assert locations[hidden_idx] == ""
    # Non-hidden event preserved.
    assert "Standup" in titles
    print("✓ test_compute_calendar_graph_api_path_redacts")


def test_compute_calendar_desktop_path_redacts_outlook_events():
    """Desktop _outlook_calendar tags every event 'Outlook'. Those must now be redacted too."""
    from api import widgets
    desktop_outlook = {"events": [
        {"title": "Patient Roe — follow-up", "calendar": "Outlook",
         "start": "Tue 2pm", "end": "3pm", "location": "Suite 2"},
    ]}
    apple_calendar = {"events": [
        {"title": "Lunch with mom", "calendar": "Personal",
         "start": "Tue 12pm", "end": "1pm", "location": "Home"},
    ]}
    with patch.object(widgets, "_outlook_calendar", return_value=desktop_outlook), \
         patch.object(widgets, "_calendar_events", return_value=apple_calendar):
        result = widgets._compute_calendar()
    assert result["source"] == "desktop"
    titles = [e["title"] for e in result["events"]]
    assert "(hidden)" in titles, "Outlook desktop event must be redacted"
    assert "Patient Roe — follow-up" not in titles
    assert "Lunch with mom" in titles
    print("✓ test_compute_calendar_desktop_path_redacts_outlook_events")


def test_dashboard_snapshot_skips_outlook_events_in_llm_context():
    """The LLM snapshot must NOT pick an Outlook-tagged event as 'Next event'."""
    from agent import memory

    async def fake_fetch_one(client, path):
        if path == "/widgets/calendar":
            # Simulate the case where the desktop path is dead and the Graph
            # API fallback returned an unredacted "Outlook" event (e.g. an
            # older cache from before this fix). Even so, memory.py must skip
            # it instead of feeding the title to the LLM.
            return {"events": [
                {"title": "Patient Acuna — chart review", "calendar": "Outlook",
                 "start": "Mon Apr 27 8:00 AM"},
                {"title": "Coffee with Dr. Lee", "calendar": "Personal",
                 "start": "Mon Apr 27 10:00 AM"},
            ]}
        return {}

    with patch.object(memory, "_fetch_one", side_effect=fake_fetch_one):
        snapshot = asyncio.run(memory.dashboard_snapshot_async())

    assert "Patient Acuna" not in snapshot, f"PHI leaked into LLM snapshot:\n{snapshot}"
    assert "chart review" not in snapshot
    assert "Coffee with Dr. Lee" in snapshot, f"non-redacted event should surface:\n{snapshot}"
    print("✓ test_dashboard_snapshot_skips_outlook_events_in_llm_context")


def test_dashboard_snapshot_no_non_redacted_events():
    """If every event is from a hidden calendar, the snapshot reports the absence — never a redacted title."""
    from agent import memory

    async def fake_fetch_one(client, path):
        if path == "/widgets/calendar":
            return {"events": [
                {"title": "Patient X", "calendar": "Rotation", "start": "9am"},
                {"title": "Patient Y", "calendar": "Outlook", "start": "10am"},
            ]}
        return {}

    with patch.object(memory, "_fetch_one", side_effect=fake_fetch_one):
        snapshot = asyncio.run(memory.dashboard_snapshot_async())

    assert "Patient" not in snapshot, f"PHI leaked:\n{snapshot}"
    assert "(hidden)" not in snapshot, f"redaction sentinel must not be sent to the LLM:\n{snapshot}"
    print("✓ test_dashboard_snapshot_no_non_redacted_events")


if __name__ == "__main__":
    test_redact_helper_basic()
    test_redact_helper_handles_missing_calendar_field()
    test_is_hidden_helper()
    test_compute_calendar_graph_api_path_redacts()
    test_compute_calendar_desktop_path_redacts_outlook_events()
    test_dashboard_snapshot_skips_outlook_events_in_llm_context()
    test_dashboard_snapshot_no_non_redacted_events()
    print("\nAll HIPAA redaction tests passed.")
