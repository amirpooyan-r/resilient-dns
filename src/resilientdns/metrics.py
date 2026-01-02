from __future__ import annotations

from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = {}

    def inc(self, key: str, by: int = 1) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + int(by)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)
