"""
FRIDAY web server — FastAPI + SSE streaming chat (same brain as CLI).
Run from repo root: python -m uvicorn web.server:app --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import faulthandler
faulthandler.enable()

import traceback

print("[BOOT] server.py import started")

import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

from backend import brain

print("[BOOT] brain imported")


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
    return {
        "memory_ready": True,
        "tts_ready": _tts_ready.is_set(),
        "stt_ready": _stt_ready,
    }


# ── API Key authentication ─────────────────────────────────────────────────────
# If FRIDAY_API_KEY is set in env, all sensitive endpoints require
# the header:  X-API-Key: <value>
# If NOT set, all requests are allowed (local dev mode).
# ───────────────────────────────────────────────────────────────
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str | None = Security(_api_key_header)):
    required = os.getenv("FRIDAY_API_KEY", "").strip()
    if not required:
        return   # local dev — no key required
    if api_key != required:
        raise HTTPException(status_code=403, detail="Invalid or missing API key.")


def _ui_info() -> dict:
    version = (os.getenv("FRIDAY_UI_VERSION") or "v2.0 Sentinel").strip()
    if not version:
        version = "v2.0 Sentinel"
    return {"version": version}


app = FastAPI(title="FRIDAY Web", version="1.0")

print("[BOOT] FastAPI app created")

REACT_DIST_DIR = ROOT / "frontend" / "dist"

ASSETS_DIR = REACT_DIST_DIR / "assets"

# ───────────────────────────────────────────────────────────────
# Lifespan (replaces deprecated @app.on_event("startup"))
# ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown lifecycle handler."""
    import asyncio
    import threading as _threading

    print("[STARTUP] Startup sequence begin")

    # Environment validation
    try:
        print("[STARTUP] Validating environment...")
        from backend.validation import validate_environment
        validate_environment()
        print("[STARTUP] ✓ Environment valid")
    except Exception:
        print("[STARTUP] Environment validation failed")
        traceback.print_exc()

    # Memory system
    try:
        await initialize_memory()
    except Exception:
        print("[STARTUP] Memory init failed")
        traceback.print_exc()

    # TTS warmup (background — does not block server bind)
    try:
        _threading.Thread(target=_load_tts, daemon=True, name="warmup-tts").start()
        asyncio.create_task(_ping_edge_tts())
        print("[STARTUP] ✓ TTS warmup started")
    except Exception:
        print("[STARTUP] TTS warmup failed")
        traceback.print_exc()

    print("[STARTUP] Startup sequence complete")

    yield  # ← server is running

    # ─ Shutdown cleanup ─
    print("[SHUTDOWN] Closing HTTP client...")
    try:
        from backend.brain import _get_http_client
        await _get_http_client().aclose()
        print("[SHUTDOWN] ✓ HTTP client closed")
    except Exception:
        pass


app = FastAPI(title="FRIDAY Web", version="1.0", lifespan=lifespan)

print("[BOOT] FastAPI app created")

# CORS: explicit origins, not wildcard (wildcard + credentials is spec-forbidden)
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "FRIDAY_ALLOWED_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

REACT_DIST_DIR = ROOT / "frontend" / "dist"
ASSETS_DIR = REACT_DIST_DIR / "assets"

if REACT_DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


# ───────────────────────────────────────────────────────────────
# Runtime readiness flags
# ───────────────────────────────────────────────────────────────

# threading.Event is explicitly thread-safe (unlike a plain bool)
_tts_ready = threading.Event()
_stt_ready = True
_memory_ready = False

# ─────────────────────────────────────────────────────────────
# Safe memory initialization
# ─────────────────────────────────────────────────────────────

async def initialize_memory():
    global _memory_ready

    if _memory_ready:
        return

    try:
        print("[MEMORY] Importing MemoryManager...")

        from backend.memory import MemoryManager

        print("[MEMORY] Initializing memory...")

        await MemoryManager.initialize()

        _memory_ready = True

        print("[MEMORY] ✓ Memory initialized")

    except Exception:
        print("[MEMORY] FAILED")
        traceback.print_exc()




def _load_tts():
    try:
        print("[TTS] Loading Kokoro...")
        from backend.tts import _get_kokoro
        _get_kokoro()
        _tts_ready.set()  # thread-safe Event
        print("[TTS] ✓ Kokoro ready")
    except Exception:
        print("[TTS] Kokoro FAILED")
        traceback.print_exc()

async def _ping_edge_tts():
    try:
        print("[TTS] Pinging Edge-TTS...")
        from backend.tts import synthesize
        await synthesize("Hello")
        _tts_ready.set()  # thread-safe Event
        print("[TTS] ✓ Edge-TTS ready")
    except Exception:
        print("[TTS] Edge-TTS FAILED")
        traceback.print_exc()


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=16_000)
    voice_mode: bool = False


@app.get("/")
async def index():
    dist_index = ROOT / "frontend" / "dist" / "index.html"
    if not dist_index.exists():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            "<html><body style='background:#000;color:#0f0;font-family:monospace;padding:2rem'>"
            "<h2>FRIDAY API is running ✓</h2>"
            "<p>Frontend not built. If you see this on Render, check that the build step ran correctly.</p>"
            "<p><a href='/health' style='color:#0f0'>/health</a> &nbsp; "
            "<a href='/docs' style='color:#0f0'>/docs</a></p>"
            "</body></html>",
            status_code=200
        )
    return FileResponse(dist_index)



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
async def chat_stream(body: ChatBody, _auth: None = Depends(verify_api_key)):
    """SSE: phase + token + error events, then `[DONE]`."""

    def _friendly_error(raw: str) -> str:
        if "getaddrinfo" in raw or "11001" in raw or "Name or service not known" in raw or "No internet" in raw:
            return "I can't reach the AI servers right now. Please check your internet connection."
        if "429" in raw:
            return "The AI provider is rate-limiting us. Give me a moment and try again."
        if "401" in raw or "403" in raw:
            return "API key issue — please check your .env file."
        if "timeout" in raw.lower():
            return "The request timed out. The server may be under load."
        return raw

    async def event_gen():
        try:
            async for ev in brain.iter_chat_sse_events(body.message.strip(), voice_mode=body.voice_mode):
                if ev.get("type") == "error" and "message" in ev:
                    ev["message"] = _friendly_error(ev["message"])
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            err_msg = _friendly_error(str(e))
            err = json.dumps({"type": "error", "message": err_msg}, ensure_ascii=False)
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


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), _auth: None = Depends(verify_api_key)):
    """Ingest a file into FRIDAY's semantic knowledge base."""
    from backend.file_intelligence import ingest_file

    ALLOWED = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}
    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED))}"
        )

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:  # 20 MB limit
        raise HTTPException(status_code=413, detail="File too large. Max 20 MB.")

    result = await ingest_file(file.filename, data)

    if result.get("status") == "error":
        raise HTTPException(status_code=422, detail=result["error"])

    return result


@app.post("/api/clear")
async def clear_history(_auth: None = Depends(verify_api_key)):
    brain.conversation_history.clear()
    return {"ok": True}


class TTSBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4_000)


@app.post("/api/tts")
async def tts_endpoint(body: TTSBody, _auth: None = Depends(verify_api_key)):
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
async def speak_endpoint(body: TTSBody, _auth: None = Depends(verify_api_key)):
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
            "Do NOT read out long URLs or links. If there is a link, just say the name of the service or document instead of the raw link address. "
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
