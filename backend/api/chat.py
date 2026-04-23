"""
Chat API — persistent conversations + facts memory.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from agent.jarvis import chat_async
from agent import memory

# Initialize DB on import.
memory.init_db()

router = APIRouter()

MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
}


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
    model: Optional[str] = Query(None, description="Override model: 'haiku' or 'sonnet'"),
):
    try:
        model_override = MODEL_MAP.get(model) if model else None
        reply, cid = await chat_async(
            req.messages,
            conversation_id=req.conversation_id,
            model_override=model_override,
        )
        return ChatResponse(reply=reply, conversation_id=cid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/conversations")
def list_conversations_endpoint():
    return {"conversations": memory.list_conversations()}


@router.post("/chat/conversations")
def create_conversation_endpoint(req: CreateConvRequest):
    conv = memory.create_conversation(title=req.title)
    return conv


@router.get("/chat/conversations/{cid}")
def get_conversation_endpoint(cid: str):
    conv = memory.get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/chat/conversations/{cid}")
def delete_conversation_endpoint(cid: str):
    ok = memory.delete_conversation(cid)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": cid}


@router.get("/chat/facts")
def list_facts_endpoint(limit: int = 50):
    return {"facts": memory.get_top_facts(limit=limit)}
