"""
Chat API — persistent conversations + facts memory.
"""

import logging
import traceback

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional

from agent.jarvis import chat_async
from agent import memory
from api._security import _require_local_origin

# Module-level logger — avoids importing logging inside the except block on
# every error path (ruff E401 antipattern). If the import itself failed during
# error handling it would mask the original exception entirely.
_chat_log = logging.getLogger("jarvis.chat")

# Initialize DB on import.
memory.init_db()

router = APIRouter()

MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
}

# Default to Haiku to conserve Opus quota. The frontend can request Opus
# explicitly via ?model=opus when complexity warrants. Haiku is fast enough
# for the tool-calling loop and leaves Opus budget for long-form reasoning.
_DEFAULT_MODEL = "haiku"


class ChatRequest(BaseModel):
    messages: list[dict]
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str


class CreateConvRequest(BaseModel):
    title: Optional[str] = None


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    request: Request,
    model: Optional[str] = Query(None, description="Override model: 'haiku' or 'sonnet'"),
):
    # CSRF guard: chat dispatches arbitrary tool calls (iMessage, calendar,
    # AppleScript). A drive-by POST from another tab must not be able to
    # trigger those — gate on Origin/Referer being localhost.
    _require_local_origin(request)
    try:
        # Fall back to _DEFAULT_MODEL (haiku) when no ?model= param is given.
        resolved = model if model else _DEFAULT_MODEL
        model_override = MODEL_MAP.get(resolved)
        reply, cid = await chat_async(
            req.messages,
            conversation_id=req.conversation_id,
            model_override=model_override,
        )
        return ChatResponse(reply=reply, conversation_id=cid)
    except Exception:
        # G3: raise HTTP 500 so the frontend's `if (!r.ok)` branch fires and
        # routes through the real error handler. A 200 with an apology string
        # looks like a normal reply and hides the error from the client.
        # Full traceback is logged server-side; nothing internal leaves the wire.
        # WHY no str(e) in detail: file paths, error topology, and partial token
        # values can leak via the detail field — the log line above captures all
        # of that for ops without exposing it to the client (Sec#5).
        _chat_log.error("chat_endpoint error: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/chat/conversations")
def list_conversations_endpoint():
    return {"conversations": memory.list_conversations()}


@router.post("/chat/conversations")
def create_conversation_endpoint(req: CreateConvRequest, request: Request):
    # CSRF guard: same rationale as POST /chat — block drive-by writes.
    _require_local_origin(request)
    conv = memory.create_conversation(title=req.title)
    return conv


@router.get("/chat/conversations/{cid}")
def get_conversation_endpoint(cid: str):
    conv = memory.get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/chat/conversations/{cid}")
def delete_conversation_endpoint(cid: str, request: Request):
    _require_local_origin(request)
    ok = memory.delete_conversation(cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": cid}


@router.get("/chat/facts")
def list_facts_endpoint(limit: int = 50):
    return {"facts": memory.get_top_facts(limit=limit)}
