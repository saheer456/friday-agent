"""
brain.py — Streaming chat backend for FRIDAY.

Uses the Provider Abstraction Layer (backend/providers) for LLM calls.
Emits events through the Streaming Event Bus (backend/events).
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path

from .memory import MemoryManager
from . import tool_bridge
from .providers import provider_manager

logger = logging.getLogger("Brain")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

conversation_history: list[dict] = []
MAX_HISTORY = 6
_history_lock = asyncio.Lock()

_PROFILE_CACHE: str | None = None

_SMALLTALK_PATTERNS = [
    "hai", "hi", "hello", "hey", "sup", "yo", "howdy",
    "how are you", "how's it going", "what's up", "whats up",
    "good morning", "good evening", "good night", "gn", "bye",
    "ok", "okay", "cool", "thanks", "thank you", "lol", "haha",
    "nice", "great", "got it", "sounds good", "sure", "yep", "nope",
]


def _load_profile() -> str:
    global _PROFILE_CACHE
    if _PROFILE_CACHE is not None:
        return _PROFILE_CACHE
    candidates = [
        DATA_DIR / "profile.txt",
        DATA_DIR.parent.parent / "data" / "profile.txt",
    ]
    for p in candidates:
        if p.exists():
            try:
                _PROFILE_CACHE = p.read_text(encoding="utf-8").strip()
                return _PROFILE_CACHE
            except Exception:
                pass
    _PROFILE_CACHE = ""
    return _PROFILE_CACHE


def _is_smalltalk(msg: str) -> bool:
    stripped = msg.strip().lower().rstrip("!?.")
    if stripped in _SMALLTALK_PATTERNS:
        return True
    if len(stripped.split()) <= 4:
        return any(stripped.startswith(p) for p in _SMALLTALK_PATTERNS)
    return False


async def _get_context(user_message: str) -> str:
    from . import rag
    parts = []
    try:
        rag_result = rag.search_personal_data(user_message)
        if rag_result and rag_result.strip():
            parts.append(f"Personal data context:\n{rag_result}")
    except Exception as e:
        logger.debug(f"RAG search error: {e}")

    try:
        from .file_intelligence import search_files
        file_hits = await search_files(user_message, limit=3)
        if file_hits:
            parts.append("UPLOADED DOCUMENT CONTEXT:\n" + "\n\n---\n".join(file_hits))
    except Exception as e:
        logger.debug(f"File search error: {e}")

    return "\n\n".join(parts)


async def _iter_chat_turn(user_message: str, voice_mode: bool, emit_phases: bool):
    from .memory import MemoryManager
    from .events import event_bus
    from .memory.tool_memory import tool_memory

    if emit_phases:
        event_bus.emit("thinking_started", {"message": user_message})
        yield (
            "phase",
            {
                "id": "ingress",
                "title": "Neural ingress",
                "detail": "Decomposing lexical intent",
            },
        )

    passive_context = ""
    try:
        passive_context = await _get_context(user_message)
        recalled = await MemoryManager.retrieve_context(user_message)
        if recalled:
            passive_context = f"{recalled}\n\n{passive_context}".strip()
            if emit_phases:
                yield (
                    "phase",
                    {
                        "id": "memory",
                        "title": "Core Memory Layer",
                        "detail": "Episodic recall",
                    },
                )
    except Exception as e:
        logger.error(f"Context retrieval error: {e}")
        passive_context = ""

    conversation_history.append({"role": "user", "content": user_message})

    system_content = (
        "You are FRIDAY, a warm, witty, and genuinely caring AI assistant. "
        "Always address the user as 'sir'. "
        "You are casual, supportive, occasionally funny, but always sharp and helpful. "
        "You speak naturally like a close friend who happens to be incredibly intelligent. "
        "No corporate stiffness. Never break character.\n"
        "CRITICAL: If you use tools, provide a brief, friendly status update in your final response about what was accomplished.\n"
        "CRITICAL: NEVER fabricate data. If the user asks for real-time information "
        "you MUST call the appropriate tool. Do not generate placeholder data.\n"
        "TOOLS: weather, web_search, clipboard, screenshot, youtube, web_scrape, app_launcher, code, terminal, "
        "gmail (read_inbox, send_email), gcalendar, gdocs, gsheets.\n"
        "IMPORTANT: NEVER say you don't have access to something without first trying the relevant tool."
    )

    _profile = _load_profile()
    if _profile:
        system_content += f"\n\nSIR'S PROFILE:\n{_profile}"

    if voice_mode:
        system_content += (
            "\n\nOUTPUT CHANNEL: VOICE. Keep your answer to 1-3 short, conversational sentences. "
            "NO markdown, NO bullet points, NO lists, NO code blocks, NO headers."
        )
    else:
        system_content += (
            "\n\nOUTPUT CHANNEL: WEB CHAT. Format with Markdown. "
            "Write bullet points as complete sentences. "
            "NEVER output raw URLs. "
            "Never use the '**Term**: description' pattern. "
        )
    if passive_context:
        system_content += f"\n\nCONTEXT:\n{passive_context}"

    messages = [{"role": "system", "content": system_content}, *conversation_history]

    if emit_phases:
        yield (
            "phase",
            {
                "id": "lattice",
                "title": "Context lattice",
                "detail": f"{len(messages)} message tensors",
            },
        )

    max_tool_rounds = 10
    max_total_tool_calls = 15
    max_tool_result_chars = 4000
    turn_timeout = 60.0
    turn_start = time.monotonic()
    executed_tool_calls = set()
    tool_call_count = 0
    consecutive_failures = 0
    tool_name_counts: dict[str, int] = {}

    for round_num in range(max_tool_rounds):
        if time.monotonic() - turn_start > turn_timeout:
            yield ("error", "[System] Tool execution timed out.")
            yield ("text", "I'm sorry, that took too long.")
            conversation_history.append({"role": "assistant", "content": "[Response timed out]"})
            break

        tools_payload = tool_bridge.get_tools_payload()
        full_response = ""
        last_error = ""
        tool_calls_accumulator = {}

        if tools_payload and emit_phases and round_num == 0:
            yield (
                "phase",
                {
                    "id": "uplink",
                    "title": "Quantum uplink",
                    "detail": "Establishing token stream",
                },
            )

        try:
            async for event in provider_manager.stream(
                messages, tools=tools_payload,
                is_heavy=any(k in user_message.lower() for k in [
                    "reason", "think", "complex", "deep", "analyze", "analyse",
                    "long", "large", "big", "extensive", "detailed",
                    "code", "script", "program", "develop", "build"]),
                voice_mode=voice_mode,
            ):
                if event.get("type") == "error":
                    last_error = f"[Error: {event['error']}]"
                elif event.get("type") == "text":
                    chunk = event.get("text", "")
                    if chunk:
                        full_response += chunk
                        yield ("text", chunk)
                elif event.get("type") == "tool_call":
                    idx = event["index"]
                    if idx not in tool_calls_accumulator:
                        fn = event.get("delta", {}).get("function", {})
                        tool_calls_accumulator[idx] = {
                            "id": event.get("delta", {}).get("id", ""),
                            "type": "function",
                            "function": {"name": fn.get("name", ""), "arguments": ""},
                        }
                    delta_fn = event.get("delta", {}).get("function", {})
                    if "arguments" in delta_fn:
                        tool_calls_accumulator[idx]["function"]["arguments"] += delta_fn["arguments"]
                elif event.get("type") == "done":
                    break
        except Exception as e:
            last_error = f"[Error: {e}]"
            logger.error(f"Provider stream failed: {e}")

        if last_error and not full_response and not tool_calls_accumulator:
            msg = "I encountered a temporary issue. Please try again."
            conversation_history.append({"role": "assistant", "content": msg})
            if emit_phases:
                yield ("phase", {"id": "fault", "title": "Subsystem fault", "detail": last_error})
            yield ("error", msg)
            full_response = msg
            break

        if tool_calls_accumulator:
            tool_calls = list(tool_calls_accumulator.values())
            assistant_msg = {
                "role": "assistant",
                "content": full_response or None,
                "tool_calls": tool_calls,
            }
            messages.append(assistant_msg)
            conversation_history.append(assistant_msg)
            conversation_history[:] = conversation_history[-MAX_HISTORY:]

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

                tool_call_count += 1
                if tool_call_count > max_total_tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "Error: Too many tool calls.",
                    })
                    continue

                tool_name_counts[fn_name] = tool_name_counts.get(fn_name, 0) + 1
                if tool_name_counts[fn_name] > 3:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Error: {fn_name} called too many times.",
                    })
                    continue

                call_sig = f"{fn_name}({fn_args})"
                if call_sig in executed_tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "Error: Loop detected.",
                    })
                    continue
                executed_tool_calls.add(call_sig)

                try:
                    json.loads(fn_args) if isinstance(fn_args, str) else fn_args
                except (json.JSONDecodeError, TypeError):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"Error: Invalid JSON arguments for {fn_name}.",
                    })
                    consecutive_failures += 1
                    continue

                t0 = time.monotonic()
                res_str = await tool_bridge.handle_tool_call_async(fn_name, fn_args)
                duration = (time.monotonic() - t0) * 1000

                is_failure = res_str.startswith("[Error:") or '"status": "failed"' in res_str
                tool_memory.record_result(
                    tool=fn_name, inputs={"args": fn_args},
                    outputs=res_str, success=not is_failure,
                    duration_ms=duration,
                )
                event_bus.emit("tool_called", {"tool": fn_name, "args": fn_args, "duration_ms": duration})

                if len(res_str) > max_tool_result_chars:
                    res_str = res_str[:max_tool_result_chars] + "\n\n... [truncated]"

                if is_failure:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0

                if consecutive_failures >= 3:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "Error: Multiple tool calls failed. Provide a direct answer.",
                    })
                    continue

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": res_str,
                })
                conversation_history.append({"role": "tool", "tool_call_id": tc_id, "content": res_str})
                conversation_history[:] = conversation_history[-MAX_HISTORY:]

                event_bus.emit("tool_finished", {"tool": fn_name, "success": not is_failure})

            continue
        else:
            if full_response and not full_response.startswith("[Error:"):
                conversation_history.append({"role": "assistant", "content": full_response})
                conversation_history[:] = conversation_history[-MAX_HISTORY:]
                if not _is_smalltalk(user_message):
                    asyncio.create_task(MemoryManager.save_memory(user_message, full_response))
                    event_bus.emit("memory_saved", {"user": user_message[:100]})
            break
    else:
        yield ("error", "[System] Tool loop exhausted.")
        yield ("text", "I'm sorry, I used too many tools.")


async def iter_chat_sse_events(user_message: str, voice_mode: bool = False):
    async for kind, payload in _iter_chat_turn(user_message, voice_mode, emit_phases=True):
        if kind == "phase":
            yield {"type": "phase", **payload}
        elif kind == "text":
            yield {"type": "token", "text": payload}
        elif kind == "error":
            yield {"type": "error", "message": payload}


async def stream_response(user_message: str, voice_mode: bool = False):
    async for kind, payload in _iter_chat_turn(user_message, voice_mode, emit_phases=False):
        if kind == "text":
            yield payload
        elif kind == "error":
            yield payload
