"""
FRIDAY Skills Framework
=======================
Drop-in skill modules that the LLM can invoke via OpenAI-compatible tool calling.

Usage:
    from backend.skills import skill_manager
    schemas = skill_manager.get_tool_schemas()   # inject into LLM tools= param
    result  = skill_manager.execute(tool_name, **args)
"""

from .skill_base    import BaseSkill, SkillResult, SkillStatus, SkillRegistry
from .skill_manager import SkillManager, skill_manager   # singleton

__all__ = [
    "BaseSkill", "SkillResult", "SkillStatus", "SkillRegistry",
    "SkillManager", "skill_manager",
]
