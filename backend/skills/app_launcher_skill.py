from __future__ import annotations

import os
import platform
import re
import subprocess
import webbrowser
from typing import Any, Dict, Optional

from .skill_base import BaseSkill, SkillResult, skill_action

_APP_ALIASES: dict[str, str] = {
    "chrome": "chrome", "browser": "chrome", "edge": "msedge",
    "vscode": "code", "vs code": "code", "code": "code",
    "notepad": "notepad", "explorer": "explorer", "files": "explorer",
    "calculator": "calc", "calc": "calc", "terminal": "wt", "cmd": "cmd",
    "spotify": "spotify", "discord": "discord", "slack": "slack",
}


class AppLauncherSkill(BaseSkill):
    name = "app_launcher"
    description = "Open applications, URLs, or files on the local machine."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    def _open_file(self, path: str) -> None:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    @skill_action(
        description="Open an application, URL, or file on the local machine.",
        params={
            "target": {"type": "string", "description": "App name (e.g. 'chrome', 'vscode'), URL, or file path."},
        },
        required=["target"],
    )
    def open_application(self, target: str) -> SkillResult:
        target = target.strip().lower()
        if not target:
            return SkillResult.invalid("Target required.")
        try:
            if target.startswith("http"):
                webbrowser.open(target)
                return SkillResult.ok(message=f"Opened {target} in browser.", data={"opened": target})
            cmd = _APP_ALIASES.get(target)
            if cmd is None:
                return SkillResult.fail(
                    f"Unknown app '{target}'. Allowed: {list(_APP_ALIASES.keys())}"
                )
            subprocess.Popen([cmd], shell=False)
            return SkillResult.ok(message=f"Opening {cmd}.", data={"opened": cmd})
        except Exception as e:
            return SkillResult.fail(f"Failed to open {target}: {e}")
