"""
Test suite for open-app endpoint.
Mocks subprocess and osascript to verify command construction without launching real apps.

Run with: cd backend && source .venv/bin/activate && python test_open_app.py
"""

import subprocess
import sys
from unittest.mock import patch, MagicMock, call
from tools.desktop_apps import (
    open_outlook_email,
    open_messages_chat,
    open_outlook_calendar,
    open_uworld,
    open_anki,
    open_app,
    _ensure_outlook_running,
    OutlookNotRunningError,
    NewOutlookModeError,
)


def test_open_outlook_email_with_id():
    """Test opening Outlook email by ID."""
    with patch("tools.desktop_apps._osascript") as mock_osascript, \
         patch("tools.desktop_apps.subprocess.run"):
        mock_osascript.return_value = {"output": "opened_by_id"}
        result = open_outlook_email("email-123")
        assert result["ok"] is True
        print("✓ test_open_outlook_email_with_id")


def test_open_outlook_email_fallback():
    """Test fallback to opening Outlook inbox when ID not found."""
    with patch("tools.desktop_apps._osascript") as mock_osascript, \
         patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_osascript.return_value = {"output": "fallback_to_inbox"}
        mock_run.return_value = MagicMock()
        result = open_outlook_email("email-123")
        assert result["ok"] is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "open" in call_args
        assert "Microsoft Outlook" in call_args
        print("✓ test_open_outlook_email_fallback")


def test_open_outlook_email_empty_ref():
    """Test opening Outlook inbox when ref is empty."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock()
        result = open_outlook_email("")
        assert result["ok"] is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "open" in call_args
        assert "Microsoft Outlook" in call_args
        print("✓ test_open_outlook_email_empty_ref")


def test_open_outlook_email_timeout():
    """Test timeout handling."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)
        result = open_outlook_email("email-123")
        assert result["ok"] is False
        assert "Timeout" in result["error"]
        print("✓ test_open_outlook_email_timeout")


def test_open_messages_with_phone():
    """Test opening Messages with phone number."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock()
        result = open_messages_chat("+16185551234")
        assert result["ok"] is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "open" in call_args
        assert "imessage://+16185551234" in call_args
        print("✓ test_open_messages_with_phone")


def test_open_messages_empty_phone():
    """Test Case 3: open Messages app when phone is empty and no context."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        result = open_messages_chat("")
        assert result["ok"] is True
        assert result["type"] == "app only"
        mock_run.assert_called_once()
        print("✓ test_open_messages_empty_phone")


def test_open_messages_timeout():
    """Test timeout handling."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)
        result = open_messages_chat("+16185551234")
        assert result["ok"] is False
        assert "Timeout" in result["error"]
        print("✓ test_open_messages_timeout")


def test_open_outlook_calendar():
    """Test opening Outlook calendar."""
    with patch("tools.desktop_apps._osascript") as mock_osascript, \
         patch("tools.desktop_apps.subprocess.run"):
        mock_osascript.return_value = {"output": "opened_calendar"}
        result = open_outlook_calendar()
        assert result["ok"] is True
        mock_osascript.assert_called_once()
        print("✓ test_open_outlook_calendar")


def test_open_outlook_calendar_fallback():
    """Test fallback to opening Outlook when calendar view fails."""
    with patch("tools.desktop_apps._osascript") as mock_osascript, \
         patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_osascript.return_value = {"output": "error_opening_calendar"}
        mock_run.return_value = MagicMock()
        result = open_outlook_calendar()
        assert result["ok"] is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "open" in call_args
        assert "Microsoft Outlook" in call_args
        print("✓ test_open_outlook_calendar_fallback")


def test_open_uworld():
    """Test opening UWorld login page."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock()
        result = open_uworld()
        assert result["ok"] is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "open" in call_args
        assert "https://www.uworld.com/login" in call_args
        print("✓ test_open_uworld")


def test_open_uworld_timeout():
    """Test timeout handling."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 10)
        result = open_uworld()
        assert result["ok"] is False
        assert "Timeout" in result["error"]
        print("✓ test_open_uworld_timeout")


def test_open_anki_url_scheme():
    """Test opening Anki via URL scheme."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock()
        result = open_anki()
        assert result["ok"] is True
        # Should try anki:// first
        call_args = mock_run.call_args[0][0]
        assert "open" in call_args
        assert "anki://" in call_args
        print("✓ test_open_anki_url_scheme")


def test_open_anki_app_fallback():
    """Test fallback to app launch when URL scheme fails."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        # First call (URL scheme) raises timeout, second call (app launch) succeeds
        mock_run.side_effect = [
            subprocess.TimeoutExpired("cmd", 10),
            MagicMock(),
        ]
        result = open_anki()
        assert result["ok"] is True
        # Should have called twice (URL scheme then app launch)
        assert mock_run.call_count == 2
        print("✓ test_open_anki_app_fallback")


def test_open_app_outlook_email():
    """Test routing to outlook-email handler."""
    with patch("tools.desktop_apps.open_outlook_email") as mock_fn:
        mock_fn.return_value = {"ok": True}
        result = open_app("outlook-email", "email-123")
        assert result["ok"] is True
        mock_fn.assert_called_once_with("email-123")
        print("✓ test_open_app_outlook_email")


def test_open_app_messages_with_context():
    """Test routing to messages with context."""
    with patch("tools.desktop_apps.open_messages_chat") as mock_fn:
        mock_fn.return_value = {"ok": True}
        result = open_app("messages", "", {"phone": "+16185551234"})
        assert result["ok"] is True
        mock_fn.assert_called_once_with("", {"phone": "+16185551234"})
        print("✓ test_open_app_messages_with_context")


def test_open_app_messages_with_ref():
    """Test routing to messages with ref as fallback."""
    with patch("tools.desktop_apps.open_messages_chat") as mock_fn:
        mock_fn.return_value = {"ok": True}
        result = open_app("messages", "+16185551234")
        assert result["ok"] is True
        mock_fn.assert_called_once_with("+16185551234", {})
        print("✓ test_open_app_messages_with_ref")


def test_open_app_outlook_calendar():
    """Test routing to outlook-calendar handler."""
    with patch("tools.desktop_apps.open_outlook_calendar") as mock_fn:
        mock_fn.return_value = {"ok": True}
        result = open_app("outlook-calendar", "event-456")
        assert result["ok"] is True
        mock_fn.assert_called_once_with("event-456")
        print("✓ test_open_app_outlook_calendar")


def test_open_app_uworld():
    """Test routing to uworld handler."""
    with patch("tools.desktop_apps.open_uworld") as mock_fn:
        mock_fn.return_value = {"ok": True}
        result = open_app("uworld")
        assert result["ok"] is True
        mock_fn.assert_called_once()
        print("✓ test_open_app_uworld")


def test_open_app_anki():
    """Test routing to anki handler."""
    with patch("tools.desktop_apps.open_anki") as mock_fn:
        mock_fn.return_value = {"ok": True}
        result = open_app("anki")
        assert result["ok"] is True
        mock_fn.assert_called_once()
        print("✓ test_open_app_anki")


def test_open_app_invalid_app():
    """Test error handling for invalid app name."""
    result = open_app("invalid-app")
    assert result["ok"] is False
    assert "Unknown app" in result["error"]
    print("✓ test_open_app_invalid_app")


# ── W2: _ensure_outlook_running tests ─────────────────────────────────────────

def _make_run_result(stdout="", stderr="", returncode=0):
    """Build a minimal subprocess.CompletedProcess-like mock."""
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def test_ensure_outlook_running_already_up():
    """If Outlook is already running, no launch command is issued."""
    # First call → System Events check returns "true" (already running).
    # Second call → New Outlook probe returns a plain integer (Classic mode).
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.side_effect = [
            _make_run_result(stdout="true"),   # _is_running() check
            _make_run_result(stdout="1"),       # New Outlook probe — integer means Classic
        ]
        _ensure_outlook_running()  # should not raise
        # open -a should NOT have been called (only the two probes ran)
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert not any("open" in (c if isinstance(c, list) else []) for c in calls if isinstance(c, list))
    print("✓ test_ensure_outlook_running_already_up")


def test_ensure_outlook_running_not_running_then_launches():
    """When Outlook is not running, open -a is called and polling succeeds."""
    call_counter = {"n": 0}

    def side_effect(cmd, **kwargs):
        call_counter["n"] += 1
        n = call_counter["n"]
        if n == 1:
            # First System Events check — not running yet
            return _make_run_result(stdout="false")
        if n == 2:
            # open -a "Microsoft Outlook" launch
            return _make_run_result(stdout="")
        if n == 3:
            # First poll — still not up
            return _make_run_result(stdout="false")
        if n == 4:
            # Second poll — now up
            return _make_run_result(stdout="true")
        # New Outlook probe — returns integer (Classic mode)
        return _make_run_result(stdout="1")

    with patch("tools.desktop_apps.subprocess.run", side_effect=side_effect), \
         patch("tools.desktop_apps.time.sleep"):  # skip real sleep in tests
        _ensure_outlook_running()  # should not raise

    assert call_counter["n"] >= 4, "Expected at least 4 subprocess calls"
    print("✓ test_ensure_outlook_running_not_running_then_launches")


def test_ensure_outlook_running_launch_timeout():
    """If Outlook never appears after launch, OutlookNotRunningError is raised."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run, \
         patch("tools.desktop_apps.time.sleep"), \
         patch("tools.desktop_apps.time.time") as mock_time:
        # Simulate _is_running returning false every time and time expiring quickly.
        mock_run.return_value = _make_run_result(stdout="false")
        # time.time() returns 0, then 0 (launch), then 100 (well past the 15s deadline)
        mock_time.side_effect = [0, 0, 100, 100]
        try:
            _ensure_outlook_running()
            assert False, "Should have raised OutlookNotRunningError"
        except OutlookNotRunningError as e:
            assert "15 seconds" in str(e)
    print("✓ test_ensure_outlook_running_launch_timeout")


def test_ensure_outlook_new_outlook_detected():
    """If New Outlook probe returns 'can't get exchange accounts', NewOutlookModeError is raised."""
    with patch("tools.desktop_apps.subprocess.run") as mock_run:
        mock_run.side_effect = [
            _make_run_result(stdout="true"),  # _is_running — Outlook up
            _make_run_result(               # New Outlook probe — Classic API broken
                stdout="",
                stderr="Microsoft Outlook got an error: Can't get exchange accounts.",
                returncode=1,
            ),
        ]
        try:
            _ensure_outlook_running()
            assert False, "Should have raised NewOutlookModeError"
        except NewOutlookModeError as e:
            assert "New Outlook" in str(e)
            assert "Help menu" in str(e)
    print("✓ test_ensure_outlook_new_outlook_detected")


if __name__ == "__main__":
    # Run all tests
    test_functions = [
        test_open_outlook_email_with_id,
        test_open_outlook_email_fallback,
        test_open_outlook_email_empty_ref,
        test_open_outlook_email_timeout,
        test_open_messages_with_phone,
        test_open_messages_empty_phone,
        test_open_messages_timeout,
        test_open_outlook_calendar,
        test_open_outlook_calendar_fallback,
        test_open_uworld,
        test_open_uworld_timeout,
        test_open_anki_url_scheme,
        test_open_anki_app_fallback,
        test_open_app_outlook_email,
        test_open_app_messages_with_context,
        test_open_app_messages_with_ref,
        test_open_app_outlook_calendar,
        test_open_app_uworld,
        test_open_app_anki,
        test_open_app_invalid_app,
        # W2 new tests
        test_ensure_outlook_running_already_up,
        test_ensure_outlook_running_not_running_then_launches,
        test_ensure_outlook_running_launch_timeout,
        test_ensure_outlook_new_outlook_detected,
    ]

    failed = 0
    for test_fn in test_functions:
        try:
            test_fn()
        except AssertionError as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test_fn.__name__}: {type(e).__name__}: {e}")
            failed += 1

    if failed == 0:
        print(f"\n✓ All {len(test_functions)} tests passed!")
        sys.exit(0)
    else:
        print(f"\n✗ {failed}/{len(test_functions)} tests failed")
        sys.exit(1)
