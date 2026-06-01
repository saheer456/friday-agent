"""
FRIDAY web server — FastAPI + SSE streaming chat.
Run from repo root: python -m uvicorn web.server:app --host 127.0.0.1 --port 8080
"""

# from __future__ import annotations

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

load_dotenv(ROOT / ".env", override=True)
load_dotenv(ROOT / "friday-agent.env", override=True)

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Security, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
import httpx
import asyncio

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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
    from backend.providers import provider_manager
    providers = provider_manager._providers if hasattr(provider_manager, '_providers') else {}
    provider_name = next(iter(provider_manager._fallback_order), "unknown") if provider_manager._fallback_order else "unknown"
    provider = provider_manager.get(provider_name)
    model = provider.config.model if provider else "unknown"
    host = provider.config.base_url.split("/")[2] if provider and "://" in provider.config.base_url else "unknown"
    return {
        "llm_provider": provider_name,
        "llm_model": model,
        "llm_url_host": host,
    }


def _readiness_info() -> dict:
    """Live readiness flags — used by the frontend status badges."""
    return {
        "memory_ready": True,
        "tts_ready": _tts_ready.is_set(),
        "stt_ready": _stt_ready,
    }


_bearer = HTTPBearer(auto_error=False)


def _supabase_auth_enabled() -> bool:
    return (os.getenv("FRIDAY_SUPABASE_AUTH_ENABLED", "0").strip() in {"1", "true", "yes", "on"})


def _api_key_configured() -> str | None:
    return (os.getenv("FRIDAY_API_KEY") or "").strip() or None


def _full_access_emails() -> set[str]:
    configured = (os.getenv("FRIDAY_FULL_ACCESS_EMAILS") or "").strip()
    return {email.strip().lower() for email in configured.split(",") if email.strip()}


def _has_full_access(user: dict) -> bool:
    if user.get("email") == "api-key-owner@local":
        return True
    email = (user.get("email") or "").strip().lower()
    return bool(email) and email in _full_access_emails()


async def _verify_supabase_token(token: str) -> dict:
    base_url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    anon_key = (os.getenv("SUPABASE_ANON_KEY") or "").strip()
    service_key = (os.getenv("SUPABASE_KEY") or "").strip()
    api_key = anon_key or service_key
    if not base_url or not api_key:
        raise HTTPException(status_code=500, detail="Supabase auth is enabled but not configured.")
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(
            f"{base_url}/auth/v1/user",
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {token}",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return resp.json()


async def verify_user_auth(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(_bearer)):
    if _supabase_auth_enabled():
        if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
            raise HTTPException(status_code=401, detail="Missing bearer token.")
        return await _verify_supabase_token(credentials.credentials)
    
    api_key = _api_key_configured()
    if api_key:
        x_api_key = request.headers.get("x-api-key")
        if x_api_key == api_key:
            return {"email": "api-key-owner@local", "full_access": True}
        if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials == api_key:
            return {"email": "api-key-owner@local", "full_access": True}
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
        
    return {"auth_disabled": True}


async def verify_auth(request: Request, credentials: HTTPAuthorizationCredentials | None = Security(_bearer)):
    user = await verify_user_auth(request, credentials)
    if user.get("auth_disabled"):
        return user
    if not _has_full_access(user):
        raise HTTPException(status_code=403, detail="Full access is limited. Contact the owner to get full access.")
    return user


def _ui_info() -> dict:
    version = (os.getenv("FRIDAY_UI_VERSION") or "v2.6 Sentinel").strip()
    if not version:
        version = "v2.6 Sentinel"
    return {"version": version}


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
        from backend.tts import TTS_BACKEND, KOKORO_MODEL_PATH, KOKORO_VOICES_PATH
        backend = TTS_BACKEND
        has_kokoro_files = os.path.exists(KOKORO_MODEL_PATH) and os.path.exists(KOKORO_VOICES_PATH)
        
        if backend == "kokoro":
            _threading.Thread(target=_load_tts, daemon=True, name="warmup-tts").start()
        elif backend == "edge":
            asyncio.create_task(_ping_edge_tts())
        else: # auto
            if has_kokoro_files:
                _threading.Thread(target=_load_tts, daemon=True, name="warmup-tts").start()
            else:
                asyncio.create_task(_ping_edge_tts())
        print("[STARTUP] ✓ TTS warmup started")
    except Exception:
        print("[STARTUP] TTS warmup failed")
        traceback.print_exc()

    # Task queue
    try:
        from backend.tasks import task_queue
        task_queue.start()
        print("[STARTUP] ✓ Task queue started")
    except Exception:
        print("[STARTUP] Task queue start failed")
        traceback.print_exc()

    print("[STARTUP] Startup sequence complete")

    yield  # ← server is running

    # ─ Shutdown cleanup ─
    print("[SHUTDOWN] Cleanup...")
    try:
        from backend.tasks import task_queue
        await task_queue.stop()
        print("[SHUTDOWN] ✓ Task queue stopped")
    except Exception:
        pass


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="FRIDAY Web", version="1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

REACT_DIST_DIR = ROOT / "frontend" / "dist"
ASSETS_DIR = REACT_DIST_DIR / "assets"

ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


# ───────────────────────────────────────────────────────────────
# Runtime readiness flags
# ───────────────────────────────────────────────────────────────

# threading.Event is explicitly thread-safe (unlike a plain bool)
_tts_ready = threading.Event()
_stt_ready = True
_memory_ready = False
_whisper_model = None
_whisper_lock = asyncio.Lock()

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
    session_id: str = Field(default="default-session", max_length=100)
    voice_mode: bool = False


class LimitedChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4_000)
    local_context: str = Field(default="", max_length=6_000)


@app.get("/api/auth/me")
async def auth_me(credentials: HTTPAuthorizationCredentials | None = Security(_bearer)):
    if not _supabase_auth_enabled():
        return {"login_enabled": False, "authenticated": True, "user": None}
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        return {"login_enabled": True, "authenticated": False, "user": None}
    try:
        user = await _verify_supabase_token(credentials.credentials)
    except HTTPException as e:
        print(f"[AUTH ERROR] Supabase token verification failed: {e.detail}")
        return {"login_enabled": True, "authenticated": False, "user": None}
    except Exception as e:
        print(f"[AUTH ERROR] Unexpected error during token verification: {e}")
        return {"login_enabled": True, "authenticated": False, "user": None}
    return {
        "login_enabled": True,
        "authenticated": True,
        "full_access": _has_full_access(user),
        "contact_email": os.getenv("FRIDAY_CONTACT_EMAIL", "").strip(),
        "user": user,
    }


@app.get("/api/greeting")
async def get_greeting(_auth: dict = Depends(verify_user_auth)):
    from backend.brain import _load_profile
    from backend.memory import long_term
    from backend.providers import provider_manager
    from datetime import datetime

    # 1. Get current time-of-day and weekday
    now = datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        time_of_day = "morning"
    elif 12 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 22:
        time_of_day = "evening"
    else:
        time_of_day = "night"
    weekday = now.strftime("%A")

    # 2. Retrieve recent memories
    try:
        memories = await long_term.retrieve_recent_memories(limit=3)
        memory_texts = [m["content"] for m in memories if m.get("content")]
    except Exception as e:
        print(f"[GREETING] Failed to retrieve memories: {e}")
        memory_texts = []

    # 3. Load user profile
    try:
        profile_text = _load_profile()
    except Exception as e:
        print(f"[GREETING] Failed to load profile: {e}")
        profile_text = ""

    # 4. Construct prompt
    memories_bullet = "\n".join([f"- {text}" for text in memory_texts]) if memory_texts else "No recent memories."
    
    prompt = f"""You are FRIDAY, a warm, witty AI assistant. 
Time of day: {time_of_day}. Day: {weekday}.
User profile: {profile_text}.
Recent memories:
{memories_bullet}

Generate a single warm, personalized greeting (1–2 sentences MAX).
Rules:
- Address the user as 'sir'
- Do NOT always start with 'Hello' or 'Hi' — vary the opening
- If memory is available, reference something specific from it
- Never be generic or robotic
- Markdown is allowed (bold/italic sparingly)
Output ONLY the greeting, nothing else."""

    # 5. Determine suggestions programmatically
    suggestions = []
    # Suggestion 1: Memory-aware
    found_project = None
    mem_search_space = (" ".join(memory_texts)).lower()
    for proj in ["Expense Tracker", "Pandora Website", "Tabeer Brand", "Local Service Marketplace", "GraphRAG"]:
        if proj.lower() in mem_search_space:
            found_project = proj
            break
    if found_project:
        suggestions.append(f"Continue {found_project} work?")
    elif memory_texts:
        first_mem = memory_texts[0]
        if len(first_mem) > 40:
            suggestions.append(f"About: {first_mem[:35]}…")
        else:
            suggestions.append(first_mem)
    else:
        suggestions.append("Continue my last project")

    # Suggestion 2: Time-of-day contextual
    if time_of_day == "morning":
        suggestions.append("Give me a daily briefing")
    elif time_of_day == "afternoon":
        suggestions.append("What's on my agenda today?")
    elif time_of_day == "evening":
        suggestions.append("Summarize my progress today")
    else:
        suggestions.append("What's the weather like?")

    # Suggestion 3: General/Utility
    suggestions.append("Search the web for latest AI news")

    # 6. Stream the LLM response
    async def event_generator():
        try:
            messages = [{"role": "system", "content": prompt}]
            async for ev in provider_manager.stream(messages, is_heavy=False, temperature=0.8, max_tokens=100):
                if ev.get("type") == "text":
                    chunk = ev.get("text", "")
                    if chunk:
                        yield f"data: {json.dumps({'type': 'token', 'text': chunk}, ensure_ascii=False)}\n\n"
                elif ev.get("type") == "error":
                    err_msg = ev.get("error", "Failed generating greeting")
                    yield f"data: {json.dumps({'type': 'error', 'message': err_msg}, ensure_ascii=False)}\n\n"
                    return
            
            # Send suggestions
            yield f"data: {json.dumps({'type': 'suggestions', 'suggestions': suggestions}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            err = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )




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


@app.get("/api/admin/health-detailed")
async def health_detailed(_auth: dict = Depends(verify_auth)):
    memory_enabled = os.getenv("FRIDAY_ENABLE_MEMORY", "1").strip() in {"1", "true", "yes", "on"}
    provider_statuses = {}
    from backend.providers import provider_manager
    for p_name in provider_manager._fallback_order:
        p = provider_manager.get(p_name)
        if p:
            provider_statuses[p_name] = {
                "configured": bool(p.config.api_key and "your_" not in p.config.api_key.lower()),
                "model": p.config.model,
                "base_url": p.config.base_url,
            }
            
    return {
        "status": "ok",
        "memory": {
            "enabled": memory_enabled,
            "ready": _memory_ready,
        },
        "tts": {
            "backend": os.getenv("FRIDAY_TTS_BACKEND", "auto"),
            "ready": _tts_ready.is_set(),
        },
        "stt": {
            "ready": _stt_ready,
            "whisper_cached": _whisper_model is not None,
        },
        "providers": provider_statuses,
    }


@app.post("/api/admin/reload-skills")
async def reload_skills(_auth: dict = Depends(verify_auth)):
    try:
        def _reload():
            import importlib
            import sys
            from backend.skills.skill_base import SkillRegistry
            
            modules_to_reload = [
                name for name in sys.modules 
                if name.startswith("backend.skills.") and name != "backend.skills.skill_base"
            ]
            for mod_name in sorted(modules_to_reload):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass
                    
            SkillRegistry.clear()
            import backend.tool_bridge
            importlib.reload(backend.tool_bridge)
            
        await asyncio.to_thread(_reload)
        return {"status": "ok", "message": "Skills hot-reloaded successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload skills: {e}")


@app.get("/api/system")
async def system_info(_auth: dict = Depends(verify_user_auth)):
    """Voice stack + LLM routing (HUD)."""
    # Count total turns in default or all active session histories
    history_turns = sum(len(h) for h in brain.conversation_histories.values()) if brain.conversation_histories else 0
    return {
        "ui": _ui_info(),
        "voice": _voice_stack_info(),
        "llm": _llm_stack_info(),
        "readiness": _readiness_info(),
        "history_turns": history_turns,
    }


@app.post("/api/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(request: Request, body: ChatBody, _auth: dict = Depends(verify_auth)):
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
            async for ev in brain.iter_chat_sse_events(body.message.strip(), session_id=body.session_id, voice_mode=body.voice_mode):
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


@app.post("/api/chat/limited/stream")
async def limited_chat_stream(body: LimitedChatBody, _auth: dict = Depends(verify_user_auth)):
    """Limited demo chat: no backend memory, no powerful tools, browser context only."""
    from backend import tools_utils
    from backend.providers import provider_manager

    async def event_gen():
        try:
            msg = body.message.strip()
            lowered = msg.lower()
            if any(word in lowered for word in ["weather", "temperature", "forecast"]):
                yield f"data: {json.dumps({'type': 'phase', 'id': 'weather', 'title': 'Weather', 'detail': 'Checking conditions'}, ensure_ascii=False)}\n\n"
                location = None
                try:
                    extract_prompt = [
                        {"role": "system", "content": "You are a location extraction assistant. Extract the city/location name from the user's weather query. If no city/location is specified, output 'DEFAULT'. Respond with ONLY the city/location name or 'DEFAULT' (no other text, no punctuation, lowercase)."},
                        {"role": "user", "content": msg}
                    ]
                    resp = await provider_manager.generate(messages=extract_prompt)
                    if resp and resp.content:
                        extracted = resp.content.strip().strip("'\"`").strip()
                        if extracted and extracted.upper() != "DEFAULT":
                            location = extracted
                except Exception as e:
                    print(f"[ERROR] Location extraction failed: {e}")

                weather = await tools_utils.get_weather(location=location)
                text = weather.get("summary") if isinstance(weather, dict) else None
                if not text:
                    text = "Weather is unavailable right now."
                yield f"data: {json.dumps({'type': 'token', 'text': text}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            system = (
                "You are FRIDAY in limited demo mode. Be helpful, concise, and honest. "
                "You do not have access to terminal, files, screenshots, email, calendar, upload ingestion, "
                "or server-side memory. Use only the user's message and the browser-local memory context. "
                "If asked for unavailable tools, explain that full access is limited and suggest contacting the owner."
            )
            if body.local_context.strip():
                system += f"\n\nBROWSER-LOCAL MEMORY CONTEXT:\n{body.local_context.strip()}"

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": msg},
            ]
            yield f"data: {json.dumps({'type': 'phase', 'id': 'limited', 'title': 'Limited chat', 'detail': 'Using browser-local context'}, ensure_ascii=False)}\n\n"
            async for ev in provider_manager.stream(messages, tools=[], is_heavy=False, voice_mode=False):
                if ev.get("type") == "text":
                    yield f"data: {json.dumps({'type': 'token', 'text': ev.get('text', '')}, ensure_ascii=False)}\n\n"
                elif ev.get("type") == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': ev.get('error', 'Limited chat failed')}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

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
@limiter.limit("20/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    session_id: str = Form("default-session"),
    _auth: dict = Depends(verify_auth)
):
    """Ingest a file into FRIDAY's semantic knowledge base and associate with a chat session."""
    from backend.file_intelligence import ingest_file
    from backend.memory import chat_history

    ALLOWED = {
        ".pdf", ".docx", ".txt", ".md", ".csv", ".json",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", 
        ".sh", ".bat", ".sql", ".yaml", ".yml", ".toml", 
        ".xml", ".ini", ".cfg", ".log", ".env"
    }
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

    try:
        await chat_history.associate_file_with_session(session_id, file.filename)
    except Exception as e:
        print(f"[SERVER] Failed to associate file with session {session_id}: {e}")

    return result


@app.delete("/api/sessions/{session_id}/files/{filename:path}")
async def unlink_file_from_session(session_id: str, filename: str, _auth: dict = Depends(verify_auth)):
    try:
        from backend.memory import chat_history
        await chat_history.remove_file_from_session(session_id, filename)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clear")

async def clear_history(session_id: str | None = None, _auth: dict = Depends(verify_auth)):
    if session_id:
        if session_id in brain.conversation_histories:
            brain.conversation_histories[session_id].clear()
    else:
        brain.conversation_histories.clear()

    try:
        from backend.memory import chat_history
        await chat_history.clear_chat_history(session_id)
    except Exception as e:
        print(f"[SERVER] Failed to clear DB chat history: {e}")
    return {"ok": True}


class SessionCreateBody(BaseModel):
    id: str
    title: str


class SessionUpdateBody(BaseModel):
    title: str


@app.get("/api/sessions")
async def list_sessions(_auth: dict = Depends(verify_auth)):
    from backend.memory import chat_history
    sessions = await chat_history.get_sessions()
    if not sessions:
        await chat_history.create_session("default-session", "Default Chat")
        sessions = await chat_history.get_sessions()
    return {"sessions": sessions}


@app.post("/api/sessions")
async def create_session(body: SessionCreateBody, _auth: dict = Depends(verify_auth)):
    from backend.memory import chat_history
    await chat_history.create_session(body.id, body.title)
    return {"ok": True, "id": body.id, "title": body.title}


@app.put("/api/sessions/{session_id}")
async def update_session_title(session_id: str, body: SessionUpdateBody, _auth: dict = Depends(verify_auth)):
    from backend.memory import chat_history
    await chat_history.update_session_title(session_id, body.title)
    return {"ok": True}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, _auth: dict = Depends(verify_auth)):
    from backend.memory import chat_history
    await chat_history.delete_session(session_id)
    if session_id in brain.conversation_histories:
        del brain.conversation_histories[session_id]
    return {"ok": True}


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, format: str = "markdown", _auth: dict = Depends(verify_auth)):
    import io
    from backend.memory import chat_history
    messages = await chat_history.get_latest_chat_messages(session_id, limit=500)
    if not messages:
        raise HTTPException(status_code=404, detail="Session has no messages or does not exist.")
        
    if format.lower() == "json":
        content = json.dumps(messages, indent=2, ensure_ascii=False)
        headers = {"Content-Disposition": f"attachment; filename=session_{session_id}.json"}
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers=headers
        )
    else:
        md_lines = [f"# FRIDAY AI Dialogue Session: {session_id}\n"]
        for m in messages:
            role_label = "FRIDAY" if m["role"] == "assistant" else "YOU"
            created_str = f" ({m['created_at']})" if m.get("created_at") else ""
            md_lines.append(f"### {role_label}{created_str}\n")
            md_lines.append(f"{m['content']}\n\n---\n")
            
        md_content = "\n".join(md_lines)
        headers = {"Content-Disposition": f"attachment; filename=session_{session_id}.md"}
        return StreamingResponse(
            io.BytesIO(md_content.encode("utf-8")),
            media_type="text/markdown",
            headers=headers
        )


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, _auth: dict = Depends(verify_auth)):
    from backend.memory import chat_history
    messages = await chat_history.get_latest_chat_messages(session_id, limit=100)
    files = await chat_history.get_session_files(session_id)
    return {"messages": messages, "files": files}
class MemoryAddBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=4_000)
    category: str = Field(default="manual", max_length=100)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


@app.get("/api/memories")
async def list_memories(
    limit: int = 50,
    offset: int = 0,
    _auth: dict = Depends(verify_auth),
):
    from backend.memory import long_term
    memories = await long_term.list_memories(limit=limit, offset=offset)
    total = await long_term.count_memories()
    return {"memories": memories, "total": total, "limit": limit, "offset": offset}


@app.get("/api/graph/nodes")
async def search_graph_nodes_api(
    q: str = "",
    _auth: dict = Depends(verify_auth),
):
    """Search graph nodes by name/description keyword."""
    from backend.memory import long_term
    if not q.strip():
        return {"nodes": [], "edges": []}
    nodes = await long_term.search_graph_nodes(q.strip())
    node_ids = [n["id"] for n in nodes]
    graph = await long_term.get_graph_neighbors(node_ids, depth=1)
    return {"nodes": graph["nodes"], "edges": graph["edges"], "query": q}


@app.get("/api/graph/all")
async def get_all_graph_nodes(
    limit: int = 60,
    _auth: dict = Depends(verify_auth),
):
    """Return top N nodes with their 1-hop edges for the graph visualisation panel."""
    from backend.memory import long_term
    try:
        conn = await long_term._get_sq_conn()
        async with conn.execute(
            "SELECT id, name, type, description FROM graph_nodes LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            nodes = [dict(r) for r in rows]
    except Exception:
        nodes = []

    if not nodes:
        return {"nodes": [], "edges": []}

    node_ids = [n["id"] for n in nodes]
    graph = await long_term.get_graph_neighbors(node_ids, depth=1)
    return {"nodes": graph["nodes"], "edges": graph["edges"]}


@app.delete("/api/memories/{memory_id}")
async def delete_memory(
    memory_id: int,
    _auth: dict = Depends(verify_auth),
):
    from backend.memory import long_term
    ok = await long_term.delete_memory(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


@app.post("/api/memories")
async def add_memory(
    body: MemoryAddBody,
    _auth: dict = Depends(verify_auth),
):
    from backend.memory import long_term
    from backend.memory.semantic_memory import vector_store
    mem_id = await long_term.insert_memory(
        content=body.content,
        category=body.category,
        importance=body.importance,
    )
    if mem_id > 0:
        await vector_store.add_memory(
            memory_id=mem_id,
            text=body.content,
            category=body.category,
            importance=body.importance,
        )
    return {"id": mem_id, "ok": mem_id > 0}


class STTBody(BaseModel):
    pass


@app.post("/api/stt")
@limiter.limit("10/minute")
async def speech_to_text(
    request: Request,
    file: UploadFile = File(...),
    _auth: dict = Depends(verify_auth),
):
    """Transcribe uploaded audio via faster-whisper (server-side STT fallback)."""
    import tempfile
    data = await file.read()
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    path = tmp.name
    tmp.close()
    try:
        with open(path, "wb") as f:
            f.write(data)
        global _whisper_model
        async with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                _whisper_model = WhisperModel(
                    os.getenv("FRIDAY_WHISPER_MODEL", "small"),
                    device=os.getenv("FRIDAY_WHISPER_DEVICE", "cpu"),
                    compute_type=os.getenv("FRIDAY_WHISPER_COMPUTE", "int8"),
                )
            model = _whisper_model
        segs, _ = model.transcribe(
            path,
            language="en",
            beam_size=1,
            temperature=0.0,
            vad_filter=True,
        )
        text = " ".join(s.text for s in segs).strip()
        return {"text": text, "words": len(text.split()) if text else 0}
    except ImportError:
        raise HTTPException(status_code=501, detail="faster-whisper not installed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STT error: {e}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class TTSBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4_000)


@app.post("/api/tts")
async def tts_endpoint(body: TTSBody, _auth: dict = Depends(verify_auth)):
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
async def speak_endpoint(body: TTSBody, _auth: dict = Depends(verify_auth)):
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



class ExecuteBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=20_000)
    language: str = Field(default="python", max_length=20)
    timeout: int = Field(default=15, ge=1, le=60)


@app.post("/api/execute")
@limiter.limit("10/minute")
async def execute_code(request: Request, body: ExecuteBody, _auth: dict = Depends(verify_auth)):
    """Execute Python code in a sandboxed subprocess via CodeSkill.
    Uses the same isolated execution environment as the backend skill —
    no raw subprocess calls, timeout enforced, stdout/stderr capped.
    """
    if body.language.lower() not in {"python", "py"}:
        raise HTTPException(
            status_code=422,
            detail=f"Only Python execution is supported. Got: {body.language}"
        )

    from backend.skills.code_skill import CodeSkill
    skill = CodeSkill()
    result = skill.execute_python(body.code, timeout=body.timeout)

    return {
        "stdout":    result.data.get("stdout", "") if result.data else "",
        "stderr":    result.data.get("stderr", "") if result.data else result.message,
        "exit_code": result.data.get("exit_code", -1) if result.data else -1,
        "status":    result.status,
    }


@app.post("/api/chat")
async def chat_once(body: ChatBody, _auth: dict = Depends(verify_auth)):
    """Non-streaming fallback (full reply as JSON)."""
    parts: list[str] = []
    try:
        async for chunk in brain.stream_response(body.message.strip(), voice_mode=body.voice_mode):
            parts.append(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"reply": "".join(parts)}
