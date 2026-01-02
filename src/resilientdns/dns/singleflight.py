import asyncio
from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar

from resilientdns.metrics import Metrics

T = TypeVar("T")


class SingleFlight:
    """
    Deduplicate concurrent work per key.
    First caller becomes leader and creates the task; others join the same task.
    The task is removed when it completes (success, error, or cancel).
    """

    def __init__(self, metrics: Metrics | None = None) -> None:
        self.metrics = metrics
        self._lock = asyncio.Lock()
        self._tasks: dict[Hashable, asyncio.Task] = {}

    async def get_or_create(
        self, key: Hashable, factory: Callable[[], Awaitable[T]]
    ) -> tuple[asyncio.Task, bool]:
        async with self._lock:
            existing = self._tasks.get(key)
            if existing is not None and not existing.done():
                if self.metrics:
                    self.metrics.inc("singleflight_dedup_total")
                return existing, False

            task = asyncio.create_task(factory())
            self._tasks[key] = task
            task.add_done_callback(lambda _t: asyncio.create_task(self._cleanup(key, _t)))
            return task, True

    async def _cleanup(self, key: Hashable, task: asyncio.Task) -> None:
        async with self._lock:
            current = self._tasks.get(key)
            if current is task:
                self._tasks.pop(key, None)
