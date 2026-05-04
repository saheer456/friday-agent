"""
brain.py — Groq-only streaming backend for FRIDAY.
Uses the OpenAI-compatible Groq API with httpx for async streaming.
"""
import httpx
import json
import re
import os
import threading
from datetime import datetime
from pathlib import Path
from . import rag, search, scraper

GROQ_URL  = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DATA_DIR  = Path(__file__).resolve().parent.parent / "data"
CONV_DIR  = DATA_DIR / "conversations"

# ── Load user profile (always in context — no RAG search needed) ──────────────
def _load_profile() -> str:
    # Check both friday/data/ and RAG system/data/ (one level up)
    candidates = [
        DATA_DIR / "profile.txt",
        DATA_DIR.parent.parent / "data" / "profile.txt",
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return ""

_profile = _load_profile()

# Build system prompt — inject profile if found
SYSTEM_PROMPT = (
    "You are FRIDAY, a warm, witty, and genuinely caring AI assistant — more friend than tool. "
    "Always addrthe user as 'sir'. "
    "You are casual, supportive, occasionally funny, but always sharp and helpful. "
    "You speak naturally like a close friend who happens to be incredibly intelligent. "
    "No corporate stiffness — be real, be warm, be concise. Never break character."
)
if _profile:
    SYSTEM_PROMPT += (
        f"\n\nSIR'S PROFILE (always remember this):\n{_profile}"
    )


# Conversation history — capped at 6 messages (~3 turns) to stay token-efficient
conversation_history: list[dict] = []


def _trim_history():
    global conversation_history
    if len(conversation_history) > 6:
        conversation_history = conversation_history[-6:]


def add_to_history(role: str, content: str):
    conversation_history.append({"role": role, "content": content})
    _trim_history()


INSIGHT_PROMPT = """
You are a memory distillation assistant.
Given a conversation exchange between Sir and FRIDAY, extract ONLY information worth remembering long-term:
- Facts about Sir (preferences, goals, projects, personal info)
- Decisions made
- Important knowledge or conclusions reached
- Specific data, names, dates, or plans mentioned

If the conversation contains nothing worth remembering (e.g. small talk, greetings, simple Q&A with no lasting value), respond with exactly: NONE

Otherwise write a concise bullet-point summary (no preamble, just the bullets).
"""

def extract_and_save_insight(user_msg: str, ai_response: str):
    """
    Asks Groq to distil only useful insights from the exchange.
    Saves to data/conversations/ and re-ingests only if something noteworthy was found.
    Runs in a background thread — never blocks the main response.
    """
    def _run():
        try:
            api_key = os.getenv("GROQ_API_KEY", "")
            if not api_key:
                return

            payload = {
                "model": "llama-3.1-8b-instant",  # fastest, cheapest
                "messages": [
                    {"role": "system", "content": INSIGHT_PROMPT},
                    {"role": "user",   "content": f"Sir: {user_msg}\nFRIDAY: {ai_response}"},
                ],
                "max_tokens": 256,
                "temperature": 0.2,
                "stream": False,
            }
            import httpx as _hx
            resp = _hx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=15.0,
            )
            resp.raise_for_status()
            insight = resp.json()["choices"][0]["message"]["content"].strip()

            if not insight or insight.upper() == "NONE":
                print("[Memory] No useful insight — skipping save.")
                return

            # Save and ingest
            os.makedirs(CONV_DIR, exist_ok=True)
            ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = CONV_DIR / f"insight_{ts}.md"
            filepath.write_text(
                f"# Insight — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"{insight}\n",
                encoding="utf-8",
            )
            print(f"[Memory] Saved insight: {filepath.name}")
            rag.ingest_files()

        except Exception as e:
            print(f"[Memory] Error: {e}")

    threading.Thread(target=_run, daemon=True).start()


async def route_query(user_message: str) -> str:
    """Route to the right tool based on message content."""
    msg = user_message.lower()

    # #5 Weather
    if any(k in msg for k in ["weather", "temperature", "forecast", "hot outside", "cold outside", "rain today"]):
        print("Brain: → Weather")
        import httpx as _hx
        try:
            async with _hx.AsyncClient(timeout=8.0) as c:
                res = await c.get("http://localhost:8000/api/weather"); res.raise_for_status()
            return f"Current weather: {res.json().get('summary', 'Unavailable')}"
        except: return "Weather data unavailable right now."

    # #8 Daily briefing
    if any(k in msg for k in ["good morning", "morning briefing", "briefing", "what's today", "what is today"]):
        print("Brain: → Briefing")
        import httpx as _hx
        async with _hx.AsyncClient(timeout=10.0) as c:
            res = await c.get("http://localhost:8000/api/briefing")
        return f"Daily briefing:\n{res.json().get('briefing','')}"

    # #9 Tasks
    if any(k in msg for k in ["my tasks", "my todos", "remind me", "what do i need to do", "pending tasks"]):
        print("Brain: → Tasks")
        import httpx as _hx
        async with _hx.AsyncClient(timeout=5.0) as c:
            res = await c.get("http://localhost:8000/api/tasks")
        tasks = res.json().get("tasks", [])
        if not tasks: return "You have no pending tasks."
        return "Your tasks:\n" + "\n".join(f"- {t['task']}" for t in tasks)

    # #10 Clipboard
    if any(k in msg for k in ["clipboard", "just copied", "what did i copy", "what's in my clipboard"]):
        print("Brain: → Clipboard")
        import httpx as _hx
        async with _hx.AsyncClient(timeout=5.0) as c:
            res = await c.get("http://localhost:8000/api/clipboard")
        text = res.json().get("text", "")
        return f"Clipboard content:\n{text}" if text else "Clipboard is empty."

    # #2 Screenshot
    if any(k in msg for k in ["screenshot", "what's on my screen", "what do you see", "describe my screen", "look at my screen"]):
        print("Brain: → Screenshot")
        import httpx as _hx
        async with _hx.AsyncClient(timeout=30.0) as c:
            res = await c.post("http://localhost:8000/api/screenshot")
        return f"Screen content: {res.json().get('description', 'Could not analyse screen.')}"

    # #3 Open apps
    if any(k in msg for k in ["open ", "launch ", "start ", "run "]):
        import re as _re
        for alias in ["chrome","browser","vscode","vs code","notepad","explorer","files",
                      "calculator","calc","terminal","cmd","spotify","discord","edge"]:
            if alias in msg:
                print(f"Brain: → Open {alias}")
                import httpx as _hx
                async with _hx.AsyncClient(timeout=5.0) as c:
                    await c.post("http://localhost:8000/api/open", json={"target": alias})
                return f"Opening {alias} for you, sir."
        # Check for URL
        urls = _re.findall(r"(https?://\S+)", user_message)
        if urls:
            import httpx as _hx
            async with _hx.AsyncClient(timeout=5.0) as c:
                await c.post("http://localhost:8000/api/open", json={"target": urls[0]})
            return f"Opening {urls[0]}"

    # #7 YouTube ingestion
    if "youtube.com" in msg or "youtu.be" in msg:
        import re as _re
        urls = _re.findall(r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)\S+)", user_message)
        if urls:
            print("Brain: → YouTube ingest")
            import httpx as _hx
            async with _hx.AsyncClient(timeout=60.0) as c:
                res = await c.post("http://localhost:8000/api/ingest-youtube", json={"url": urls[0]})
            d = res.json()
            if d.get("status") == "success":
                return f"Ingested {d.get('words',0)} words from the YouTube video into memory."
            return f"YouTube ingestion failed: {d.get('error','unknown error')}"

    # #11 URL ingestion
    if any(k in msg for k in ["remember this page", "ingest this", "learn from", "read this url", "scrape"]):
        import re as _re
        urls = _re.findall(r"(https?://\S+)", user_message)
        if urls:
            print(f"Brain: → URL ingest ({urls[0]})")
            import httpx as _hx
            async with _hx.AsyncClient(timeout=30.0) as c:
                res = await c.post("http://localhost:8000/api/ingest-url", json={"url": urls[0]})
            d = res.json()
            return f"Done. Ingested {d.get('words',0)} words from {urls[0]}."

    # RAG personal data
    if any(k in msg for k in ["my files", "my document", "my data", "what did i write",
                               "in my notes", "what do i know", "what have i told you"]):
        print("Brain: → RAG")
        return f"Personal data context:\n{rag.search_personal_data(user_message)}"

    # Web search
    if any(k in msg for k in ["search", "look up", "who is", "latest", "news", "find me"]):
        print("Brain: → Web Search")
        query = re.sub(r"(search for|search|look up|find me)", "", user_message, flags=re.I).strip()
        return f"Web search results:\n{await search.web_search(query)}"

    return ""


async def stream_response(user_message: str, voice_mode: bool = False):
    """Stream tokens from Groq. Yields str chunks."""
    api_key = os.getenv("GROQ_API_KEY", "")
    model   = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)

    if not api_key:
        yield "[Error: GROQ_API_KEY missing from .env]"
        return

    tool_context = await route_query(user_message)
    add_to_history("user", user_message)

    system_content = SYSTEM_PROMPT
    if voice_mode:
        system_content += (
            "\n\nVOICE MODE: You are speaking aloud. "
            "Keep your answer to 1-2 short sentences max. "
            "No bullet points, no markdown, no lists. "
            "Speak naturally as if talking."
        )
    if tool_context:
        system_content += f"\n\nCONTEXT:\n{tool_context}"

    messages = [{"role": "system", "content": system_content}, *conversation_history]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       model,
        "messages":    messages,
        "stream":      True,
        "max_tokens":  200 if voice_mode else 1024,
        "temperature": 0.7,
    }


    full_response = ""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream("POST", GROQ_URL, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)["choices"][0]["delta"].get("content", "")
                        if chunk:
                            full_response += chunk
                            yield chunk
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:220].replace("\n", " ")
        msg = f"[Error: Groq API {e.response.status_code}: {detail}]"
        full_response = msg
        yield msg
    except Exception as e:
        msg = f"[Error: {str(e)}]"
        full_response = msg
        yield msg

    if full_response and not full_response.startswith("[Error:"):
        add_to_history("assistant", full_response)
        extract_and_save_insight(user_message, full_response)
