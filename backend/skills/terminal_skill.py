"""
terminal_skill.py — Local System Access Skill
=============================================
Gives FRIDAY controlled access to the local filesystem and shell.

SAFETY:
  - All shell commands run with a configurable timeout
  - A blocklist prevents destructive commands (rm -rf, format, del /f, etc.)
  - File reads are capped to avoid LLM context flooding
  - Writes only allowed inside the workspace root
"""
from __future__ import annotations

import os
import re as _re
import shlex
import subprocess
import sys
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action

# Commands that are never allowed regardless of config
_HARD_BLOCK = {
    "rm", "rmdir", "del", "format", "mkfs", "dd",
    "shutdown", "reboot", "halt", "poweroff",
    ":(){ :|:& };:",   # fork bomb
    "deltree", "cipher", "sfc", "bcdedit", "diskpart",
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
        
        # Ensure containment via Path.is_relative_to
        if not p.is_relative_to(self._workspace):
            raise PermissionError(
                f"Path '{p}' is outside the allowed workspace '{self._workspace}'. "
                "Access denied."
            )
        return p

    def _is_blocked(self, command: str) -> bool:
        """Block if any token is a dangerous command OR shell metacharacters present."""
        if _re.search(r"[;&|`$()]", command):
            return True
        try:
            parts = shlex.split(command, posix=(sys.platform != "win32"))
        except ValueError:
            return True  # malformed shell input -> block
        for part in parts:
            if Path(part).name.lower() in _HARD_BLOCK:
                return True
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
        permissions=["terminal:shell"]
    )
    def run_command(self, command: str, cwd: Optional[str] = None) -> SkillResult:
        if not self._allow_shell:
            return SkillResult.fail("Shell execution is disabled in this configuration.")
        if self._is_blocked(command):
            return SkillResult.fail(f"Command '{command.split()[0]}' is blocked for safety.")

        work_dir = self._workspace if cwd is None else self._check_path(cwd)
        try:
            try:
                parts = shlex.split(command, posix=(sys.platform != "win32"))
            except ValueError as e:
                return SkillResult.fail(f"Invalid command syntax: {e}")
            proc = subprocess.run(
                parts,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=str(work_dir),
            )
            stdout_raw = proc.stdout.strip()
            stderr_raw = proc.stderr.strip()
            
            stdout_limit = 8_000
            stderr_limit = 2_000
            
            stdout = stdout_raw[:stdout_limit]
            stderr = stderr_raw[:stderr_limit]
            truncated = (len(stdout_raw) > stdout_limit) or (len(stderr_raw) > stderr_limit)
            
            return SkillResult.ok(
                message="Command executed.",
                data={
                    "stdout":    stdout,
                    "stderr":    stderr,
                    "exit_code": proc.returncode,
                    "cwd":       str(work_dir),
                    "truncated": truncated,
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
        permissions=["terminal:read"]
    )
    def read_file(self, path: str, max_bytes: Optional[int] = None) -> SkillResult:
        try:
            p = self._check_path(path)
            if not p.exists():
                return SkillResult.fail(f"File not found: {p}")
            limit = max_bytes or self._max_bytes
            content_raw = p.read_bytes()
            content = content_raw[:limit].decode("utf-8", errors="replace")
            truncated = len(content_raw) > limit
            return SkillResult.ok(
                message=f"Read {len(content)} chars from {p.name}",
                data={
                    "content": content,
                    "path": str(p),
                    "size_bytes": p.stat().st_size,
                    "truncated": truncated
                },
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
        permissions=["terminal:write"]
    )
    def write_file(self, path: str, content: str, append: bool = False) -> SkillResult:
        if not self._allow_write:
            return SkillResult.fail("File writes are disabled in this configuration.")
        try:
            p = self._check_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with p.open(mode, encoding="utf-8") as f:
                f.write(content)
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
        permissions=["terminal:read"]
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

    @skill_action(
        description="Copy a file or directory.",
        params={
            "src": {"type": "string", "description": "Source path (relative or absolute)."},
            "dst": {"type": "string", "description": "Destination path (relative or absolute)."},
        },
        required=["src", "dst"],
        permissions=["terminal:write"]
    )
    def copy_file(self, src: str, dst: str) -> SkillResult:
        try:
            s = self._check_path(src)
            d = self._check_path(dst)
            if not s.exists():
                return SkillResult.fail(f"Source path does not exist: {s}")
            if s.is_dir():
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
            return SkillResult.ok(message=f"Copied {src} to {dst}.")
        except Exception as e:
            return SkillResult.fail(f"Copy failed: {e}")

    @skill_action(
        description="Move/rename a file or directory.",
        params={
            "src": {"type": "string", "description": "Source path (relative or absolute)."},
            "dst": {"type": "string", "description": "Destination path (relative or absolute)."},
        },
        required=["src", "dst"],
        permissions=["terminal:write"]
    )
    def move_file(self, src: str, dst: str) -> SkillResult:
        try:
            s = self._check_path(src)
            d = self._check_path(dst)
            if not s.exists():
                return SkillResult.fail(f"Source path does not exist: {s}")
            shutil.move(str(s), str(d))
            return SkillResult.ok(message=f"Moved {src} to {dst}.")
        except Exception as e:
            return SkillResult.fail(f"Move failed: {e}")

    @skill_action(
        description="Delete a file or empty directory.",
        params={
            "path": {"type": "string", "description": "File or folder path to delete."},
        },
        required=["path"],
        permissions=["terminal:write"]
    )
    def delete_file(self, path: str) -> SkillResult:
        try:
            p = self._check_path(path)
            if not p.exists():
                return SkillResult.fail(f"Path does not exist: {p}")
            if p.is_dir():
                p.rmdir()  # only delete empty dirs for safety
                msg = f"Deleted directory {path}."
            else:
                p.unlink()
                msg = f"Deleted file {path}."
            return SkillResult.ok(message=msg)
        except Exception as e:
            return SkillResult.fail(f"Delete failed: {e}")

    @skill_action(
        description="Search for files recursively by name patterns or search content inside files.",
        params={
            "path":    {"type": "string", "description": "Root path to search (default: workspace root)."},
            "pattern": {"type": "string", "description": "File name glob pattern (e.g. '*.py')."},
            "query":   {"type": "string", "description": "Text query to search for inside files (optional)."},
        },
        required=[],
        permissions=["terminal:read"]
    )
    def search_files(self, path: str = ".", pattern: str = "*", query: Optional[str] = None) -> SkillResult:
        try:
            root = self._check_path(path)
            if not root.is_dir():
                return SkillResult.fail(f"Not a directory: {root}")
            
            results = []
            for p in root.rglob(pattern):
                try:
                    p_resolved = p.resolve()
                    if not p_resolved.is_relative_to(self._workspace):
                        continue
                    if p_resolved.is_file():
                        if query:
                            # Read text ignoring errors (skips binaries gracefully)
                            content = p_resolved.read_text(encoding="utf-8", errors="ignore")
                            if query in content:
                                results.append(str(p_resolved.relative_to(self._workspace)))
                        else:
                            results.append(str(p_resolved.relative_to(self._workspace)))
                except Exception:
                    continue
                if len(results) >= 100:
                    break
            
            return SkillResult.ok(
                message=f"Search complete. Found {len(results)} files.",
                data={"results": results[:100]}
            )
        except Exception as e:
            return SkillResult.fail(f"Search failed: {e}")
