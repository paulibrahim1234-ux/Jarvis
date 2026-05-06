"""
AnkiConnect tool — reads stats, searches cards, unsuspends by tag.
Requires Anki running locally with AnkiConnect add-on.
"""

import os
import httpx

ANKICONNECT_URL = os.getenv("ANKICONNECT_URL", "http://localhost:8765")

ANKI_TOOLS = [
    {
        "name": "anki_get_stats",
        "description": (
            "Use this when the user asks 'how many Anki cards do I have due', 'what's my Anki "
            "progress today', 'did I do my reviews', or 'how am I doing on Anki'. "
            "Returns today's review stats: due count, cards reviewed, new cards introduced. "
            "Requires Anki open with the AnkiConnect add-on running."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "anki_find_cards",
        "description": (
            "Use this when the user asks 'find cards tagged [topic]', 'how many [subject] cards', "
            "'show me my UWorld cardiology cards', or needs to search the Anki deck by tag/field. "
            "Uses Anki browser query syntax (e.g. 'tag:UWorld::Cardiology', 'deck:Default is:due'). "
            "Returns card IDs and count. Use query to specify the Anki search expression."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query, e.g. 'tag:UWorld::Cardiology'"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "anki_unsuspend_cards",
        "description": "Unsuspend Anki cards by their IDs so they appear in future reviews.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_ids": {"type": "array", "items": {"type": "integer"}}
            },
            "required": ["card_ids"],
        },
    },
]


def _invoke(action: str, **params):
    payload = {"action": action, "version": 6, "params": params}
    r = httpx.post(ANKICONNECT_URL, json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"AnkiConnect error: {data['error']}")
    return data["result"]


def _invoke_multi(actions: list[dict]):
    """Send multiple AnkiConnect actions in a single HTTP request (action="multi").

    Each item in *actions* should be a dict with at least an "action" key
    and optionally a "params" key.  Returns the list of per-action results.
    """
    payload = {
        "action": "multi",
        "version": 6,
        "params": {"actions": actions},
    }
    r = httpx.post(ANKICONNECT_URL, json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"AnkiConnect multi error: {data['error']}")
    return data["result"]


def run_anki_tool(name: str, inp: dict):
    if name == "anki_get_stats":
        # Aggregate stats across all decks
        stats = _invoke("getCollectionStatsHTML", wholeCollection=True)
        return {"html_stats": stats}
    if name == "anki_find_cards":
        ids = _invoke("findCards", query=inp["query"])
        return {"card_ids": ids, "count": len(ids)}
    if name == "anki_unsuspend_cards":
        _invoke("unsuspend", cards=inp["card_ids"])
        return {"unsuspended": len(inp["card_ids"])}
    raise ValueError(f"Unknown anki tool: {name}")
