from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator


class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RATE_LIMITED = "rate_limited"


@dataclass
class ProviderConfig:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: float = 30.0
    max_retries: int = 3
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class BaseProvider(ABC):
    name: str = ""
    config: ProviderConfig = field(default_factory=ProviderConfig)
    status: ProviderStatus = ProviderStatus.HEALTHY

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> ProviderResponse:
        ...

    @abstractmethod
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[dict]:
        ...

    async def health_check(self) -> bool:
        return True
