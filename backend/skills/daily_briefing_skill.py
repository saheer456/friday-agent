from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

from .skill_base import BaseSkill, SkillResult, skill_action
from ..tools_utils import CONV_DIR, get_weather


class DailyBriefingSkill(BaseSkill):
    name = "daily_briefing"
    description = "Retrieve the user's daily briefing and scan for pending tasks."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Scan the workspace conversation history to list all pending tasks marked with [TASK].",
        params={},
        required=[],
    )
    def list_tasks(self) -> SkillResult:
        try:
            os.makedirs(CONV_DIR, exist_ok=True)
            tasks = []
            for f in sorted(CONV_DIR.glob("*.md")):
                for line in f.read_text(encoding="utf-8").splitlines():
                    if "[TASK]" in line.upper():
                        tasks.append({
                            "task": line.upper().replace("[TASK]", "").strip(" -•*"),
                            "file": f.name
                        })
            return SkillResult.ok(
                message=f"Found {len(tasks)} pending tasks.",
                data={"tasks": tasks}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to list tasks: {e}")

    @skill_action(
        description="Get a combined daily briefing including current date, weather summary, and pending tasks list.",
        params={},
        required=[],
    )
    async def get_briefing(self) -> SkillResult:
        try:
            w = await get_weather()
            t_res = self.list_tasks()
            
            ws = w.get("summary", "Weather unavailable") if "error" not in w else "Unavailable"
            
            if t_res.is_success():
                tl = t_res.data.get("tasks", [])
                ts = "\n".join(f"- {x['task']}" for x in tl) if tl else "No pending tasks."
            else:
                ts = "Tasks list could not be retrieved."
                
            day = datetime.now().strftime("%A, %B %d")
            briefing = f"Today is {day}.\nWeather: {ws}\nPending tasks:\n{ts}"
            
            return SkillResult.ok(
                message="Daily briefing generated.",
                data={"briefing": briefing}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to generate daily briefing: {e}")
