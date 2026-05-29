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


def get_tools_payload(user_message: Optional[str] = None) -> Optional[List[Dict]]:
    schemas = skill_manager.get_tool_schemas()
    if not schemas:
        return None
    if not user_message:
        return schemas

    import re
    lowered = user_message.lower()

    categories = {
        "weather": ["weather", "forecast", "temp", "degree", "rain", "snow", "cloudy", "wind", "humidity"],
        "web_search": ["search", "find", "google", "web", "online", "news", "look up"],
        "web_scrape": ["scrape", "web_scrape", "read page", "website content"],
        "youtube": ["youtube", "video", "transcript"],
        "code": ["code", "python", "script", "program", "developer", "coding", "bug", "debug", "compile"],
        "terminal": ["terminal", "bash", "cmd", "command", "run", "execute", "directory", "folder", "list", "file", "read", "write", "create"],
        "clipboard": ["clipboard", "copy", "paste"],
        "screenshot": ["screenshot", "screen", "capture", "image", "view"],
        "app_launcher": ["launch", "open", "start", "app", "application", "chrome", "edge", "spotify", "discord", "slack"],
        "gmail": ["email", "mail", "inbox", "gmail", "send"],
        "gcalendar": ["calendar", "event", "schedule", "meeting", "date", "appoint"],
        "gdocs": ["doc", "document", "google doc", "write doc"],
        "gsheets": ["sheet", "spreadsheet", "excel", "csv", "rows", "cell"]
    }

    matched_prefixes = set()
    for category_name, keywords in categories.items():
        for keyword in keywords:
            pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, lowered):
                matched_prefixes.add(category_name)
                break

    if "web_search" in matched_prefixes:
        matched_prefixes.add("web_scrape")
        matched_prefixes.add("youtube")

    if "code" in matched_prefixes:
        matched_prefixes.add("terminal")
        matched_prefixes.add("clipboard")

    def tool_matches(tool_name: str, active_categories: set[str]) -> bool:
        if tool_name.startswith("weather_") and "weather" in active_categories:
            return True
        if tool_name.startswith("web_search_") and "web_search" in active_categories:
            return True
        if tool_name.startswith("web_scrape_") and "web_scrape" in active_categories:
            return True
        if tool_name.startswith("youtube_") and "youtube" in active_categories:
            return True
        if tool_name.startswith("code_") and "code" in active_categories:
            return True
        if tool_name.startswith("terminal_") and "terminal" in active_categories:
            return True
        if tool_name.startswith("clipboard_") and "clipboard" in active_categories:
            return True
        if tool_name.startswith("screenshot_") and "screenshot" in active_categories:
            return True
        if tool_name.startswith("app_launcher_") and "app_launcher" in active_categories:
            return True
        if tool_name.startswith("gmail_") and "gmail" in active_categories:
            return True
        if tool_name.startswith("gcalendar_") and "gcalendar" in active_categories:
            return True
        if tool_name.startswith("gdocs_") and "gdocs" in active_categories:
            return True
        if tool_name.startswith("gsheets_") and "gsheets" in active_categories:
            return True
        return False

    if not matched_prefixes:
        # Core categories fallback
        core_categories = {"code", "terminal", "weather", "web_search", "app_launcher"}
        return [t for t in schemas if tool_matches(t["function"]["name"], core_categories)]

    filtered = [t for t in schemas if tool_matches(t["function"]["name"], matched_prefixes)]
    return filtered if filtered else schemas


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
    try:
        args = json.loads(tool_args_json) if tool_args_json else {}
    except json.JSONDecodeError:
        args = {}

    try:
        result = await skill_manager.dispatch_async(tool_name, args)
        return result.to_tool_message()
    except Exception as e:
        logger.error("Tool execution failed for %s: %s", tool_name, e)
        return f"Error executing tool {tool_name}: {e}"
