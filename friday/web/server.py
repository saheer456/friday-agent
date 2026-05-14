"""
FRIDAY web server — FastAPI + SSE streaming chat (same brain as CLI).
Run from repo root: python -m uvicorn web.server:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import brain


def _voice_stack_info() -> dict:
    return {
        "stt_model": os.getenv("FRIDAY_WHISPER_MODEL", "small"),
        "stt_device": os.getenv("FRIDAY_WHISPER_DEVICE", "cpu"),
        "stt_compute": os.getenv("FRIDAY_WHISPER_COMPUTE", "int8"),
        "tts_backend": os.getenv("FRIDAY_TTS_BACKEND", "auto"),
        "tts_voice": os.getenv("FRIDAY_VOICE", "af_heart"),
        "vad_mode": os.getenv("FRIDAY_VAD_MODE", "2"),
    }


def _llm_stack_info() -> dict:
    url, _key, model, provider = brain._chat_stream_config()
    return {
        "llm_provider": provider,
        "llm_model": model,
        "llm_url_host": url.split("/")[2] if "://" in url else url,
    }


def _readiness_info() -> dict:
    """Live readiness flags — used by the frontend status badges."""
    from backend import memory as _mem
    return {
        "memory_ready": _mem._memory_ready.is_set(),
        "tts_ready": _tts_ready,
        "stt_ready": _stt_ready,
    }


def _ui_info() -> dict:
    version = (os.getenv("FRIDAY_UI_VERSION") or "v2.0 Sentinel").strip()
    if not version:
        version = "v2.0 Sentinel"
    return {"version": version}


app = FastAPI(title="FRIDAY Web", version="1.0")

STATIC_DIR = ROOT / "web" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Readiness flags (set during warmup, read by /api/system) ──────────────────
_tts_ready = False
_stt_ready = True   # STT is Whisper — loaded on demand; mark ready by default

# ── Startup warmup — block until slow models are ready ────────────────────────
@app.on_event("startup")
async def _warmup():
    import asyncio, threading

    # ── Memory: BLOCKING await — server won't accept requests until the
    # HuggingFace embedding model + ChromaDB are fully loaded.
    # This is the simplest and most reliable fix for the second-message crash:
    # there is no race condition if the model is already ready before msg 1.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_load_memory)

    # ── TTS: fire-and-forget — not required before first chat
    threading.Thread(target=_load_tts, daemon=True, name="warmup-tts").start()
    asyncio.create_task(_ping_edge_tts())


def _do_load_memory():
    try:
        from backend.memory import warm_up
        warm_up()   # loads HF model + ChromaDB, sets _memory_ready event
    except Exception as e:
        print(f"[FRIDAY] Memory warmup skipped: {e}")


def _load_tts():
    global _tts_ready
    try:
        from backend.tts import _get_kokoro
        _get_kokoro()
        _tts_ready = True
        print("[FRIDAY] ✓ Kokoro TTS warmed up")
    except Exception:
        pass


async def _ping_edge_tts():
    global _tts_ready
    try:
        from backend.tts import synthesize
        await synthesize("Hi")
        _tts_ready = True
        print("[FRIDAY] ✓ Edge-TTS warmed up")
    except Exception:
        pass


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=16_000)
    voice_mode: bool = False


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "friday-web"}


@app.get("/api/system")
async def system_info():
    """Voice stack + LLM routing (HUD)."""
    return {
        "ui": _ui_info(),
        "voice": _voice_stack_info(),
        "llm": _llm_stack_info(),
        "readiness": _readiness_info(),
        "history_turns": len(brain.conversation_history),
    }


@app.post("/api/chat/stream")
async def chat_stream(body: ChatBody):
    """SSE: phase + token + error events, then `[DONE]`."""

    async def event_gen():
        try:
            async for ev in brain.iter_chat_sse_events(body.message.strip(), voice_mode=body.voice_mode):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            err = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {err}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/clear")
async def clear_history():
    brain.conversation_history.clear()
    return {"ok": True}


class TTSBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4_000)


@app.post("/api/tts")
async def tts_endpoint(body: TTSBody):
    """Synthesize text → audio via the backend TTS pipeline (edge-tts / Kokoro).
    Returns MP3 or WAV bytes for the browser to play natively.
    """
    from fastapi.responses import Response as RawResponse
    from backend.tts import synthesize, clean_for_speech

    cleaned = clean_for_speech(body.text.strip())
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty text after cleaning")
    try:
        audio, suffix, _ = await synthesize(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS error: {e}") from e
    if not audio:
        raise HTTPException(status_code=500, detail="TTS returned no audio")
    media_type = "audio/mpeg" if suffix == ".mp3" else "audio/wav"
    return RawResponse(content=audio, media_type=media_type)


@app.post("/api/speak")
async def speak_endpoint(body: TTSBody):
    """Convert Markdown → natural spoken prose via LLM, then synthesize.
    Uses llama-3.1-8b-instant (fast, cheap) to rewrite the text naturally
    before passing to TTS. Far better quality than regex-based cleaning.
    """
    from fastapi.responses import Response as RawResponse
    from backend.tts import synthesize, clean_for_speech
    import httpx, os

    raw = body.text.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty text")

    # Step 1: convert Markdown → spoken prose via a fast LLM call
    spoken = raw  # fallback if LLM fails
    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if api_key and "your_" not in api_key.lower():
        prompt = (
            "Convert the following text into natural spoken English, as if you are speaking it aloud. "
            "Rules: remove ALL markdown (no **, no ##, no -, no backticks, no numbered lists). "
            "Convert bullet lists into flowing prose sentences. "
            "Convert numbered steps into 'First... Then... Finally...' style. "
            "Keep the same meaning and information. Be concise. "
            "Output ONLY the spoken version, nothing else.\n\n"
            f"Text to convert:\n{raw}"
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "llama-3.1-8b-instant",   # fastest Groq model
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 400,
                        "temperature": 0.2,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                spoken = r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            spoken = clean_for_speech(raw)   # regex fallback

    # Step 2: synthesize
    spoken = clean_for_speech(spoken)   # final safety pass
    if not spoken:
        raise HTTPException(status_code=400, detail="Empty after cleaning")
    try:
        audio, suffix, _ = await synthesize(spoken)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS error: {e}") from e
    if not audio:
        raise HTTPException(status_code=500, detail="No audio returned")
    media_type = "audio/mpeg" if suffix == ".mp3" else "audio/wav"
    return RawResponse(content=audio, media_type=media_type)



@app.post("/api/chat")
async def chat_once(body: ChatBody):
    """Non-streaming fallback (full reply as JSON)."""
    parts: list[str] = []
    try:
        async for chunk in brain.stream_response(body.message.strip(), voice_mode=body.voice_mode):
            parts.append(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"reply": "".join(parts)}
