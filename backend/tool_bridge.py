"""
tool_bridge.py — Connects the Skills Framework to the LLM
==========================================================
Intercepts tool_call responses from the Groq/OpenAI API,
routes them through the SkillManager, and feeds results back
into the conversation as tool messages.

Used by brain.py in the streaming chat loop.
"""
from __future__ import annotations

import json
import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

from .skills import skill_manager
from .skills.code_skill     import CodeSkill
from .skills.terminal_skill import TerminalSkill
from .skills.google_auth    import is_google_configured


# ── One-time skill registration at import time ─────────────────────────────────

def _register_default_skills() -> None:
    """Register all built-in skills with their default (no-config) settings."""
    # Core dev skills (always available)
    if not skill_manager.get("code"):
        skill_manager.register(CodeSkill())
    if not skill_manager.get("terminal"):
        skill_manager.register(TerminalSkill())

    # Google Workspace skills (only if credentials exist)
    if is_google_configured():
        from .skills.gcalendar_skill import GCalendarSkill
        from .skills.gmail_skill     import GmailSkill
        from .skills.gdocs_skill     import GDocsSkill
        from .skills.gsheets_skill   import GSheetsSkill

        if not skill_manager.get("gcalendar"):
            skill_manager.register(GCalendarSkill())
        if not skill_manager.get("gmail"):
            skill_manager.register(GmailSkill())
        if not skill_manager.get("gdocs"):
            skill_manager.register(GDocsSkill())
        if not skill_manager.get("gsheets"):
            skill_manager.register(GSheetsSkill())
        print("[Skills] ✓ Google Workspace skills loaded (Calendar, Gmail, Docs, Sheets)")
    else:
        print("[Skills] ⚠ Google credentials not found — Google skills disabled")
        print("[Skills]   → Download from Google Cloud Console and save as data/google_credentials.json")


_register_default_skills()


# ── Schema injection helper ────────────────────────────────────────────────────

def get_tools_payload() -> Optional[List[Dict]]:
    """
    Returns the tools= list to pass to the LLM, or None if no skills are active.
    Call this when building the API request payload in brain.py.
    """
    schemas = skill_manager.get_tool_schemas()
    return schemas if schemas else None


# ── Tool call dispatcher ───────────────────────────────────────────────────────

import logging
logger = logging.getLogger("ToolBridge")

def handle_tool_call(tool_name: str, tool_args_json: str) -> str:
    """
    Synchronous dispatcher.
    Call this when the LLM response contains a tool_call.
    Returns a string ready to insert as a {"role": "tool"} message.
    """
    try:
        args = json.loads(tool_args_json) if tool_args_json else {}
    except json.JSONDecodeError:
        args = {}

    try:
        result = skill_manager.dispatch(tool_name, args)
        return result.to_tool_message()
    except Exception as e:
        logger.error(f"Tool execution failed for {tool_name}: {e}")
        return f"Error executing tool {tool_name}: {e}"



async def handle_tool_call_async(tool_name: str, tool_args_json: str) -> str:
    """Async-safe wrapper — runs the synchronous dispatch in the executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, handle_tool_call, tool_name, tool_args_json
    )
