import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("TaskQueue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task:
    def __init__(self, task_id: str, name: str, coro: Coroutine):
        self.id = task_id
        self.name = name
        self.coro = coro
        self.status = TaskStatus.PENDING
        self.progress: float = 0.0
        self.result: Any = None
        self.error: str = ""
        self.created_at = time.time()
        self.completed_at: Optional[float] = None


class TaskQueue:
    def __init__(self, max_concurrent: int = 4):
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._workers: list[asyncio.Task] = []
        self._max_concurrent = max_concurrent
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for _ in range(self._max_concurrent):
            worker = asyncio.create_task(self._worker_loop())
            self._workers.append(worker)

    async def stop(self) -> None:
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            task.status = TaskStatus.RUNNING
            try:
                result = await task.coro
                task.status = TaskStatus.COMPLETED
                task.result = result
            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                logger.error(f"[TaskQueue] Task '{task.name}' failed: {e}")
            finally:
                task.completed_at = time.time()
                self._queue.task_done()

    def enqueue(self, name: str, coro: Coroutine) -> str:
        task_id = str(uuid.uuid4())[:8]
        task = Task(task_id=task_id, name=name, coro=coro)
        self._tasks[task_id] = task
        self._queue.put_nowait(task)
        logger.info(f"[TaskQueue] Enqueued '{name}' [{task_id}]")
        return task_id

    def get_status(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            return True
        return False

    def list_tasks(self) -> list[dict]:
        return [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status.value,
                "progress": t.progress,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
            }
            for t in self._tasks.values()
        ]


task_queue = TaskQueue()
