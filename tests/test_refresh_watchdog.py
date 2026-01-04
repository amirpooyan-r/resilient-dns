import asyncio

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler, HandlerConfig


class NoopUpstream:
    async def query(self, wire: bytes):
        return None


def test_refresh_watchdog_does_not_cancel_task():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        handler = DnsHandler(
            upstream=NoopUpstream(),
            cache=cache,
            config=HandlerConfig(refresh_watch_timeout_s=0.01),
        )
        task = asyncio.create_task(asyncio.sleep(0.05))

        await handler._watch_refresh(task, "example.com", "A")

        assert not task.cancelled()
        await task

    asyncio.run(run())
