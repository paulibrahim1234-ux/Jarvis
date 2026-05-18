"""
Voice integration — STT via Groq Whisper Large v3 Turbo, TTS via Cartesia Sonic.

STT: https://api.groq.com/openai/v1/audio/transcriptions (model whisper-large-v3-turbo)
TTS: https://api.cartesia.ai/tts/bytes

Apple SFSpeechRecognizer is the on-device offline fallback but is handled
on the Swift client side, not here.

Env:
  GROQ_API_KEY            — Groq API key for STT
  CARTESIA_API_KEY        — Cartesia API key for TTS
  JARVIS_VOICE_DISABLED=1 — short-circuit both functions (kill switch)
"""

import logging
import os
import time

import httpx

_logger = logging.getLogger(__name__)

# Kill switch: read once at import. If the user wants to disable voice
# they restart the backend — same pattern as other JARVIS_* env flags.
VOICE_DISABLED = os.getenv("JARVIS_VOICE_DISABLED") == "1"

# Groq Whisper endpoint (OpenAI-compatible audio API).
_GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_GROQ_STT_MODEL = "whisper-large-v3-turbo"

# Cartesia Sonic TTS endpoint — returns raw audio bytes.
_CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
# Pin the API version we coded against — Cartesia bumps headers occasionally.
_CARTESIA_API_VERSION = "2024-06-10"
# Sonic English voice. Callers can override via `voice=` to swap voice IDs.
_CARTESIA_DEFAULT_MODEL = "sonic-english"


async def transcribe_audio(audio_bytes: bytes, language: str | None = "en") -> dict:
    """Transcribe audio bytes via Groq Whisper Large v3 Turbo.

    Returns {"text": str, "duration": float, "language": str} on success,
    or {"text": "", "error": str} on failure / disabled / missing key.
    """
    if VOICE_DISABLED:
        _logger.info("transcribe_audio: voice disabled via JARVIS_VOICE_DISABLED")
        return {"text": "", "error": "voice disabled"}

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        _logger.warning("transcribe_audio: GROQ_API_KEY missing")
        return {"text": "", "error": "GROQ_API_KEY not set"}

    audio_len = len(audio_bytes)
    _logger.info("transcribe_audio: %d bytes, lang=%s", audio_len, language)
    started = time.perf_counter()

    # Build multipart form. Groq accepts the OpenAI audio API shape.
    files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
    data: dict[str, str] = {"model": _GROQ_STT_MODEL}
    if language:
        data["language"] = language

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _GROQ_STT_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as e:
        _logger.warning(
            "transcribe_audio: HTTP %s from Groq: %s",
            e.response.status_code,
            e.response.text[:200],
        )
        return {"text": "", "error": f"Groq HTTP {e.response.status_code}"}
    except Exception as e:
        _logger.warning("transcribe_audio: %r", e)
        return {"text": "", "error": str(e)}

    latency_ms = (time.perf_counter() - started) * 1000.0
    text = body.get("text", "") or ""
    # Groq's verbose response carries `duration` and `language`; the default
    # response_format only returns `text`. Default to 0.0 / requested lang.
    duration = float(body.get("duration", 0.0) or 0.0)
    detected_lang = body.get("language") or (language or "")
    _logger.info(
        "transcribe_audio: %d bytes -> %d chars in %.0f ms",
        audio_len,
        len(text),
        latency_ms,
    )
    return {"text": text, "duration": duration, "language": detected_lang}


async def synthesize_speech(text: str, voice: str = "default") -> bytes:
    """Synthesize speech via Cartesia Sonic.

    Returns raw audio bytes on success, b"" on failure / disabled / missing key.
    Default Cartesia output is MP3 — callers should serve as audio/mpeg.
    """
    if VOICE_DISABLED:
        _logger.info("synthesize_speech: voice disabled via JARVIS_VOICE_DISABLED")
        return b""

    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        _logger.warning("synthesize_speech: CARTESIA_API_KEY missing")
        return b""

    text_len = len(text)
    _logger.info("synthesize_speech: %d chars, voice=%s", text_len, voice)
    started = time.perf_counter()

    # Cartesia /tts/bytes payload shape. voice="default" is a sentinel that
    # lets the API pick a stock voice; otherwise the caller passes a voice ID.
    payload: dict = {
        "model_id": _CARTESIA_DEFAULT_MODEL,
        "transcript": text,
        "output_format": {
            "container": "mp3",
            "encoding": "mp3",
            "sample_rate": 44100,
        },
    }
    if voice and voice != "default":
        payload["voice"] = {"mode": "id", "id": voice}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _CARTESIA_TTS_URL,
                headers={
                    "X-API-Key": api_key,
                    "Cartesia-Version": _CARTESIA_API_VERSION,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            audio = resp.content
    except httpx.HTTPStatusError as e:
        _logger.warning(
            "synthesize_speech: HTTP %s from Cartesia: %s",
            e.response.status_code,
            e.response.text[:200],
        )
        return b""
    except Exception as e:
        _logger.warning("synthesize_speech: %r", e)
        return b""

    latency_ms = (time.perf_counter() - started) * 1000.0
    _logger.info(
        "synthesize_speech: %d chars -> %d audio bytes in %.0f ms",
        text_len,
        len(audio),
        latency_ms,
    )
    return audio
