"""
Voice API — STT + TTS endpoints backed by tools/voice.py.

POST /api/voice/transcribe  multipart audio -> {text, duration, language}
POST /api/voice/synthesize  {text, voice}   -> audio/mpeg bytes
GET  /api/voice/status      -> {enabled, stt_available, tts_available}
"""

import logging
import os
import traceback

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

from api._security import _require_local_origin
from tools.voice import VOICE_DISABLED, synthesize_speech, transcribe_audio

_voice_log = logging.getLogger("jarvis.voice")

router = APIRouter(prefix="/api/voice")


class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = None


@router.post("/transcribe")
async def transcribe_endpoint(request: Request, audio: UploadFile = File(...)):
    """Transcribe an uploaded audio file via Groq Whisper Large v3 Turbo."""
    # CSRF guard — same rationale as /chat: voice POSTs trigger paid API calls.
    _require_local_origin(request)
    try:
        audio_bytes = await audio.read()
        result = await transcribe_audio(audio_bytes)
        return result
    except Exception:
        # Match chat.py: log full traceback server-side, return generic 500
        # so the frontend's error path fires without leaking internals.
        _voice_log.error("transcribe_endpoint error: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/synthesize")
async def synthesize_endpoint(req: SynthesizeRequest, request: Request):
    """Synthesize speech via Cartesia Sonic — returns audio/mpeg bytes."""
    _require_local_origin(request)
    try:
        audio = await synthesize_speech(req.text, voice=req.voice or "default")
        if not audio:
            # Empty bytes means disabled, missing key, or upstream failure —
            # the underlying logger has already recorded the cause.
            raise HTTPException(status_code=503, detail="TTS unavailable")
        return Response(content=audio, media_type="audio/mpeg")
    except HTTPException:
        raise
    except Exception:
        _voice_log.error("synthesize_endpoint error: %s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/status")
def status_endpoint():
    """Capability probe — does the user have keys configured, is voice live?"""
    return {
        "enabled": not VOICE_DISABLED,
        "stt_available": bool(os.getenv("GROQ_API_KEY")),
        "tts_available": bool(os.getenv("CARTESIA_API_KEY")),
    }
