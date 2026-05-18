import logging
import time
import uuid
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("Planner")


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStep:
    def __init__(self, step_id: str, reasoning: str, tool: str, args: dict):
        self.id = step_id
        self.reasoning = reasoning
        self.tool = tool
        self.args = args
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: str = ""


class Planner:
    def __init__(self):
        self._retry_limit = 2

    def set_retry_limit(self, limit: int) -> None:
        self._retry_limit = limit

    def decompose(self, goal: str, available_tools: list[str]) -> list[PlanStep]:
        steps = []
        step_id = lambda: str(uuid.uuid4())[:8]
        steps.append(PlanStep(
            step_id=step_id(),
            reasoning=f"Analyzing goal: {goal}",
            tool="",
            args={},
        ))
        return steps

    async def execute_step(self, step: PlanStep, dispatch_fn) -> Any:
        step.status = StepStatus.RUNNING
        for attempt in range(self._retry_limit + 1):
            try:
                result = await dispatch_fn(step.tool, step.args)
                step.status = StepStatus.COMPLETED
                step.result = result
                return result
            except Exception as e:
                step.error = str(e)
                logger.warning(f"[Planner] Step '{step.id}' attempt {attempt + 1} failed: {e}")
                if attempt < self._retry_limit:
                    continue
                step.status = StepStatus.FAILED
                return None

    def summarize(self, steps: list[PlanStep]) -> str:
        completed = [s for s in steps if s.status == StepStatus.COMPLETED]
        failed = [s for s in steps if s.status == StepStatus.FAILED]
        summary = f"Completed {len(completed)}/{len(steps)} steps"
        if failed:
            summary += f" ({len(failed)} failed)"
        return summary

    def track_state(self, steps: list[PlanStep]) -> dict:
        return {
            "total": len(steps),
            "pending": sum(1 for s in steps if s.status == StepStatus.PENDING),
            "running": sum(1 for s in steps if s.status == StepStatus.RUNNING),
            "completed": sum(1 for s in steps if s.status == StepStatus.COMPLETED),
            "failed": sum(1 for s in steps if s.status == StepStatus.FAILED),
        }


planner = Planner()
