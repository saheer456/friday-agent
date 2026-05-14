"""
skill_manager.py — Orchestration Engine for the FRIDAY Skills Framework
========================================================================
The SkillManager is a singleton that:
  - Holds all registered skills
  - Generates LLM tool schemas from them
  - Routes tool_call responses from the LLM back to the correct skill action
  - Tracks execution history and stats
"""
from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillRegistry, SkillResult, SkillStatus


class SkillManager:
    """
    Central orchestrator.

    Typical startup:
        from backend.skills import skill_manager
        from backend.skills.code_skill import CodeSkill
        from backend.skills.terminal_skill import TerminalSkill

        skill_manager.register(CodeSkill())
        skill_manager.register(TerminalSkill())

    LLM integration:
        schemas = skill_manager.get_tool_schemas()
        # pass schemas to your LLM call under tools=[...]
        # when the LLM responds with a tool_call:
        result = skill_manager.dispatch(tool_name, tool_args_dict)
        tool_message = result.to_tool_message()
    """

    def __init__(self, history_limit: int = 200) -> None:
        self._history: deque[Dict] = deque(maxlen=history_limit)
        self._start_time = time.time()

    # ── Registration ───────────────────────────────────────────────────────────

    def register(self, skill: BaseSkill, config: Optional[Dict[str, Any]] = None) -> None:
        """Register a skill, optionally configuring it immediately."""
        if config:
            skill.configure(config)
        SkillRegistry.register(skill)
        print(f"[Skills] ✓ Registered '{skill.name}' | actions: {list(skill.get_actions().keys())}")

    def unregister(self, name: str) -> None:
        SkillRegistry.unregister(name)

    def get(self, name: str) -> Optional[BaseSkill]:
        return SkillRegistry.get(name)

    def list_skills(self) -> List[Dict]:
        return [s.info() for s in SkillRegistry.all().values()]

    # ── LLM Tool Schema ────────────────────────────────────────────────────────

    def get_tool_schemas(self) -> List[Dict]:
        """
        Returns a list of OpenAI/Groq-compatible tool schema dicts.
        Inject into your LLM call:
            response = client.chat.completions.create(
                model=...,
                messages=...,
                tools=skill_manager.get_tool_schemas(),
            )
        """
        schemas = []
        for skill in SkillRegistry.all().values():
            if skill._enabled:
                schemas.extend(skill.to_tool_schemas())
        return schemas

    # ── Dispatch (tool_call router) ────────────────────────────────────────────

    def dispatch(self, tool_name: str, args: Dict[str, Any]) -> SkillResult:
        """
        Route an LLM tool_call to the correct skill + action.

        The LLM emits tool names in the format:  "<skill_name>_<action_name>"
        e.g. "code_generate_code", "terminal_run_command", "email_send_email"

        This method splits on the first known skill prefix, executes the
        action, records the call in history, and returns a SkillResult.
        """
        t0 = time.perf_counter()

        # Find a registered skill whose name is a prefix of tool_name
        skill_name  = None
        action_name = None
        for name in SkillRegistry.all():
            prefix = f"{name}_"
            if tool_name.startswith(prefix):
                skill_name  = name
                action_name = tool_name[len(prefix):]
                break

        if skill_name is None:
            result = SkillResult.invalid(f"No skill found for tool '{tool_name}'")
        else:
            skill  = SkillRegistry.get(skill_name)
            result = skill.run(action_name, **args)

        result.duration_ms = (time.perf_counter() - t0) * 1000
        self._history.append({
            "tool":       tool_name,
            "args":       args,
            "status":     result.status,
            "duration_ms": result.duration_ms,
            "ts":         time.time(),
        })
        return result

    # ── Convenience execute (non-LLM path) ────────────────────────────────────

    def execute(self, skill_name: str, action: str, **kwargs) -> SkillResult:
        """Directly call a skill action without going through the tool_name format."""
        skill = SkillRegistry.get(skill_name)
        if skill is None:
            return SkillResult.invalid(f"Skill '{skill_name}' not registered")
        return skill.run(action, **kwargs)

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        calls = list(self._history)
        total   = len(calls)
        success = sum(1 for c in calls if c["status"] == SkillStatus.SUCCESS)
        return {
            "total_calls":    total,
            "success_calls":  success,
            "failed_calls":   total - success,
            "success_rate":   round(success / total * 100, 1) if total else 0.0,
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "skills":         self.list_skills(),
        }

    def get_history(self, n: int = 20) -> List[Dict]:
        return list(self._history)[-n:]


# ── Global singleton ───────────────────────────────────────────────────────────
# Import this everywhere; skills are registered at startup.
skill_manager = SkillManager()
