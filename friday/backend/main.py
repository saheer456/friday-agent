"""
main.py — FRIDAY FastAPI backend
All 15 features implemented as API endpoints.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os, shutil, tempfile
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from . import brain, system, rag, voice_in, voice_out, tts as tts_engine

BASE_DIR     = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR     = BASE_DIR / "data"
CONV_DIR     = DATA_DIR / "conversations"

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("FRIDAY Systems booting up...")
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CONV_DIR, exist_ok=True)
    try:
        rag.ingest_files()
    except Exception as e:
        print(f"Startup ingestion failed: {e}")

    # Pre-warm Kokoro TTS in background — eliminates cold-start lag on first voice response
    import threading
    def _warmup_tts():
        try:
            tts_engine._get_kokoro()
        except Exception as e:
            print(f"[TTS warmup] {e}")
    threading.Thread(target=_warmup_tts, daemon=True, name="tts-warmup").start()

    yield
    print("FRIDAY shutting down.")

app = FastAPI(title="FRIDAY AI Assistant", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ── Core ──────────────────────────────────────────────────────────────────────
@app.get("/")
async def get_index():
    try:
        return HTMLResponse(content=(FRONTEND_DIR / "index.html").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return HTMLResponse("Frontend not found.")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon(): return Response(status_code=204)

@app.get("/api/stats")
async def get_stats(): return JSONResponse(system.get_stats())

# ── Models ────────────────────────────────────────────────────────────────────
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
FALLBACK_GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
    "groq/compound",
    "groq/compound-mini",
]
CHAT_MODEL_MARKERS = (
    "llama",
    "gpt-oss",
    "qwen",
    "gemma",
    "compound",
)
NON_CHAT_MODEL_MARKERS = (
    "whisper",
    "guard",
    "playai",
    "tts",
    "stt",
)


def _is_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    return any(x in mid for x in CHAT_MODEL_MARKERS) and not any(
        x in mid for x in NON_CHAT_MODEL_MARKERS
    )

async def _available_groq_models() -> list[str]:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return FALLBACK_GROQ_MODELS
    try:
        import httpx as _hx
        async with _hx.AsyncClient(timeout=5.0) as c:
            r = await c.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
        ids = sorted(
            m["id"] for m in r.json().get("data", [])
            if isinstance(m, dict) and isinstance(m.get("id"), str)
            and _is_chat_model(m["id"])
        )
        return ids or FALLBACK_GROQ_MODELS
    except Exception as e:
        print(f"[Models] Groq model lookup failed: {e}")
        return FALLBACK_GROQ_MODELS


def _current_groq_model(models: list[str] | None = None) -> str:
    current = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
    if models and current not in models:
        current = DEFAULT_GROQ_MODEL if DEFAULT_GROQ_MODEL in models else models[0]
        os.environ["GROQ_MODEL"] = current
    return current

@app.get("/api/models")
async def list_models():
    models = await _available_groq_models()
    current = _current_groq_model(models)
    return {"models": models, "current": current}

@app.post("/api/set-model")
async def set_model(body: dict):
    model = body.get("model", "").strip()
    models = await _available_groq_models()
    if not model or model not in models:
        return JSONResponse({"error": "invalid model"}, status_code=400)
    os.environ["GROQ_MODEL"] = model
    return {"status": "success", "model": model}

# ── RAG / Files ───────────────────────────────────────────────────────────────
@app.post("/api/ingest")
async def trigger_ingestion():
    try:
        rag.ingest_files()
        return {"status": "success"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        fp = DATA_DIR / file.filename
        with open(fp, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        rag.ingest_files()
        return {"status": "success", "file": file.filename}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ── STT ───────────────────────────────────────────────────────────────────────
@app.post("/api/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    try:
        suffix = Path(audio.filename).suffix or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(audio.file, tmp)
            tmp_path = tmp.name
        text = voice_in.transcribe_audio(tmp_path)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return {"status": "success", "text": text}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ── Feature: Edge TTS ─────────────────────────────────────────────────────────
from fastapi.responses import StreamingResponse
import io

@app.post("/api/tts")
async def synthesize_speech(body: dict):
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    try:
        speed = body.get("speed")
        audio, suffix = await tts_engine.synthesize(text, speed=speed)
        if not audio:
            return JSONResponse({"error": "empty synthesis"}, status_code=500)
        mime = "audio/wav" if suffix == ".wav" or audio[:4] == b"RIFF" else "audio/mpeg"
        return StreamingResponse(io.BytesIO(audio), media_type=mime)
    except Exception as e:
        print(f"TTS error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Feature #5: Weather (Open-Meteo, free, no key) ───────────────────────────
@app.get("/api/weather")
async def get_weather(lat: float = 28.6, lon: float = 77.2):
    import httpx as _hx
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m,relativehumidity_2m"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&timezone=auto&forecast_days=1"
        )
        async with _hx.AsyncClient(timeout=8.0) as c:
            r = await c.get(url); r.raise_for_status()
        d   = r.json()
        cur = d["current"]
        WMO = {0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",
               45:"Foggy",51:"Drizzle",61:"Rain",71:"Snow",80:"Showers",95:"Thunderstorm"}
        cond = WMO.get(cur["weathercode"], "Unknown")
        hi, lo = d["daily"]["temperature_2m_max"][0], d["daily"]["temperature_2m_min"][0]
        summary = f"{cond}, {cur['temperature_2m']}°C (High {hi} / Low {lo}), Humidity {cur['relativehumidity_2m']}%, Wind {cur['windspeed_10m']} km/h"
        return {"temp_c": cur["temperature_2m"], "condition": cond,
                "humidity": cur["relativehumidity_2m"], "wind_kph": cur["windspeed_10m"],
                "max_c": hi, "min_c": lo, "summary": summary}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Feature #10: Clipboard ────────────────────────────────────────────────────
@app.get("/api/clipboard")
async def read_clipboard():
    try:
        import pyperclip
        return {"status": "success", "text": pyperclip.paste()[:4000]}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ── Feature #6: Memory browser ────────────────────────────────────────────────
@app.get("/api/memories")
async def list_memories():
    os.makedirs(CONV_DIR, exist_ok=True)
    memories = []
    for f in sorted(CONV_DIR.glob("*.md"), reverse=True)[:50]:
        lines   = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        preview = lines[0][:120] if lines else ""
        date    = f.stem.replace("insight_", "").replace("conv_", "")
        memories.append({"filename": f.name, "date": date, "preview": preview})
    return {"memories": memories}

@app.delete("/api/memories/{filename}")
async def delete_memory(filename: str):
    try:
        fp = CONV_DIR / filename
        if fp.exists() and fp.parent.resolve() == CONV_DIR.resolve():
            fp.unlink(); return {"status": "success"}
        return JSONResponse({"error": "Not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Feature #9: Task tracker ──────────────────────────────────────────────────
@app.get("/api/tasks")
async def list_tasks():
    os.makedirs(CONV_DIR, exist_ok=True)
    tasks = []
    for f in sorted(CONV_DIR.glob("*.md")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if "[TASK]" in line.upper():
                tasks.append({"task": line.upper().replace("[TASK]","").strip(" -•*"), "file": f.name})
    return {"tasks": tasks}

# ── Feature #7: YouTube ingestion ────────────────────────────────────────────
@app.post("/api/ingest-youtube")
async def ingest_youtube(body: dict):
    import re as _re
    url = body.get("url", "")
    if not url:
        return JSONResponse({"error": "url required"}, status_code=400)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        vid = _re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url)
        if not vid:
            return JSONResponse({"error": "Invalid YouTube URL"}, status_code=400)
        transcript = YouTubeTranscriptApi.get_transcript(vid.group(1))
        text = " ".join(t["text"] for t in transcript)
        web_dir = DATA_DIR / "web"; os.makedirs(web_dir, exist_ok=True)
        fp = web_dir / f"youtube_{vid.group(1)}.md"
        fp.write_text(f"# YouTube: {url}\n\n{text}", encoding="utf-8")
        rag.ingest_files()
        return {"status": "success", "words": len(text.split()), "file": fp.name}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Feature #11: Auto-ingest URL ─────────────────────────────────────────────
@app.post("/api/ingest-url")
async def ingest_url(body: dict):
    url = body.get("url", "")
    if not url:
        return JSONResponse({"error": "url required"}, status_code=400)
    try:
        from . import scraper as _sc
        text    = await _sc.scrape_url(url)
        web_dir = DATA_DIR / "web"; os.makedirs(web_dir, exist_ok=True)
        safe    = "".join(c if c.isalnum() else "_" for c in url[:60])
        fp      = web_dir / f"web_{safe}.md"
        fp.write_text(f"# Web: {url}\n\n{text}", encoding="utf-8")
        rag.ingest_files()
        return {"status": "success", "words": len(text.split()), "url": url}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Feature #2: Screenshot + Groq Vision ─────────────────────────────────────
@app.post("/api/screenshot")
async def take_screenshot():
    try:
        from PIL import ImageGrab
        import base64, io, httpx as _hx
        buf = io.BytesIO()
        ImageGrab.grab().save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        api_key = os.getenv("GROQ_API_KEY", "")
        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Describe what is on this screen concisely for a voice assistant response."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]}],
            "max_tokens": 512,
        }
        async with _hx.AsyncClient(timeout=30.0) as c:
            r = await c.post("https://api.groq.com/openai/v1/chat/completions",
                             headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            r.raise_for_status()
        return {"status": "success", "description": r.json()["choices"][0]["message"]["content"]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Feature #3: Open apps / URLs ─────────────────────────────────────────────
APP_ALIASES = {
    "chrome":"chrome","browser":"chrome","edge":"msedge",
    "vscode":"code","vs code":"code","code":"code",
    "notepad":"notepad","explorer":"explorer","files":"explorer",
    "calculator":"calc","calc":"calc","terminal":"wt","cmd":"cmd",
    "spotify":"spotify","discord":"discord","slack":"slack",
}

@app.post("/api/open")
async def open_app(body: dict):
    import subprocess as _sp, webbrowser as _wb
    target = body.get("target", "").strip().lower()
    if not target:
        return JSONResponse({"error": "target required"}, status_code=400)
    try:
        if target.startswith("http"):
            _wb.open(target); return {"status": "success", "opened": target}
        cmd = APP_ALIASES.get(target, target)
        _sp.Popen(cmd, shell=True)
        return {"status": "success", "opened": cmd}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Feature #8: Daily briefing ────────────────────────────────────────────────
@app.get("/api/briefing")
async def daily_briefing():
    from datetime import datetime as _dt
    w   = await get_weather()
    t   = await list_tasks()
    ws  = w.get("summary", "Weather unavailable") if isinstance(w, dict) else "Unavailable"
    tl  = t.get("tasks", [])
    ts  = "\n".join(f"- {x['task']}" for x in tl) if tl else "No pending tasks."
    day = _dt.now().strftime("%A, %B %d")
    return {"status": "success",
            "briefing": f"Today is {day}.\nWeather: {ws}\nPending tasks:\n{ts}"}

# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected to /ws/chat")
    try:
        while True:
            data = await websocket.receive_text()
            full_response = ""
            async for chunk in brain.stream_response(data):
                full_response += chunk
                await websocket.send_text(chunk)
            if full_response and os.getenv("TTS_BACKEND", "browser") == "server":
                voice_out.speak(full_response)
            await websocket.send_text("[DONE]")
    except WebSocketDisconnect:
        print("Client disconnected from /ws/chat")
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.send_text(f"\n[Error: {str(e)}]")
            await websocket.send_text("[DONE]")
        except: pass
