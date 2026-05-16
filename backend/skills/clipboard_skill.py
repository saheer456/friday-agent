from __future__ import annotations

import pyperclip
from typing import Any, Dict

from .skill_base import BaseSkill, SkillResult, skill_action


class ClipboardSkill(BaseSkill):
    name = "clipboard"
    description = "Read the contents of the system clipboard."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Read the current text content of the system clipboard.",
        params={},
        required=[],
    )
    def read_clipboard(self) -> SkillResult:
        try:
            text = pyperclip.paste()[:4000]
            return SkillResult.ok(
                message="Clipboard read.",
                data={"text": text},
            )
        except Exception as e:
            return SkillResult.fail(f"Clipboard read failed: {e}")
