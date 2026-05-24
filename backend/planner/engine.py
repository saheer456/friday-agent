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

    async def decompose(self, goal: str, available_tools: list[dict]) -> list[PlanStep]:
        from backend.providers import provider_manager
        
        tool_descriptions = []
        for t in available_tools:
            fn = t.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "")
            tool_descriptions.append(f"- {name}: {desc}")
        tools_list_str = "\n".join(tool_descriptions)
        
        prompt = (
            "You are the high-level Planner for FRIDAY, an intelligent assistant.\n"
            "Given a complex goal and a set of available tools, decompose it into a sequential list of steps.\n"
            "Each step must contain:\n"
            "1. 'reasoning': Why we are executing this step.\n"
            "2. 'tool': The exact name of the tool to use (or empty string if it's a reasoning/final answer step).\n"
            "3. 'args': A JSON object representing the arguments to pass to the tool (or empty object).\n\n"
            f"Goal: {goal}\n\n"
            f"Available Tools:\n{tools_list_str}\n\n"
            "Respond in JSON format as a list of objects. Example:\n"
            "[\n"
            "  {\n"
            "    \"reasoning\": \"Search the web for the latest weather in Paris.\",\n"
            "    \"tool\": \"web_search\",\n"
            "    \"args\": {\"query\": \"Paris weather 2026\"}\n"
            "  }\n"
            "]\n"
            "Output ONLY valid JSON. No other text or markdown formatting outside of the JSON."
        )
        
        try:
            resp = await provider_manager.generate(
                messages=[{"role": "user", "content": prompt}],
                is_heavy=True
            )
            content = resp.content.strip() if resp and resp.content else ""
            if "```json" in content:
                content = content.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in content:
                content = content.split("```", 1)[1].split("```", 1)[0].strip()
                
            import json
            steps_data = json.loads(content)
            
            steps = []
            import uuid
            for item in steps_data:
                step_id = str(uuid.uuid4())[:8]
                steps.append(PlanStep(
                    step_id=step_id,
                    reasoning=item.get("reasoning", ""),
                    tool=item.get("tool", ""),
                    args=item.get("args", {}),
                ))
            return steps
        except Exception as e:
            logger.error(f"[Planner] Failed to decompose goal: {e}")
            import uuid
            step_id = str(uuid.uuid4())[:8]
            return [PlanStep(
                step_id=step_id,
                reasoning=f"Direct execution of: {goal}",
                tool="",
                args={}
            )]

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
