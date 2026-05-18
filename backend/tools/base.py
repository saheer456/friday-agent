from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    status: str = "success"
    message: str = ""
    data: Any = None
    error: str = ""
    tool: str = ""
    duration_ms: float = 0.0


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    permissions: list[str] = []

    @abstractmethod
    async def run(self, args: dict) -> ToolResult:
        ...
