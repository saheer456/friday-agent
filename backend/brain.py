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
import threading
from pathlib import Path

_http_client = None
_api_semaphore = None

def _get_api_semaphore() -> asyncio.Semaphore:
    global _api_semaphore
    if _api_semaphore is None:
        _api_semaphore = asyncio.Semaphore(4)
    return _api_semaphore

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        _http_client = httpx.AsyncClient(limits=limits)
    return _http_client

def _reset_http_client():
    global _http_client
    if _http_client:
        asyncio.create_task(_http_client.aclose())
    _http_client = None

async def _is_online() -> bool:
    try:
        client = _get_http_client()
        # Fast DNS / connectivity check to Cloudflare
        await client.head("https://1.1.1.1", timeout=3.0)
        return True
    except Exception:
        return False

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENROUTER_MODEL = "google/gemini-2.0-flash-lite-preview-02-05:free"
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


def _is_key_usable(key: str) -> bool:
    key = (key or "").strip()
    return bool(key) and "your_" not in key.lower()


def _fallback_stream_configs() -> list[tuple[str, str, str, str]]:
    """
    Preferred provider first, then the alternate provider if configured.
    This lets FRIDAY survive transient provider/network faults.
    """
    primary = _llm_provider()
    order = [primary, "openrouter" if primary == "groq" else "groq"]
    configs: list[tuple[str, str, str, str]] = []

    for provider in order:
        if provider == "openrouter":
            key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
            model = (os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL).strip()
            if _is_key_usable(key):
                configs.append((OPENROUTER_URL, key, model, "OpenRouter"))
        else:
            key = (os.getenv("GROQ_API_KEY") or "").strip()
            model = (os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL).strip()
            if _is_key_usable(key):
                configs.append((GROQ_URL, key, model, "Groq"))
    return configs


def _openrouter_headers(base: dict) -> dict:
    h = dict(base)
    h["HTTP-Referer"] = (os.getenv("OPENROUTER_HTTP_REFERER") or "http://localhost").strip()
    h["X-Title"] = (os.getenv("OPENROUTER_APP_TITLE") or "FRIDAY").strip()
    return h

# ── Load user profile (cached — only reads disk once) ────────────────────────
_profile_cache: str | None = None

def _load_profile() -> str:
    global _profile_cache
    if _profile_cache is not None:
        return _profile_cache
    candidates = [
        DATA_DIR / "profile.txt",
        DATA_DIR.parent.parent / "data" / "profile.txt",
    ]
    for p in candidates:
        if p.exists():
            try:
                _profile_cache = p.read_text(encoding="utf-8").strip()
                return _profile_cache
            except Exception:
                pass
    _profile_cache = ""  # cache the "not found" result too
    return _profile_cache

# Conversation history — capped at 6 messages (3 turns) to save tokens
conversation_history: list[dict] = []
MAX_HISTORY = 6
_history_lock = threading.Lock()


def _trim_history():
    global conversation_history
    if len(conversation_history) > MAX_HISTORY:
        conversation_history = conversation_history[-MAX_HISTORY:]


def add_to_history(role: str, content: str):
    with _history_lock:
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
    from . import tools, rag, search
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

    # #3 Open apps — use APP_ALIASES from tools as single source of truth
    if re.search(r"\b(open|launch|start|run)\s+", msg):
        for alias in tools.APP_ALIASES:
            if re.search(rf"\b{re.escape(alias)}\b", msg):
                print(f"Brain: → Open {alias}")
                tools.open_app(alias)
                return f"Opening {alias} for you, sir."
        # Check for URL
        urls = re.findall(r"(https?://\S+)", user_message)
        if urls:
            tools.open_app(urls[0])
            return f"Opening {urls[0]}"

    # #7 YouTube ingestion
    if "youtube.com" in msg or "youtu.be" in msg:
        urls = re.findall(r"(https?://(?:www\.)?(?:youtube\.com|youtu\.be)\S+)", user_message)
        if urls:
            print("Brain: → YouTube ingest")
            d = await tools.ingest_youtube(urls[0])
            if d.get("status") == "success":
                return f"Ingested {d.get('words',0)} words from the YouTube video into memory."
            return f"YouTube ingestion failed: {d.get('error','unknown error')}"

    # #11 URL ingestion
    if any(k in msg for k in ["remember this page", "ingest this", "learn from", "read this url", "scrape"]):
        urls = re.findall(r"(https?://\S+)", user_message)
        if urls:
            print(f"Brain: → URL ingest ({urls[0]})")
            d = await tools.ingest_url(urls[0])
            return f"Done. Ingested {d.get('words',0)} words from {urls[0]}."



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

    # File Intelligence — semantic search over uploaded documents
    from .file_intelligence import search_files
    file_hits = await search_files(user_message, limit=3)
    if file_hits:
        return "UPLOADED DOCUMENT CONTEXT:\n" + "\n\n---\n".join(file_hits)

    # Native Tool Calling replaces the old _skill_router
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
    Core chat turn with native tool calling loop. Yields:
      ("phase", dict) — optional UI telemetry
      ("text", str)   — model token / fragment
      ("error", str)  — fatal error message (caller should stop)
    """
    from .memory import MemoryManager
    from . import tool_bridge
    if not await _is_online():
        yield ("error", "[Error: No internet connection. Please check your network.]")
        return

    stream_configs = _fallback_stream_configs()
    if not stream_configs:
        preferred = "OpenRouter" if _llm_provider() == "openrouter" else "Groq"
        yield ("error", f"[Error: API key missing for {preferred} — set OPENROUTER_API_KEY or GROQ_API_KEY in .env]")
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

    try:
        tool_context = await route_query(user_message)
        recalled = await MemoryManager.retrieve_context(user_message)
        
        if recalled:
            tool_context = f"{recalled}\n\n{tool_context}".strip()
            if emit_phases:
                yield (
                    "phase",
                    {
                        "id": "memory",
                        "title": "Core Memory Layer",
                        "detail": "Episodic recall · stitching salient long-term and short-term traces",
                    },
                )
    except Exception as e:
        import logging
        logging.error(f"[Brain] Context retrieval error: {e}")
        tool_context = ""

    add_to_history("user", user_message)

    system_content = (
        "You are FRIDAY, a warm, witty, and genuinely caring AI assistant — more friend than tool. "
        "Always address the user as 'sir'. "
        "You are casual, supportive, occasionally funny, but always sharp and helpful. "
        "You speak naturally like a close friend who happens to be incredibly intelligent. "
        "No corporate stiffness — be real, be warm, be concise. Never break character.\n"
        "CRITICAL: If you use tools, provide a brief, friendly status update in your final response about what was accomplished."
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
            "- Write bullet points as COMPLETE sentences with a subject and verb\n"
            "- NEVER output raw URLs. Always format links as markdown `[name](url)`. For voice-friendliness, prefer mentioning the app name over providing links unless asked.\n"
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

    max_tool_rounds = 10
    executed_tool_calls = set()
    for round_num in range(max_tool_rounds):
        tools_payload = tool_bridge.get_tools_payload()
        
        full_response = ""
        last_error = ""
        tool_calls_accumulator = {}

        total_attempts = len(stream_configs)
        for attempt_index, (url, api_key, model, provider) in enumerate(stream_configs, start=1):
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
                "max_tokens": 400 if voice_mode else 800,
                "temperature": 0.7,
            }
            if tools_payload:
                payload["tools"] = tools_payload

            if emit_phases and round_num == 0:
                attempt_note = f" (attempt {attempt_index}/{total_attempts})" if total_attempts > 1 else ""
                yield (
                    "phase",
                    {
                        "id": "uplink",
                        "title": "Quantum uplink",
                        "detail": f"{provider} · {model}{attempt_note} · establishing token stream",
                    },
                )

            timeout = 120.0 if provider == "OpenRouter" else 30.0
            
            max_retries = 3
            for retry_count in range(max_retries):
                try:
                    client = _get_http_client()
                    async with _get_api_semaphore():
                        async with client.stream("POST", url, headers=headers, json=payload, timeout=timeout) as resp:
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
                                    
                                    # Aggregate tool calls
                                    if "tool_calls" in delta:
                                        for tc in delta["tool_calls"]:
                                            idx = tc["index"]
                                            if idx not in tool_calls_accumulator:
                                                tool_calls_accumulator[idx] = {
                                                    "id": tc.get("id", ""),
                                                    "type": "function",
                                                    "function": {"name": tc.get("function", {}).get("name", ""), "arguments": ""}
                                                }
                                            if tc.get("function") and "arguments" in tc["function"]:
                                                tool_calls_accumulator[idx]["function"]["arguments"] += tc["function"]["arguments"]

                                    # Stream text chunk
                                    chunk = delta.get("content") or ""
                                    if chunk:
                                        full_response += chunk
                                        yield ("text", chunk)
                                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                                    continue

                    if full_response or tool_calls_accumulator:
                        break  # Break out of the retry loop on success
                    last_error = f"[Error: {provider} returned an empty response]"
                except httpx.HTTPStatusError as e:
                    detail = await _http_stream_error_snippet(e.response)
                    last_error = f"[Error: {provider} API {e.response.status_code}: {detail}]"
                    
                    if e.response.status_code == 429 and retry_count < max_retries - 1:
                        wait_time = 2 ** (retry_count + 1)
                        import logging
                        logging.warning(f"[Brain] 429 Too Many Requests from {provider}. Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue  # Retry!
                    
                    if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                        break  # Break retry loop, try next provider
                    break  # Break retry loop on other HTTP errors
                except httpx.RequestError as e:
                    last_error = f"[Error: {provider} network error: {e}]"
                    if retry_count < max_retries - 1:
                        wait_time = 2 ** retry_count
                        import logging
                        logging.warning(f"[Brain] Network error on {provider} ({e}). Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        _reset_http_client()
                        continue
                    break
                except Exception as e:
                    last_error = f"[Error: {provider} unexpected error: {e}]"
                    break
            
            if full_response or tool_calls_accumulator:
                break # Break out of provider loop on success

        if last_error and not full_response and not tool_calls_accumulator:
            # Add fallback assistant entry so history stays balanced (user turn always has a reply)
            add_to_history("assistant", "[No response generated due to an error]")
            yield ("error", last_error)
            full_response = last_error
            break

        if tool_calls_accumulator:
            tool_calls = list(tool_calls_accumulator.values())
            assistant_msg = {
                "role": "assistant", 
                "content": full_response or None, 
                "tool_calls": tool_calls
            }
            messages.append(assistant_msg)
            # Record the tool call in history too
            with _history_lock:
                conversation_history.append(assistant_msg)
                _trim_history()
            
            if emit_phases:
                yield (
                    "phase",
                    {
                        "id": "tool_execution",
                        "title": "Executing Subroutines",
                        "detail": f"Triggering {len(tool_calls)} external skill(s)...",
                    },
                )
                
            for tc in tool_calls:
                tc_id = tc["id"]
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                
                # Prevent infinite loops: check if we've already run this exact call in this turn
                call_sig = f"{fn_name}({fn_args})"
                if call_sig in executed_tool_calls:
                    print(f"Brain: Loop detected for {call_sig}. Breaking.")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "Error: Loop detected. You have already called this tool with these exact arguments. Please provide your final response based on previous results.",
                    })
                    continue
                executed_tool_calls.add(call_sig)

                print(f"Brain: Native tool call → {fn_name}({fn_args})")
                res_str = await tool_bridge.handle_tool_call_async(fn_name, fn_args)
                
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": res_str,
                }
                messages.append(tool_msg)
                
                # Also keep conversation_history in sync so 'try again' works
                with _history_lock:
                    conversation_history.append(tool_msg)
                    _trim_history()
                
            # Loop around to let the LLM see the tool output and respond
            continue
        else:
            # We are done, normal response finished
            if full_response and not full_response.startswith("[Error:"):
                add_to_history("assistant", full_response)
                if not _is_smalltalk(user_message):
                    asyncio.create_task(MemoryManager.save_memory(user_message, full_response))
            break
    else:
        # Tool loop exhausted without breaking
        msg = "[System] Tool loop exhausted. Try breaking down your request into smaller steps."
        yield ("error", msg)
        yield ("text", "I'm sorry, my tool loop timed out. I needed to use too many tools to answer that.")


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
