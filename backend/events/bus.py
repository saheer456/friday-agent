import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("EventBus")


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable[[dict], Coroutine]]] = {}
        self._history: list[dict] = []
        self._max_history = 200

    def subscribe(self, event_type: str, handler: Callable[[dict], Coroutine]) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[dict], Coroutine]) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type] = [h for h in self._subscribers[event_type] if h is not handler]

    async def emit(self, event_type: str, data: dict) -> None:
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"[EventBus] Handler error for event '{event_type}': {e}")

    def get_history(self, limit: int = 50) -> list[dict]:
        return list(self._history)[-limit:]

    def clear_history(self) -> None:
        self._history.clear()


event_bus = EventBus()
