import time

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.metrics import Metrics


def test_cache_clear_updates_metrics():
    metrics = Metrics()
    cache = MemoryDnsCache(CacheConfig(), metrics=metrics)
    now = time.monotonic()
    cache._put_entry_for_test(
        ("example.com", 1, 1),
        CacheEntry(response_wire=b"x", expires_at=now + 10, stale_until=now + 20, rcode=0),
    )

    cache.clear()

    snap = metrics.snapshot()
    assert snap.get("cache_entries", 0) == 0
    assert snap.get("cache_clears_total", 0) == 1
