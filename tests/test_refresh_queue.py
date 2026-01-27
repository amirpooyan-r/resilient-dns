import asyncio

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler, HandlerConfig
from resilientdns.metrics import Metrics


class StubUpstream:
    async def query(self, wire: bytes, request_id: str | None = None):
        return None


def test_refresh_enqueue_dedup():
    async def run():
        metrics = Metrics()
        handler = DnsHandler(
            upstream=StubUpstream(),
            cache=MemoryDnsCache(CacheConfig()),
            config=HandlerConfig(refresh_queue_max=2),
            metrics=metrics,
        )

        key = ("example.com", 1, 1)
        assert handler.enqueue_refresh(key, reason="stale_served") is True
        assert handler.enqueue_refresh(key, reason="stale_served") is False

        snapshot = metrics.snapshot()
        assert snapshot.get("cache_refresh_enqueued_total") == 1
        assert snapshot.get("cache_refresh_dropped_total{reason=duplicate}") == 1
        assert handler.refresh_queue.qsize() == 1

    asyncio.run(run())


def test_refresh_enqueue_queue_full():
    async def run():
        metrics = Metrics()
        handler = DnsHandler(
            upstream=StubUpstream(),
            cache=MemoryDnsCache(CacheConfig()),
            config=HandlerConfig(refresh_queue_max=1),
            metrics=metrics,
        )

        key1 = ("example.com", 1, 1)
        key2 = ("example.net", 1, 1)
        assert handler.enqueue_refresh(key1, reason="stale_served") is True
        assert handler.enqueue_refresh(key2, reason="stale_served") is False

        snapshot = metrics.snapshot()
        assert snapshot.get("cache_refresh_enqueued_total") == 1
        assert snapshot.get("cache_refresh_dropped_total{reason=queue_full}") == 1
        assert handler.refresh_queue.qsize() == 1

    asyncio.run(run())
