import time

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.metrics import Metrics


def test_cache_stats_snapshot_counts():
    metrics = Metrics()
    cache = MemoryDnsCache(CacheConfig(serve_stale_max_s=60), metrics=metrics)
    now = time.monotonic()

    cache._put_entry_for_test(
        ("fresh", 1, 1),
        CacheEntry(response_wire=b"x", expires_at=now + 10, stale_until=now + 70, rcode=0),
    )
    cache._put_entry_for_test(
        ("stale", 1, 1),
        CacheEntry(response_wire=b"y", expires_at=now - 5, stale_until=now + 20, rcode=0),
    )
    cache._put_entry_for_test(
        ("expired", 1, 1),
        CacheEntry(response_wire=b"z", expires_at=now - 20, stale_until=now - 10, rcode=0),
    )
    cache._put_entry_for_test(
        ("negative", 1, 1),
        CacheEntry(response_wire=b"n", expires_at=now + 5, stale_until=now + 65, rcode=3),
    )

    metrics.inc("evictions_total", 2)
    snapshot = cache.stats_snapshot()

    assert snapshot["entries_total"] == 4
    assert snapshot["fresh_total"] == 2
    assert snapshot["expired_total"] == 2
    assert snapshot["stale_servable_total"] == 1
    assert snapshot["negative_total"] == 1
    assert snapshot["evictions_total"] == 2
