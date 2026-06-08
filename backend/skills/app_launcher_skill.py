from __future__ import annotations

import os
import platform
import subprocess
import webbrowser
import shutil
from pathlib import Path
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
    description = "Open or close applications, URLs, or files on the local machine."

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
        permissions=["app_launcher:open"]
    )
    def open_application(self, target: str) -> SkillResult:
        target_str = target.strip()
        target_lower = target_str.lower()
        if not target_str:
            return SkillResult.invalid("Target required.")
        try:
            # 1. URL/mailto check
            if target_lower.startswith(("http://", "https://", "mailto:")):
                webbrowser.open(target_str)
                return SkillResult.ok(message=f"Opened URL: {target_str} in browser.", data={"opened": target_str})

            # 2. Local File / Directory check
            try:
                path_obj = Path(target_str).expanduser().resolve()
                if path_obj.exists():
                    self._open_file(str(path_obj))
                    return SkillResult.ok(message=f"Opened path: {target_str}", data={"opened": target_str})
            except Exception:
                pass

            # 3. Check App Alias or System Executable
            cmd = _APP_ALIASES.get(target_lower)
            if cmd is None:
                # Dynamic PATH discovery
                resolved = shutil.which(target_str)
                if resolved:
                    cmd = resolved
                else:
                    return SkillResult.fail(
                        f"Unknown app, path, or URL '{target_str}'. "
                        f"Allowed aliases: {list(_APP_ALIASES.keys())} or executables on system PATH."
                    )

            subprocess.Popen([cmd], shell=False)
            return SkillResult.ok(message=f"Opening application: {cmd}.", data={"opened": cmd})
        except Exception as e:
            return SkillResult.fail(f"Failed to open {target_str}: {e}")

    @skill_action(
        description="Close an active application on the local machine.",
        params={
            "target": {"type": "string", "description": "App name or process name (e.g. 'chrome', 'spotify')."},
        },
        required=["target"],
        permissions=["app_launcher:close"]
    )
    def close_application(self, target: str) -> SkillResult:
        target_str = target.strip()
        target_lower = target_str.lower()
        if not target_str:
            return SkillResult.invalid("Target required.")
        try:
            # Map alias to process name if configured, otherwise use directly
            proc_name = _APP_ALIASES.get(target_lower, target_str)
            system = platform.system()
            if system == "Windows":
                img = proc_name if proc_name.endswith(".exe") else f"{proc_name}.exe"
                cmd = ["taskkill", "/F", "/T", "/IM", img]
                proc = subprocess.run(cmd, shell=False, capture_output=True, text=True)
                if proc.returncode == 0:
                    return SkillResult.ok(message=f"Terminated process '{img}'.")
                else:
                    return SkillResult.fail(f"Failed to close process: {proc.stderr.strip() or 'process not found'}")
            else:
                cmd = ["pkill", "-f", proc_name]
                proc = subprocess.run(cmd, shell=False, capture_output=True, text=True)
                if proc.returncode == 0:
                    return SkillResult.ok(message=f"Terminated process '{proc_name}'.")
                else:
                    return SkillResult.fail(f"Failed to close process: {proc.stderr.strip() or 'process not found'}")
        except Exception as e:
            return SkillResult.fail(f"Failed to close {target_str}: {e}")
