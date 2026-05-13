"""
brain.py — Streaming chat backend for FRIDAY.

Providers (OpenAI-compatible HTTP + SSE):
  - Groq       — GROQ_API_KEY, GROQ_MODEL
  - OpenRouter — OPENROUTER_API_KEY, OPENROUTER_MODEL

Pick with FRIDAY_LLM_PROVIDER=groq|openrouter, or auto: OpenRouter if
OPENROUTER_API_KEY is set, otherwise Groq.
"""
import httpx
import asyncio
import json
import re
import os
from pathlib import Path
from . import rag, search, scraper, memory as mem, tools

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENROUTER_MODEL = "ring-2.6-1t:free"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _llm_provider() -> str:
    explicit = os.getenv("FRIDAY_LLM_PROVIDER", "").strip().lower()
    if explicit in ("groq", "openrouter"):
        return explicit
    gq = (os.getenv("GROQ_API_KEY") or "").strip()
    or_k = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if gq and "your_" not in gq.lower():
        return "groq"
    if or_k and "your_" not in or_k.lower():
        return "openrouter"
    return "groq"


def _chat_stream_config() -> tuple[str, str, str, str]:
    """Returns (url, api_key, model_id, provider_label)."""
    if _llm_provider() == "openrouter":
        key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        model = (os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL).strip()
        return OPENROUTER_URL, key, model, "OpenRouter"
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model = (os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL).strip()
    return GROQ_URL, key, model, "Groq"


def _openrouter_headers(base: dict) -> dict:
    h = dict(base)
    h["HTTP-Referer"] = (os.getenv("OPENROUTER_HTTP_REFERER") or "http://localhost").strip()
    h["X-Title"] = (os.getenv("OPENROUTER_APP_TITLE") or "FRIDAY").strip()
    return h

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

# Profile is loaded lazily inside stream_response

# Conversation history — capped at 10 messages (5 turns) to save tokens
conversation_history: list[dict] = []
MAX_HISTORY = 10


def _trim_history():
    global conversation_history
    if len(conversation_history) > MAX_HISTORY:
        conversation_history = conversation_history[-MAX_HISTORY:]


def add_to_history(role: str, content: str):
    conversation_history.append({"role": role, "content": content})
    _trim_history()




# ── Smalltalk detector — skip expensive tools/memory for greetings ────────────
_SMALLTALK_PATTERNS = [
    "hai", "hi", "hello", "hey", "sup", "yo", "howdy",
    "how are you", "how's it going", "what's up", "whats up",
    "good morning", "good evening", "good night", "gn", "bye",
    "ok", "okay", "cool", "thanks", "thank you", "lol", "haha",
    "nice", "great", "got it", "sounds good", "sure", "yep", "nope",
]

def _is_smalltalk(msg: str) -> bool:
    """True if the message is a short greeting/filler with no real query."""
    stripped = msg.strip().lower().rstrip("!?.")
    # Exact match OR very short message that starts with a smalltalk word
    if stripped in _SMALLTALK_PATTERNS:
        return True
    if len(stripped.split()) <= 4:
        return any(stripped.startswith(p) for p in _SMALLTALK_PATTERNS)
    return False


async def route_query(user_message: str) -> str:
    """Route to the right tool based on message content."""
    msg = user_message.lower()

    # #5 Weather
    if any(k in msg for k in ["weather", "forecast", "hot outside", "cold outside", "rain today"]):
        print("Brain: → Weather")
        res = await tools.get_weather()
        return f"Current weather: {res.get('summary', 'Unavailable')}"

    # #8 Daily briefing
    if any(k in msg for k in ["good morning", "morning briefing", "briefing", "what's today", "what is today"]):
        print("Brain: → Briefing")
        res = await tools.daily_briefing()
        return f"Daily briefing:\n{res.get('briefing','')}"

    # #9 Tasks
    if any(k in msg for k in ["my tasks", "my todos", "remind me", "what do i need to do", "pending tasks"]):
        print("Brain: → Tasks")
        res = await tools.list_tasks()
        tasks = res.get("tasks", [])
        if not tasks: return "You have no pending tasks."
        return "Your tasks:\n" + "\n".join(f"- {t['task']}" for t in tasks)

    # #10 Clipboard
    if any(k in msg for k in ["clipboard", "just copied", "what did i copy", "what's in my clipboard"]):
        print("Brain: → Clipboard")
        res = tools.read_clipboard()
        text = res.get("text", "")
        return f"Clipboard content:\n{text}" if text else "Clipboard is empty."

    # #2 Screenshot
    if any(k in msg for k in ["screenshot", "what's on my screen", "what do you see", "describe my screen", "look at my screen"]):
        print("Brain: → Screenshot")
        res = await tools.take_screenshot()
        return f"Screen content: {res.get('description', 'Could not analyse screen.')}"

    # #3 Open apps
    import re as _re
    if _re.search(r"\b(open|launch|start|run)\s+", msg):

        for alias in ["chrome","browser","vscode","vs code","notepad","explorer","files",
                      "calculator","calc","terminal","cmd","spotify","discord","edge"]:
            if _re.search(rf"\b{alias}\b", msg):
                print(f"Brain: → Open {alias}")
                tools.open_app(alias)
                return f"Opening {alias} for you, sir."
        # Check for URL
        urls = _re.findall(r"(https?://\S+)", user_message)
        if urls:
            tools.open_app(urls[0])
            return f"Opening {urls[0]}"

    # #7 YouTube ingestion
    if "youtube.com" in msg or "youtu.be" in msg:
        import re as _re
        urls = _re.findall(r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)\S+)", user_message)
        if urls:
            print("Brain: → YouTube ingest")
            d = await tools.ingest_youtube(urls[0])
            if d.get("status") == "success":
                return f"Ingested {d.get('words',0)} words from the YouTube video into memory."
            return f"YouTube ingestion failed: {d.get('error','unknown error')}"

    # #11 URL ingestion
    if any(k in msg for k in ["remember this page", "ingest this", "learn from", "read this url", "scrape"]):
        import re as _re
        urls = _re.findall(r"(https?://\S+)", user_message)
        if urls:
            print(f"Brain: → URL ingest ({urls[0]})")
            d = await tools.ingest_url(urls[0])
            return f"Done. Ingested {d.get('words',0)} words from {urls[0]}."

    # #12 Calendar
    if any(k in msg for k in ["calendar", "add event", "schedule", "remind me at", "remind me on", "class at"]):
        print("Brain: → Calendar")
        api_key = os.getenv("GROQ_API_KEY", "")
        if api_key:
            from datetime import datetime
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            prompt = f"The user wants to add a calendar event based on: '{user_message}'. The current time is {now}. Extract the title and start time. Return ONLY a JSON object with keys 'title', 'start_time' (format YYYY-MM-DD HH:MM:SS), 'duration_minutes' (integer, default 60), and 'location' (string). No markdown, no other text."
            payload = {
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.post("https://api.groq.com/openai/v1/chat/completions",
                                     headers={"Authorization": f"Bearer {api_key}"}, json=payload)
                    r.raise_for_status()
                    data = json.loads(r.json()["choices"][0]["message"]["content"])
                    res = tools.add_calendar_event(data.get("title", "Event"), data.get("start_time"), data.get("duration_minutes", 60), data.get("location", ""))
                    if res.get("status") == "success":
                        return f"Action complete: I generated a calendar event for '{data.get('title')}' at {data.get('start_time')} and opened it in your calendar app for you to save."
                    return f"Failed to open calendar: {res.get('error')}"
            except Exception as e:
                pass # Fallback to normal chat if extraction fails

    # #13 Email
    if any(k in msg for k in ["email", "send an email", "mail to"]):
        print("Brain: → Email")
        api_key = os.getenv("GROQ_API_KEY", "")
        if api_key:
            prompt = f"The user wants to send an email based on: '{user_message}'. Extract the recipient, subject, and body. Return ONLY a JSON object with keys 'to', 'subject', and 'body'. No markdown, no other text."
            payload = {
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.post("https://api.groq.com/openai/v1/chat/completions",
                                     headers={"Authorization": f"Bearer {api_key}"}, json=payload)
                    r.raise_for_status()
                    data = json.loads(r.json()["choices"][0]["message"]["content"])
                    res = tools.send_email(data.get("to", ""), data.get("subject", ""), data.get("body", ""))
                    if res.get("status") == "success":
                        return f"Action complete: I opened an email draft addressed to {data.get('to')} with the subject and body pre-filled. You just need to click send."
                    return f"Failed to open email client: {res.get('error')}"
            except Exception as e:
                pass # Fallback to normal chat if extraction fails

    # RAG personal data
    if any(k in msg for k in ["my files", "my document", "my data", "what did i write",
                               "in my notes", "what do i know", "what have i told you"]):
        print("Brain: → RAG")
        return f"Personal data context:\n{rag.search_personal_data(user_message)}"

    # Web search
    if any(k in msg for k in ["search", "look up", "who is", "latest news", "find me"]):
        print("Brain: → Web Search")
        query = re.sub(r"(search for|search|look up|find me)", "", user_message, flags=re.I).strip()
        return f"Web search results:\n{await search.web_search(query)}"

    return ""


async def _http_stream_error_snippet(resp: httpx.Response) -> str:
    """Streaming responses must be read before .text / .json (httpx 0.28+)."""
    try:
        await resp.aread()
        t = (resp.text or "").replace("\n", " ")[:400]
        return t if t else "(empty body)"
    except Exception as ex:
        return f"(could not read body: {ex})"


async def _iter_chat_turn(user_message: str, voice_mode: bool, emit_phases: bool):
    """
    Core chat turn. Yields:
      ("phase", dict) — optional UI telemetry
      ("text", str)   — model token / fragment
      ("error", str)  — fatal error message (caller should stop)
    """
    url, api_key, model, provider = _chat_stream_config()

    if not api_key or "your_" in api_key.lower():
        yield ("error", f"[Error: API key missing for {provider} — set OPENROUTER_API_KEY or GROQ_API_KEY in .env]")
        return

    if emit_phases:
        yield (
            "phase",
            {
                "id": "ingress",
                "title": "Neural ingress",
                "detail": "Decomposing lexical intent · quantizing query manifold",
            },
        )

    tool_context = await route_query(user_message)

    if emit_phases:
        if tool_context.strip():
            yield (
                "phase",
                {
                    "id": "routing",
                    "title": "Auxiliary routing matrix",
                    "detail": "Engaging tool fabric · weaving contextual subroutines",
                },
            )
        else:
            yield (
                "phase",
                {
                    "id": "routing",
                    "title": "Direct reasoning path",
                    "detail": "Bypassing heavy subsystems · low-latency uplink primed",
                },
            )

    recalled = ""
    if not _is_smalltalk(user_message):
        # Run in executor — _get_memory() loads HuggingFace model on first call
        # and would block the entire event loop (and stall SSE flushing) if called directly.
        loop = asyncio.get_event_loop()
        recalled = await loop.run_in_executor(
            None, mem.recall_memory, user_message, 3
        ) or ""
        if recalled:
            tool_context = f"LONG-TERM MEMORIES (about sir):\n{recalled}\n\n{tool_context}".strip()
            if emit_phases:
                yield (
                    "phase",
                    {
                        "id": "memory",
                        "title": "Mem₀ graph substrate",
                        "detail": "Episodic recall · stitching salient long-term traces",
                    },
                )

    add_to_history("user", user_message)

    system_content = (
        "You are FRIDAY, a warm, witty, and genuinely caring AI assistant — more friend than tool. "
        "Always address the user as 'sir'. "
        "You are casual, supportive, occasionally funny, but always sharp and helpful. "
        "You speak naturally like a close friend who happens to be incredibly intelligent. "
        "No corporate stiffness — be real, be warm, be concise. Never break character."
    )
    _profile = _load_profile()
    if _profile:
        system_content += f"\n\nSIR'S PROFILE (always remember this):\n{_profile}"

    if voice_mode:
        system_content += (
            "\n\nOUTPUT CHANNEL: VOICE (spoken aloud via TTS). "
            "Keep your answer to 1-3 short, conversational sentences. "
            "NO markdown, NO bullet points, NO lists, NO code blocks, NO headers. "
            "Speak naturally as if talking to a friend — be warm and direct."
        )
    else:
        system_content += (
            "\n\nOUTPUT CHANNEL: WEB CHAT with real-time voice readback. "
            "Format your response with Markdown for display, but structure it so it also sounds natural when spoken. "
            "RULES:\n"
            "- Write bullet points as COMPLETE sentences with a subject and verb (e.g. 'Clustering groups similar data points together.')\n"
            "- NEVER use the '**Term**: description' anti-pattern — instead write '**Term** is/does/means description.'\n"
            "- Use `## headers` only for multi-section responses, not for single-topic answers\n"
            "- Use numbered lists only for strict step-by-step sequences\n"
            "- Code examples: always wrap in ```language blocks\n"
            "- For conversational replies, plain prose is better than bullet lists"
        )
    if tool_context:
        system_content += f"\n\nCONTEXT:\n{tool_context}"

    messages = [{"role": "system", "content": system_content}, *conversation_history]

    if emit_phases:
        yield (
            "phase",
            {
                "id": "lattice",
                "title": "Context lattice",
                "detail": f"{len(messages)} message tensors harmonized · persona lock engaged",
            },
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "OpenRouter":
        headers = _openrouter_headers(headers)

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 400 if voice_mode else 600,
        "temperature": 0.7,
    }

    if emit_phases:
        yield (
            "phase",
            {
                "id": "uplink",
                "title": "Quantum uplink",
                "detail": f"{provider} · {model} · establishing token stream",
            },
        )

    full_response = ""
    timeout = 120.0 if provider == "OpenRouter" else 30.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                        chunk = delta.get("content") or delta.get("reasoning") or ""
                        if chunk:
                            full_response += chunk
                            yield ("text", chunk)
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue
    except httpx.HTTPStatusError as e:
        detail = await _http_stream_error_snippet(e.response)
        msg = f"[Error: {provider} API {e.response.status_code}: {detail}]"
        full_response = msg
        yield ("error", msg)
    except Exception as e:
        msg = f"[Error: {str(e)}]"
        full_response = msg
        yield ("error", msg)

    if full_response and not full_response.startswith("[Error:"):
        add_to_history("assistant", full_response)
        if not _is_smalltalk(user_message):
            mem.save_memory(user_message, full_response)


async def iter_chat_sse_events(user_message: str, voice_mode: bool = False):
    """Web / diagnostics: same turn as stream_response, with phase telemetry dicts."""
    async for kind, payload in _iter_chat_turn(user_message, voice_mode, emit_phases=True):
        if kind == "phase":
            yield {"type": "phase", **payload}
        elif kind == "text":
            yield {"type": "token", "text": payload}
        elif kind == "error":
            yield {"type": "error", "message": payload}


async def stream_response(user_message: str, voice_mode: bool = False):
    """Stream tokens from Groq or OpenRouter. Yields str chunks (CLI / simple clients)."""
    async for kind, payload in _iter_chat_turn(user_message, voice_mode, emit_phases=False):
        if kind == "text":
            yield payload
        elif kind == "error":
            yield payload
