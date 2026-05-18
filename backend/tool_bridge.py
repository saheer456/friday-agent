"""
tool_bridge.py — Connects the Skills Framework to the LLM
==========================================================
Intercepts tool_call responses from the LLM provider,
routes them through the SkillManager with permission validation,
and feeds results back into the conversation as tool messages.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

from .skills import skill_manager
from .skills.code_skill     import CodeSkill
from .skills.terminal_skill import TerminalSkill
from .skills.google_auth    import is_google_configured
from .security import permission_manager
from .events import event_bus

logger = logging.getLogger("ToolBridge")


# ── One-time skill registration at import time ─────────────────────────────────

def _register_default_skills() -> None:
    """Register all built-in skills with their default (no-config) settings."""
    if not skill_manager.get("code"):
        skill_manager.register(CodeSkill())
    if not skill_manager.get("terminal"):
        skill_manager.register(TerminalSkill())

    from .skills.weather_skill      import WeatherSkill
    from .skills.web_search_skill   import WebSearchSkill
    from .skills.clipboard_skill    import ClipboardSkill
    from .skills.screenshot_skill   import ScreenshotSkill
    from .skills.youtube_skill      import YouTubeSkill
    from .skills.web_scrape_skill   import WebScrapeSkill
    from .skills.app_launcher_skill import AppLauncherSkill

    for skill_cls in [WeatherSkill, WebSearchSkill, ClipboardSkill,
                      ScreenshotSkill, YouTubeSkill, WebScrapeSkill, AppLauncherSkill]:
        name = skill_cls.name if hasattr(skill_cls, 'name') else skill_cls.__name__.lower().replace("skill", "")
        if not skill_manager.get(name):
            skill_manager.register(skill_cls())

    if is_google_configured():
        from .skills.gcalendar_skill import GCalendarSkill
        from .skills.gmail_skill     import GmailSkill
        from .skills.gdocs_skill     import GDocsSkill
        from .skills.gsheets_skill   import GSheetsSkill

        for skill_cls in [GCalendarSkill, GmailSkill, GDocsSkill, GSheetsSkill]:
            name = skill_cls.name if hasattr(skill_cls, 'name') else skill_cls.__name__.lower().replace("skill", "")
            if not skill_manager.get(name):
                skill_manager.register(skill_cls())
        logger.info("Google Workspace skills loaded")
    else:
        logger.info("Google credentials not found — Google skills disabled")


_register_default_skills()


def get_tools_payload() -> Optional[List[Dict]]:
    schemas = skill_manager.get_tool_schemas()
    return schemas if schemas else None


def handle_tool_call(tool_name: str, tool_args_json: str) -> str:
    try:
        args = json.loads(tool_args_json) if tool_args_json else {}
    except json.JSONDecodeError:
        args = {}

    try:
        result = skill_manager.dispatch(tool_name, args)
        return result.to_tool_message()
    except Exception as e:
        logger.error("Tool execution failed for %s: %s", tool_name, e)
        return f"Error executing tool {tool_name}: {e}"


async def handle_tool_call_async(tool_name: str, tool_args_json: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, handle_tool_call, tool_name, tool_args_json
    )
