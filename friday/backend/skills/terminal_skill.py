"""
terminal_skill.py — Local System Access Skill
=============================================
Gives FRIDAY controlled access to the local filesystem and shell.

SAFETY:
  - All shell commands run with a configurable timeout
  - A blocklist prevents destructive commands (rm -rf, format, del /f, etc.)
  - File reads are capped at max_bytes to avoid LLM context flooding
  - Writes only allowed inside the workspace root by default
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action

# Commands that are never allowed regardless of config
_HARD_BLOCK = {
    "rm", "rmdir", "del", "format", "mkfs", "dd",
    "shutdown", "reboot", "halt", "poweroff",
    ":(){ :|:& };:",   # fork bomb
}


class TerminalSkill(BaseSkill):
    """Safe local terminal & file system access."""

    name        = "terminal"
    description = (
        "Run shell commands, read/write files, and list directories on the local machine. "
        "Use this skill for file management, running scripts, or inspecting the workspace."
    )

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        """
        Config keys:
            workspace   — root directory skill is allowed to write to (default: project root)
            timeout     — shell command timeout in seconds (default: 30)
            max_bytes   — max bytes to read from a file (default: 32 KB)
            allow_write — enable write_file action (default: True)
            allow_shell — enable run_command action (default: True)
        """
        self._workspace   = Path(config.get("workspace", self._default_workspace())).resolve()
        self._timeout     = int(config.get("timeout", 30))
        self._max_bytes   = int(config.get("max_bytes", 32_768))
        self._allow_write = bool(config.get("allow_write", True))
        self._allow_shell = bool(config.get("allow_shell", True))
        self._configured  = True
        return True

    def __init__(self) -> None:
        super().__init__()
        self.configure()   # auto-configure with defaults

    @staticmethod
    def _default_workspace() -> str:
        # Project root is 2 levels above this file (friday/)
        return str(Path(__file__).resolve().parent.parent.parent)

    def _check_path(self, path: str) -> Path:
        """Resolve path and ensure it sits inside the workspace."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self._workspace / p
        p = p.resolve()
        if not str(p).startswith(str(self._workspace)):
            raise PermissionError(
                f"Path '{p}' is outside the allowed workspace '{self._workspace}'. "
                "Access denied."
            )
        return p

    def _is_blocked(self, command: str) -> bool:
        try:
            parts = shlex.split(command, posix=(sys.platform != "win32"))
            base  = Path(parts[0]).name.lower() if parts else ""
            return base in _HARD_BLOCK
        except Exception:
            return False

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description=(
            "Execute a shell command on the local machine. "
            "Returns stdout, stderr, and the exit code. "
            "Avoid destructive commands — they are blocked automatically."
        ),
        params={
            "command": {"type": "string", "description": "Shell command to run."},
            "cwd":     {"type": "string", "description": "Working directory (optional)."},
        },
        required=["command"],
    )
    def run_command(self, command: str, cwd: Optional[str] = None) -> SkillResult:
        if not self._allow_shell:
            return SkillResult.fail("Shell execution is disabled in this configuration.")
        if self._is_blocked(command):
            return SkillResult.fail(f"Command '{command.split()[0]}' is blocked for safety.")

        work_dir = self._workspace if cwd is None else self._check_path(cwd)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=str(work_dir),
            )
            return SkillResult.ok(
                message="Command executed.",
                data={
                    "stdout":    proc.stdout.strip()[:8_000],
                    "stderr":    proc.stderr.strip()[:2_000],
                    "exit_code": proc.returncode,
                    "cwd":       str(work_dir),
                },
            )
        except subprocess.TimeoutExpired:
            return SkillResult.fail(f"Command timed out after {self._timeout}s.")
        except Exception as e:
            return SkillResult.fail(str(e))

    @skill_action(
        description="Read the contents of a file and return it as a string.",
        params={
            "path":      {"type": "string", "description": "File path (relative to workspace or absolute)."},
            "max_bytes": {"type": "integer", "description": "Max bytes to read (default 32768)."},
        },
        required=["path"],
    )
    def read_file(self, path: str, max_bytes: Optional[int] = None) -> SkillResult:
        try:
            p = self._check_path(path)
            if not p.exists():
                return SkillResult.fail(f"File not found: {p}")
            limit = max_bytes or self._max_bytes
            content = p.read_bytes()[:limit].decode("utf-8", errors="replace")
            return SkillResult.ok(
                message=f"Read {len(content)} chars from {p.name}",
                data={"content": content, "path": str(p), "size_bytes": p.stat().st_size},
            )
        except PermissionError as e:
            return SkillResult.fail(str(e))
        except Exception as e:
            return SkillResult.fail(f"Read error: {e}")

    @skill_action(
        description="Write text content to a file. Creates the file and parent directories if needed.",
        params={
            "path":    {"type": "string", "description": "File path (relative to workspace or absolute)."},
            "content": {"type": "string", "description": "Text content to write."},
            "append":  {"type": "boolean", "description": "If true, append instead of overwrite."},
        },
        required=["path", "content"],
    )
    def write_file(self, path: str, content: str, append: bool = False) -> SkillResult:
        if not self._allow_write:
            return SkillResult.fail("File writes are disabled in this configuration.")
        try:
            p = self._check_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            p.open(mode, encoding="utf-8").write(content)
            return SkillResult.ok(
                message=f"{'Appended' if append else 'Wrote'} {len(content)} chars to {p.name}",
                data={"path": str(p), "chars": len(content)},
            )
        except PermissionError as e:
            return SkillResult.fail(str(e))
        except Exception as e:
            return SkillResult.fail(f"Write error: {e}")

    @skill_action(
        description="List the contents of a directory.",
        params={
            "path":    {"type": "string", "description": "Directory path (default: workspace root)."},
            "pattern": {"type": "string", "description": "Glob pattern to filter results (e.g. '*.py')."},
        },
        required=[],
    )
    def list_directory(self, path: str = ".", pattern: str = "*") -> SkillResult:
        try:
            p = self._check_path(path)
            if not p.is_dir():
                return SkillResult.fail(f"Not a directory: {p}")
            entries: List[Dict] = []
            for item in sorted(p.glob(pattern))[:200]:
                entries.append({
                    "name":  item.name,
                    "type":  "dir" if item.is_dir() else "file",
                    "size":  item.stat().st_size if item.is_file() else None,
                })
            return SkillResult.ok(
                message=f"Listed {len(entries)} entries in {p.name}",
                data={"path": str(p), "entries": entries},
            )
        except PermissionError as e:
            return SkillResult.fail(str(e))
        except Exception as e:
            return SkillResult.fail(f"List error: {e}")
