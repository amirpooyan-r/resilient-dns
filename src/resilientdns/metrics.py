from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from threading import Lock

logger = logging.getLogger("resilientdns")

_STATS_FIELDS = (
    ("queries", "queries_total"),
    ("hit_fresh", "cache_hit_fresh_total"),
    ("hit_stale", "cache_hit_stale_total"),
    ("miss", "cache_miss_total"),
    ("negative_hit", "negative_cache_hit_total"),
    ("upstream_req", "upstream_requests_total"),
    ("upstream_fail", "upstream_fail_total"),
    ("refresh", "swr_refresh_triggered_total"),
    ("dedup", "singleflight_dedup_total"),
    ("dropped", "dropped_total"),
)


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


def format_stats(snapshot: Mapping[str, int]) -> str:
    parts = [f"{label}={snapshot.get(key, 0)}" for label, key in _STATS_FIELDS]
    return f"STATS {' '.join(parts)}"


async def periodic_stats_reporter(metrics: Metrics | None, interval_s: float = 30.0) -> None:
    if metrics is None:
        return

    while True:
        await asyncio.sleep(interval_s)
        snapshot = metrics.snapshot()
        if not any(snapshot.values()):
            continue
        logger.info(format_stats(snapshot))
