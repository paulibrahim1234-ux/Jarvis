"""
Tool registry — Claude tool definitions + dispatch.
"""

from tools.anki import ANKI_TOOLS, run_anki_tool
from tools.outlook import run_outlook_tool
from tools.spotify import run_spotify_tool
from tools.computer import COMPUTER_TOOLS, run_computer_tool
from tools.browser import BROWSER_TOOLS, run_browser_tool
from tools.desktop_apps import DESKTOP_TOOLS, run_desktop_tool

# Desktop tools replace the API-based outlook/spotify tools for Claude.
# (The API versions are still called directly by widgets.py as fallbacks.)
TOOLS = [
    *ANKI_TOOLS,
    *DESKTOP_TOOLS,
    *COMPUTER_TOOLS,
    *BROWSER_TOOLS,
]

_COMPUTER_NAMES = {t["name"] for t in COMPUTER_TOOLS}
_BROWSER_NAMES = {t["name"] for t in BROWSER_TOOLS}
_DESKTOP_NAMES = {t["name"] for t in DESKTOP_TOOLS}


def dispatch(tool_name: str, tool_input: dict):
    if tool_name.startswith("anki_"):
        return run_anki_tool(tool_name, tool_input)
    if tool_name in _DESKTOP_NAMES:
        return run_desktop_tool(tool_name, tool_input)
    if tool_name in _COMPUTER_NAMES:
        return run_computer_tool(tool_name, tool_input)
    if tool_name in _BROWSER_NAMES:
        return run_browser_tool(tool_name, tool_input)
    raise ValueError(f"Unknown tool: {tool_name}")
