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
        "description": "Get today's Anki review stats: due count, reviewed, new cards introduced.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "anki_find_cards",
        "description": "Search Anki cards by query (same syntax as Anki browser). Returns card IDs.",
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
