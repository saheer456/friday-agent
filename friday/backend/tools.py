import os
import re
import base64
import io
import subprocess
import webbrowser
import pyperclip
from pathlib import Path
from datetime import datetime
import httpx

from . import rag, scraper

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONV_DIR = DATA_DIR / "conversations"

APP_ALIASES = {
    "chrome":"chrome", "browser":"chrome", "edge":"msedge",
    "vscode":"code", "vs code":"code", "code":"code",
    "notepad":"notepad", "explorer":"explorer", "files":"explorer",
    "calculator":"calc", "calc":"calc", "terminal":"wt", "cmd":"cmd",
    "spotify":"spotify", "discord":"discord", "slack":"slack",
}

async def get_weather(lat: float = None, lon: float = None) -> dict:
    if lat is None: lat = float(os.getenv("FRIDAY_LAT", 28.6))
    if lon is None: lon = float(os.getenv("FRIDAY_LON", 77.2))
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m,relativehumidity_2m"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&timezone=auto&forecast_days=1"
        )
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(url)
            r.raise_for_status()
        d = r.json()
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
        return {"error": str(e)}

async def list_tasks() -> dict:
    os.makedirs(CONV_DIR, exist_ok=True)
    tasks = []
    for f in sorted(CONV_DIR.glob("*.md")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if "[TASK]" in line.upper():
                tasks.append({"task": line.upper().replace("[TASK]","").strip(" -•*"), "file": f.name})
    return {"tasks": tasks}

async def daily_briefing() -> dict:
    w = await get_weather()
    t = await list_tasks()
    ws = w.get("summary", "Weather unavailable") if "error" not in w else "Unavailable"
    tl = t.get("tasks", [])
    ts = "\n".join(f"- {x['task']}" for x in tl) if tl else "No pending tasks."
    day = datetime.now().strftime("%A, %B %d")
    return {"status": "success",
            "briefing": f"Today is {day}.\nWeather: {ws}\nPending tasks:\n{ts}"}

def read_clipboard() -> dict:
    try:
        return {"status": "success", "text": pyperclip.paste()[:4000]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def take_screenshot() -> dict:
    try:
        from PIL import ImageGrab
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
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post("https://api.groq.com/openai/v1/chat/completions",
                             headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            r.raise_for_status()
        return {"status": "success", "description": r.json()["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def open_app(target: str) -> dict:
    target = target.strip().lower()
    if not target:
        return {"error": "target required"}
    try:
        if target.startswith("http"):
            webbrowser.open(target)
            return {"status": "success", "opened": target}
        
        cmd = APP_ALIASES.get(target, target)
        subprocess.Popen(cmd, shell=True)
        return {"status": "success", "opened": cmd}
    except Exception as e:
        return {"error": str(e)}

async def ingest_youtube(url: str) -> dict:
    if not url:
        return {"error": "url required"}
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        vid = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url)
        if not vid:
            return {"error": "Invalid YouTube URL"}
        transcript = YouTubeTranscriptApi.get_transcript(vid.group(1))
        text = " ".join(t["text"] for t in transcript)
        web_dir = DATA_DIR / "web"
        os.makedirs(web_dir, exist_ok=True)
        fp = web_dir / f"youtube_{vid.group(1)}.md"
        fp.write_text(f"# YouTube: {url}\n\n{text}", encoding="utf-8")
        rag.ingest_files()
        return {"status": "success", "words": len(text.split()), "file": fp.name}
    except Exception as e:
        return {"error": str(e)}

async def ingest_url(url: str) -> dict:
    if not url:
        return {"error": "url required"}
    try:
        text = await scraper.scrape_url(url)
        web_dir = DATA_DIR / "web"
        os.makedirs(web_dir, exist_ok=True)
        safe = "".join(c if c.isalnum() else "_" for c in url[:60])
        fp = web_dir / f"web_{safe}.md"
        fp.write_text(text, encoding="utf-8")
        rag.ingest_files()
        return {"status": "success", "words": len(text.split()), "url": url}
    except Exception as e:
        return {"error": str(e)}
