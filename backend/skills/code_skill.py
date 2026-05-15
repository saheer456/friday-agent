"""
code_skill.py — Codex-style Code Generation & Execution Skill
==============================================================
Gives FRIDAY the ability to:
  - Generate code via the LLM (using the same Groq backend)
  - Execute Python code safely in a subprocess sandbox
  - Analyse and explain existing code
  - Fix bugs autonomously
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from typing import Any, Dict

from .skill_base import BaseSkill, SkillResult, skill_action


def _api_config():
    """Read LLM config from env vars directly (avoids circular import with brain.py)."""
    provider = os.getenv("FRIDAY_LLM_PROVIDER", "").lower()
    cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
    groq_key     = os.getenv("GROQ_API_KEY", "")
    or_key       = os.getenv("OPENROUTER_API_KEY", "")

    # Prioritize Cerebras for heavy code tasks if available
    if (provider == "cerebras" or cerebras_key) and "your_" not in cerebras_key.lower():
        return (
            "https://api.cerebras.ai/v1/chat/completions",
            cerebras_key,
            os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
        )
    
    if provider == "openrouter" or (not groq_key and or_key):
        return (
            "https://openrouter.ai/api/v1/chat/completions",
            or_key,
            os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-lite-preview-02-05:free"),
        )
    
    return (
        "https://api.groq.com/openai/v1/chat/completions",
        groq_key,
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    )


class CodeSkill(BaseSkill):
    """LLM-powered code generation + sandboxed Python execution."""

    name        = "code"
    description = (
        "Generate, execute, analyse, and fix code. "
        "Use this skill whenever the user asks to write a script, "
        "run Python code, or debug an error."
    )

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        """
        Optional config keys:
            timeout   — subprocess timeout in seconds (default 15)
            max_lines — max output lines to return (default 80)
        """
        self._timeout   = int(config.get("timeout", 15))
        self._max_lines = int(config.get("max_lines", 80))
        self._configured = True
        return True

    def __init__(self) -> None:
        super().__init__()
        self.configure()   # auto-configure with defaults

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description=(
            "Generate clean, working code in any language for a given task. "
            "Returns the full code as a string."
        ),
        params={
            "task":     {"type": "string", "description": "What the code should do."},
            "language": {"type": "string", "description": "Programming language (default: python)."},
            "context":  {"type": "string", "description": "Optional extra context or constraints."},
        },
        required=["task"],
    )
    def generate_code(self, task: str, language: str = "python", context: str = "") -> SkillResult:
        """Ask the LLM to write code. Returns the raw code string."""
        try:
            import httpx
            url, api_key, model = _api_config()
            system = (
                f"You are an expert {language} programmer. "
                "Write clean, well-commented, working code. "
                "Return ONLY the code block — no markdown fences, no explanation."
            )
            user_prompt = f"Task: {task}"
            if context:
                user_prompt += f"\n\nContext: {context}"

            payload = {
                "model": model,
                "messages": [
                    {"role": "system",  "content": system},
                    {"role": "user",    "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
            }
            with httpx.Client(timeout=30.0) as c:
                r = c.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
                r.raise_for_status()
            code = r.json()["choices"][0]["message"]["content"].strip()
            return SkillResult.ok(message="Code generated successfully.", data={"code": code, "language": language})
        except Exception as e:
            return SkillResult.fail(f"Code generation failed: {e}")

    @skill_action(
        description=(
            "Execute a Python code snippet in a safe subprocess sandbox. "
            "Returns stdout, stderr, and the exit code."
        ),
        params={
            "code":    {"type": "string", "description": "Python code to execute."},
            "timeout": {"type": "integer", "description": "Max execution seconds (default 15)."},
        },
        required=["code"],
    )
    def execute_python(self, code: str, timeout: int = None) -> SkillResult:
        """Run Python code in an isolated subprocess and return its output."""
        timeout = timeout or self._timeout
        try:
            # Write code to a temp file — avoids shell injection
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as f:
                f.write(textwrap.dedent(code))
                tmp_path = f.name

            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            os.unlink(tmp_path)

            stdout = "\n".join(proc.stdout.splitlines()[:self._max_lines])
            stderr = proc.stderr.strip()
            success = proc.returncode == 0

            return SkillResult(
                status=("success" if success else "failed"),
                message="Execution complete.",
                data={
                    "stdout":    stdout,
                    "stderr":    stderr,
                    "exit_code": proc.returncode,
                },
            )
        except subprocess.TimeoutExpired:
            return SkillResult.fail(f"Code execution timed out after {timeout}s.")
        except Exception as e:
            return SkillResult.fail(f"Execution error: {e}")

    @skill_action(
        description="Analyse a code snippet and explain what it does, its complexity, and any issues.",
        params={
            "code":     {"type": "string", "description": "Code to analyse."},
            "language": {"type": "string", "description": "Language hint (default: python)."},
        },
        required=["code"],
    )
    def analyse_code(self, code: str, language: str = "python") -> SkillResult:
        """Ask the LLM to explain and review a snippet."""
        try:
            import httpx
            url, api_key, model = _api_config()
            payload = {
                "model": model,
                "messages": [
                    {"role": "system",  "content": "You are a senior code reviewer. Be concise."},
                    {"role": "user",    "content": f"Analyse this {language} code:\n\n{code}"},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            }
            with httpx.Client(timeout=30.0) as c:
                r = c.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
                r.raise_for_status()
            analysis = r.json()["choices"][0]["message"]["content"].strip()
            return SkillResult.ok(message=analysis)
        except Exception as e:
            return SkillResult.fail(f"Analysis failed: {e}")

    @skill_action(
        description="Fix bugs in a code snippet. Returns the corrected code and a brief explanation.",
        params={
            "code":  {"type": "string", "description": "Buggy code."},
            "error": {"type": "string", "description": "Optional error message / traceback."},
        },
        required=["code"],
    )
    def fix_bugs(self, code: str, error: str = "") -> SkillResult:
        """Ask the LLM to fix the code and return the corrected version."""
        try:
            import httpx
            url, api_key, model = _api_config()
            prompt = f"Fix the following code:\n\n{code}"
            if error:
                prompt += f"\n\nError message:\n{error}"
            prompt += "\n\nReturn ONLY the corrected code, then a short explanation after '---'."

            payload = {
                "model": model,
                "messages": [
                    {"role": "system",  "content": "You are an expert debugger. Fix bugs precisely."},
                    {"role": "user",    "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
            }
            with httpx.Client(timeout=30.0) as c:
                r = c.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
                r.raise_for_status()
            response = r.json()["choices"][0]["message"]["content"].strip()
            parts = response.split("---", 1)
            return SkillResult.ok(
                message="Bugs fixed.",
                data={
                    "fixed_code":  parts[0].strip(),
                    "explanation": parts[1].strip() if len(parts) > 1 else "",
                },
            )
        except Exception as e:
            return SkillResult.fail(f"Bug fix failed: {e}")
