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

conversation_histories: dict[str, list[dict]] = {}
MAX_HISTORY = 30
_history_lock = asyncio.Lock()

_PROFILE_CACHE: str | None = None

_SMALLTALK_PATTERNS = [
    "hai", "hi", "hello", "hey", "sup", "yo", "howdy",
    "how are you", "how's it going", "what's up", "whats up",
    "good morning", "good evening", "good night", "gn", "bye",
    "ok", "okay", "cool", "thanks", "thank you", "lol", "haha",
    "nice", "great", "got it", "sounds good", "sure", "yep", "nope",
    "thank", "thanks friday", "thanks helper", "gm", "ge", "hello there",
    "testing", "test", "hi friday", "hey friday", "hello friday"
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


async def _get_context(user_message: str, session_id: str = "default-session") -> str:
    from . import rag
    parts = []
    try:
        rag_result = rag.search_personal_data(user_message)
        if rag_result and rag_result.strip():
            parts.append(f"Personal data context:\n{rag_result}")
    except Exception as e:
        logger.debug(f"RAG search error: {e}")

    try:
        from .memory import chat_history
        session_files = await chat_history.get_session_files(session_id)
        if session_files:
            from .file_intelligence import search_files, get_file_preview
            file_hits = await search_files(user_message, filenames=session_files, limit=3)
            if not file_hits:
                file_hits = await get_file_preview(session_files, limit=3)
            if file_hits:
                parts.append("UPLOADED DOCUMENT CONTEXT:\n" + "\n\n---\n".join(file_hits))
    except Exception as e:
        logger.debug(f"File search error: {e}")

    return "\n\n".join(parts)


async def _run_tool_with_progress(fn_name: str, fn_args: str, emit_phases: bool):
    task = asyncio.create_task(tool_bridge.handle_tool_call_async(fn_name, fn_args))
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=15.0)
        except asyncio.TimeoutError:
            if emit_phases:
                yield (
                    "phase",
                    {
                        "id": "tool_progress",
                        "title": "Still working...",
                        "detail": f"Processing subroutine {fn_name}...",
                    },
                )
    res_str = await task
    yield ("result", res_str)


async def _iter_chat_turn(user_message: str, session_id: str, voice_mode: bool, emit_phases: bool):
    from .memory import MemoryManager
    from .events import event_bus
    from .memory.tool_memory import tool_memory
    from .memory import chat_history

    if not session_id:
        session_id = "default-session"

    if emit_phases:
        await event_bus.emit("thinking_started", {"message": user_message})
        yield (
            "phase",
            {
                "id": "ingress",
                "title": "Neural ingress",
                "detail": "Decomposing lexical intent",
            },
        )

    try:
        passive_context = ""
        try:
            passive_context = await _get_context(user_message, session_id)
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

        # Load from DB if in-memory history is empty
        async with _history_lock:
            if session_id not in conversation_histories:
                conversation_histories[session_id] = []
                try:
                    db_history = await chat_history.get_latest_chat_messages(session_id, limit=16)
                    conversation_histories[session_id].extend(db_history)
                except Exception as e:
                    logger.error(f"Error loading chat history from DB: {e}")

            session_history = conversation_histories[session_id]

        session_history.append({"role": "user", "content": user_message})
        try:
            await chat_history.save_chat_message(session_id, "user", user_message)
        except Exception as e:
            logger.error(f"Error saving user message to DB: {e}")

        system_content = (
            "You are FRIDAY, a warm, witty, and genuinely caring AI assistant. "
            "Always address the user as 'sir'. "
            "You are casual, supportive, occasionally funny, but always sharp and helpful. "
            "You speak naturally like a close friend who happens to be incredibly intelligent. "
            "No corporate stiffness. Never break character.\n"
            "CRITICAL: If the user asks who created, built, developed, or made you (or similar queries), "
            "you MUST state that you were built and created by Saheer Khan MK (or Saheer).\n"
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

        messages = [{"role": "system", "content": system_content}, *session_history]

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

        skip_tool_loop = False
        is_planner_request = any(k in user_message.lower() for k in ["plan:", "step by step", "multi-step", "decompose", "planner"])
        if is_planner_request:
            if emit_phases:
                yield (
                    "phase",
                    {
                        "id": "planner_decomposing",
                        "title": "Planner Engine",
                        "detail": "Decomposing task into logical steps...",
                    },
                )
            
            from .planner.engine import planner
            tools_payload = tool_bridge.get_tools_payload()
            try:
                steps = await planner.decompose(user_message, tools_payload)
                for idx, step in enumerate(steps):
                    if emit_phases:
                        yield (
                            "phase",
                            {
                                "id": f"plan_step_{step.id}",
                                "title": f"Plan Step {idx+1}/{len(steps)}",
                                "detail": f"{step.reasoning} (Tool: {step.tool or 'None'})",
                            },
                        )
                    
                    if step.tool:
                        try:
                            t0 = time.monotonic()
                            res_str = ""
                            async for event_type, val in _run_tool_with_progress(step.tool, json.dumps(step.args), emit_phases):
                                if event_type == "phase":
                                    yield (event_type, val)
                                elif event_type == "result":
                                    res_str = val
                            duration = (time.monotonic() - t0) * 1000
                            
                            step.status = "completed"
                            step.result = res_str
                            
                            await event_bus.emit("tool_called", {"tool": step.tool, "args": json.dumps(step.args), "duration_ms": duration})
                            await event_bus.emit("tool_finished", {"tool": step.tool, "success": True})
                            
                        except Exception as e:
                            step.status = "failed"
                            step.error = str(e)
                            await event_bus.emit("tool_finished", {"tool": step.tool, "success": False})
                    else:
                        step.status = "completed"
                        
                steps_summary = []
                for idx, step in enumerate(steps):
                    status_str = "Succeeded" if step.status == "completed" else "Failed"
                    res_preview = str(step.result)[:500] + "..." if step.result else str(step.error)
                    steps_summary.append(
                        f"Step {idx+1}: {step.reasoning}\n"
                        f"Tool: {step.tool}\n"
                        f"Status: {status_str}\n"
                        f"Result: {res_preview}"
                    )
                
                summary_content = "\n\n".join(steps_summary)
                system_content += f"\n\nPLANNER STEPS COMPLETED:\n{summary_content}"
                messages = [{"role": "system", "content": system_content}, *session_history]
                skip_tool_loop = True
            except Exception as e:
                logger.error(f"Planner failed: {e}")

        for round_num in range(max_tool_rounds):
            if time.monotonic() - turn_start > turn_timeout:
                yield ("error", "[System] Tool execution timed out.")
                yield ("text", "I'm sorry, that took too long.")
                session_history.append({"role": "assistant", "content": "[Response timed out]"})
                break

            tools_payload = tool_bridge.get_tools_payload() if not skip_tool_loop else []
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
                session_history.append({"role": "assistant", "content": msg})
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
                session_history.append(assistant_msg)

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
                    res_str = ""
                    async for event_type, val in _run_tool_with_progress(fn_name, fn_args, emit_phases):
                        if event_type == "phase":
                            yield (event_type, val)
                        elif event_type == "result":
                            res_str = val
                    duration = (time.monotonic() - t0) * 1000

                    is_failure = res_str.startswith("[Error:") or '"status": "failed"' in res_str
                    tool_memory.record_result(
                        tool=fn_name, inputs={"args": fn_args},
                        outputs=res_str, success=not is_failure,
                        duration_ms=duration,
                    )
                    await event_bus.emit("tool_called", {"tool": fn_name, "args": fn_args, "duration_ms": duration})

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
                    session_history.append({"role": "tool", "tool_call_id": tc_id, "content": res_str})

                    await event_bus.emit("tool_finished", {"tool": fn_name, "success": not is_failure})

                continue
            else:
                if full_response and not full_response.startswith("[Error:"):
                    session_history.append({"role": "assistant", "content": full_response})
                    try:
                        await chat_history.save_chat_message(session_id, "assistant", full_response)
                    except Exception as e:
                        logger.error(f"Error saving assistant message to DB: {e}")
                    if not _is_smalltalk(user_message):
                        asyncio.create_task(MemoryManager.save_memory(user_message, full_response))
                        await event_bus.emit("memory_saved", {"user": user_message[:100]})
                break
        else:
            yield ("error", "[System] Tool loop exhausted.")
            yield ("text", "I'm sorry, I used too many tools.")
    finally:
        session_history[:] = session_history[-MAX_HISTORY:]


async def iter_chat_sse_events(user_message: str, session_id: str = "default-session", voice_mode: bool = False):
    async for kind, payload in _iter_chat_turn(user_message, session_id, voice_mode, emit_phases=True):
        if kind == "phase":
            yield {"type": "phase", **payload}
        elif kind == "text":
            yield {"type": "token", "text": payload}
        elif kind == "error":
            yield {"type": "error", "message": payload}


async def stream_response(user_message: str, session_id: str = "default-session", voice_mode: bool = False):
    async for kind, payload in _iter_chat_turn(user_message, session_id, voice_mode, emit_phases=False):
        if kind == "text":
            yield payload
        elif kind == "error":
            yield payload
