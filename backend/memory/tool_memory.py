import json
import time
from collections import deque
from typing import Any, Optional


class ToolMemoryEntry:
    def __init__(self, tool: str, inputs: dict, outputs: Any, success: bool,
                 duration_ms: float, timestamp: Optional[float] = None):
        self.tool = tool
        self.inputs = inputs
        self.outputs = outputs
        self.success = success
        self.duration_ms = duration_ms
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "inputs": self.inputs,
            "outputs": str(self.outputs)[:500] if not isinstance(self.outputs, str) else self.outputs[:500],
            "success": self.success,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


class ToolMemory:
    def __init__(self, max_entries: int = 500):
        self._entries: deque[ToolMemoryEntry] = deque(maxlen=max_entries)

    def record(self, entry: ToolMemoryEntry) -> None:
        self._entries.append(entry)

    def record_result(self, tool: str, inputs: dict, outputs: Any, success: bool, duration_ms: float) -> None:
        self.record(ToolMemoryEntry(
            tool=tool, inputs=inputs, outputs=outputs,
            success=success, duration_ms=duration_ms,
        ))

    def get_recent(self, n: int = 10) -> list[dict]:
        return [e.to_dict() for e in list(self._entries)[-n:]]

    def get_failures(self, tool: Optional[str] = None, n: int = 10) -> list[dict]:
        failures = [e for e in self._entries if not e.success]
        if tool:
            failures = [e for e in failures if e.tool == tool]
        return [e.to_dict() for e in failures[-n:]]

    def get_stats(self) -> dict:
        total = len(self._entries)
        success = sum(1 for e in self._entries if e.success)
        return {
            "total": total,
            "success": success,
            "failed": total - success,
            "success_rate": round(success / total * 100, 1) if total else 0.0,
        }

    def clear(self) -> None:
        self._entries.clear()


tool_memory = ToolMemory()
