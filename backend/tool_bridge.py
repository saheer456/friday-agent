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
from typing import Any, AsyncGenerator, Dict, List, Optional

from pydantic import BaseModel, ValidationError, create_model

from .skills import skill_manager
from .skills.code_skill     import CodeSkill
from .skills.terminal_skill import TerminalSkill
from .skills.google_auth    import is_google_configured
from .security import permission_manager
from .events import event_bus

logger = logging.getLogger("ToolBridge")


TYPE_MAP = {
    "string": (str, ...),
    "integer": (int, ...),
    "number": (float, ...),
    "boolean": (bool, ...),
    "array": (list, ...),
    "object": (dict, ...),
}


def _build_tool_schema(tool_name: str, props: dict[str, Any], required: list[str]) -> type[BaseModel]:
    """Dynamically create a Pydantic model from a tool's schema properties."""
    fields: dict[str, tuple[Any, Any]] = {}
    for pname, pdef in props.items():
        ptype = pdef.get("type", "string")
        py_type, default = TYPE_MAP.get(ptype, (str, ...))
        if pname not in required:
            default = None
            py_type = Optional[py_type]
        fields[pname] = (py_type, default)
    return create_model(f"{tool_name}_args", **fields)  # type: ignore


def _validate_tool_args(tool_name: str, raw_args: str, tool_schemas: list[Dict]) -> tuple[Dict | None, str | None]:
    """Validate tool arguments against the declared schema. Returns (parsed_args, error_msg)."""
    try:
        parsed = json.loads(raw_args) if raw_args and raw_args.strip() else {}
    except json.JSONDecodeError as jde:
        return None, f"Invalid JSON in tool call arguments: {jde}. Raw: {raw_args}"

    # Find matching schema
    for schema in tool_schemas:
        fn_info = schema.get("function", {})
        if fn_info.get("name") == tool_name:
            params = fn_info.get("parameters", {})
            props = params.get("properties", {})
            required = params.get("required", [])
            model_class = _build_tool_schema(tool_name, props, required)
            try:
                validated = model_class(**parsed)
                return validated.model_dump(exclude_none=True), None
            except ValidationError as ve:
                return None, f"Tool '{tool_name}' argument validation failed: {ve}"

    # Schema not found; still return parsed args (no strict enforcement)
    return parsed, None


logger = logging.getLogger("ToolBridge")


# ── One-time skill registration at import time ─────────────────────────────────

def _register_default_skills() -> None:
    """Register all built-in skills with their default (no-config) settings."""
    if not skill_manager.get("code"):
        skill_manager.register(CodeSkill())
    if not skill_manager.get("terminal"):
        skill_manager.register(TerminalSkill())

    from .skills.weather_skill        import WeatherSkill
    from .skills.web_search_skill     import WebSearchSkill
    from .skills.clipboard_skill      import ClipboardSkill
    from .skills.screenshot_skill     import ScreenshotSkill
    from .skills.youtube_skill        import YouTubeSkill
    from .skills.web_scrape_skill     import WebScrapeSkill
    from .skills.app_launcher_skill   import AppLauncherSkill
    from .skills.daily_briefing_skill import DailyBriefingSkill

    for skill_cls in [WeatherSkill, WebSearchSkill, ClipboardSkill,
                      ScreenshotSkill, YouTubeSkill, WebScrapeSkill, AppLauncherSkill, DailyBriefingSkill]:
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
        "daily_briefing": ["briefing", "tasks", "todo", "agenda", "schedule brief", "daily brief"],
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
        if tool_name.startswith("daily_briefing_") and "daily_briefing" in active_categories:
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
        # Fallback: if no keywords matched, provide ALL schemas so the LLM has full capabilities
        return schemas

    # If keywords matched, always include core tools (code, terminal) as they are universally useful,
    # along with the matched prefixes.
    always_include = {"code", "terminal"}
    active_categories = matched_prefixes.union(always_include)
    filtered = [t for t in schemas if tool_matches(t["function"]["name"], active_categories)]
    return filtered if filtered else schemas


def _validate_call(tool_name: str, tool_args_json: str):
    """Common validation for both sync and async tool calls."""
    schemas = skill_manager.get_tool_schemas()
    parsed, error = _validate_tool_args(tool_name, tool_args_json, schemas)
    if error:
        from .skills.skill_base import SkillResult
        return None, SkillResult.invalid(error)
    if parsed is None:
        parsed = {}
    return parsed, None


def handle_tool_call(tool_name: str, tool_args_json: str) -> str:
    parsed, validation_error = _validate_call(tool_name, tool_args_json)
    if validation_error:
        return validation_error.to_tool_message()

    try:
        result = skill_manager.dispatch(tool_name, parsed)
        return result.to_tool_message()
    except Exception as e:
        logger.error("Tool execution failed for %s: %s", tool_name, e)
        from .skills.skill_base import SkillResult
        return SkillResult.fail(f"Error executing tool {tool_name}: {e}").to_tool_message()


async def handle_tool_call_async(tool_name: str, tool_args_json: str) -> str:
    parsed, validation_error = _validate_call(tool_name, tool_args_json)
    if validation_error:
        return validation_error.to_tool_message()

    try:
        result = await skill_manager.dispatch_async(tool_name, parsed)
        return result.to_tool_message()
    except Exception as e:
        logger.error("Tool execution failed for %s: %s", tool_name, e)
        from .skills.skill_base import SkillResult
        return SkillResult.fail(f"Error executing tool {tool_name}: {e}").to_tool_message()
