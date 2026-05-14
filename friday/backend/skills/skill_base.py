"""
skill_base.py — Foundation for the FRIDAY Skills Framework
============================================================
All skills inherit from BaseSkill. Results are always SkillResult.
The SkillRegistry is a global lookup used by SkillManager.
"""
from __future__ import annotations

import inspect
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ── Status Enum ────────────────────────────────────────────────────────────────

class SkillStatus(str, Enum):
    SUCCESS         = "success"
    FAILED          = "failed"
    NOT_CONFIGURED  = "not_configured"
    INVALID_PARAMS  = "invalid_params"
    DISABLED        = "disabled"
    TIMEOUT         = "timeout"


# ── Result Dataclass ───────────────────────────────────────────────────────────

@dataclass
class SkillResult:
    """Standardised return value for every skill action."""
    status:    SkillStatus
    message:   str          = ""
    data:      Any          = None
    error:     str          = ""
    skill:     str          = ""
    action:    str          = ""
    duration_ms: float      = 0.0

    # ── Convenience ────────────────────────────────────────────────────────────
    def is_success(self) -> bool:
        return self.status == SkillStatus.SUCCESS

    def to_tool_message(self) -> str:
        """Serialise to a string that can be fed back to the LLM as a tool result."""
        if self.is_success():
            payload = {"status": self.status, "message": self.message}
            if self.data is not None:
                payload["data"] = self.data
        else:
            payload = {"status": self.status, "error": self.error or self.message}
        return json.dumps(payload, ensure_ascii=False, default=str)

    # ── Factories ──────────────────────────────────────────────────────────────
    @classmethod
    def ok(cls, message: str = "", data: Any = None, **kwargs) -> "SkillResult":
        return cls(status=SkillStatus.SUCCESS, message=message, data=data, **kwargs)

    @classmethod
    def fail(cls, error: str, **kwargs) -> "SkillResult":
        return cls(status=SkillStatus.FAILED, error=error, **kwargs)

    @classmethod
    def not_configured(cls, skill: str) -> "SkillResult":
        return cls(status=SkillStatus.NOT_CONFIGURED,
                   error=f"Skill '{skill}' is not configured. Call .configure() first.",
                   skill=skill)

    @classmethod
    def invalid(cls, msg: str) -> "SkillResult":
        return cls(status=SkillStatus.INVALID_PARAMS, error=msg)


# ── Action Decorator ───────────────────────────────────────────────────────────

def skill_action(
    description: str,
    params: Optional[Dict[str, Any]] = None,
    required: Optional[List[str]] = None,
):
    """
    Decorator that marks a method as an invokable skill action.
    Decorated methods are automatically included in the LLM tool schema.

    Usage:
        @skill_action(
            description="Send an email to a recipient.",
            params={"to": {"type": "string"}, "body": {"type": "string"}},
            required=["to", "body"],
        )
        def send(self, to: str, body: str) -> SkillResult: ...
    """
    def decorator(fn: Callable) -> Callable:
        fn._is_skill_action = True
        fn._description     = description
        fn._params          = params or {}
        fn._required        = required or []
        return fn
    return decorator


# ── Base Skill ─────────────────────────────────────────────────────────────────

class BaseSkill(ABC):
    """
    Abstract base class for all FRIDAY skills.

    Subclasses MUST implement:
        name        — unique identifier (e.g. "email")
        description — one-liner used in the LLM tool schema
        configure() — validate and store config dict
    """

    name:        str = ""
    description: str = ""

    def __init__(self) -> None:
        self._configured: bool = False
        self._enabled:    bool = True
        self._config:     Dict[str, Any] = {}
        self._exec_count: int = 0
        self._fail_count: int = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    @abstractmethod
    def configure(self, config: Dict[str, Any]) -> bool:
        """Store and validate config. Return True on success."""
        ...

    def enable(self)  -> None: self._enabled = True
    def disable(self) -> None: self._enabled = False

    @property
    def is_ready(self) -> bool:
        return self._configured and self._enabled

    # ── Schema generation ──────────────────────────────────────────────────────

    def get_actions(self) -> Dict[str, Callable]:
        """Return all methods decorated with @skill_action."""
        return {
            name: method
            for name, method in inspect.getmembers(self, predicate=inspect.ismethod)
            if getattr(method, "_is_skill_action", False)
        }

    def to_tool_schemas(self) -> List[Dict]:
        """
        Generate OpenAI/Groq-compatible tool schemas for every @skill_action.
        Each action becomes a separate tool: f"{self.name}_{action_name}"
        """
        schemas = []
        for action_name, method in self.get_actions().items():
            tool_name = f"{self.name}_{action_name}"
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": method._description,
                    "parameters": {
                        "type": "object",
                        "properties": method._params,
                        "required": method._required,
                    },
                },
            })
        return schemas

    # ── Execution ──────────────────────────────────────────────────────────────

    def run(self, action: str, **kwargs) -> SkillResult:
        """Dispatch an action by name with timing and error wrapping."""
        if not self._enabled:
            return SkillResult(status=SkillStatus.DISABLED,
                               error=f"Skill '{self.name}' is disabled.",
                               skill=self.name, action=action)
        if not self._configured:
            return SkillResult.not_configured(self.name)

        actions = self.get_actions()
        if action not in actions:
            return SkillResult.invalid(f"Unknown action '{action}' for skill '{self.name}'")

        t0 = time.perf_counter()
        try:
            result = actions[action](**kwargs)
            result.skill  = self.name
            result.action = action
            result.duration_ms = (time.perf_counter() - t0) * 1000
            self._exec_count += 1
            if not result.is_success():
                self._fail_count += 1
            return result
        except TypeError as e:
            self._fail_count += 1
            return SkillResult.invalid(f"Bad params for '{action}': {e}")
        except Exception as e:
            self._fail_count += 1
            return SkillResult.fail(str(e), skill=self.name, action=action,
                                    duration_ms=(time.perf_counter() - t0) * 1000)

    # ── Info ───────────────────────────────────────────────────────────────────

    def info(self) -> Dict[str, Any]:
        return {
            "name":        self.name,
            "description": self.description,
            "configured":  self._configured,
            "enabled":     self._enabled,
            "actions":     list(self.get_actions().keys()),
            "exec_count":  self._exec_count,
            "fail_count":  self._fail_count,
        }


# ── Global Registry ────────────────────────────────────────────────────────────

class SkillRegistry:
    """Thread-safe global registry of all registered BaseSkill instances."""

    _skills: Dict[str, BaseSkill] = {}

    @classmethod
    def register(cls, skill: BaseSkill) -> None:
        if not skill.name:
            raise ValueError("Skill must have a non-empty name.")
        cls._skills[skill.name] = skill

    @classmethod
    def unregister(cls, name: str) -> None:
        cls._skills.pop(name, None)

    @classmethod
    def get(cls, name: str) -> Optional[BaseSkill]:
        return cls._skills.get(name)

    @classmethod
    def all(cls) -> Dict[str, BaseSkill]:
        return dict(cls._skills)

    @classmethod
    def clear(cls) -> None:
        cls._skills.clear()
