import asyncio
import time

from dnslib import QTYPE, RCODE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler, HandlerConfig
from resilientdns.metrics import Metrics


class TimeoutUpstream:
    def __init__(self):
        self.calls = 0

    async def query(self, wire: bytes):
        self.calls += 1
        raise asyncio.TimeoutError()


class ErrorUpstream:
    def __init__(self):
        self.calls = 0

    async def query(self, wire: bytes):
        self.calls += 1
        raise RuntimeError("boom")


def _make_response(wire: bytes, ip: str) -> bytes:
    req = DNSRecord.parse(wire)
    reply = req.reply()
    reply.add_answer(
        RR(
            rname=req.q.qname,
            rtype=QTYPE.A,
            rclass=1,
            ttl=60,
            rdata=A(ip),
        )
    )
    return reply.pack()


def _cache_key(request: DNSRecord) -> tuple[str, int, int]:
    qname = str(request.q.qname).rstrip(".").lower()
    return (qname, int(request.q.qtype), int(request.q.qclass))


def test_cold_miss_timeout_servfail():
    async def run():
        metrics = Metrics()
        cache = MemoryDnsCache(CacheConfig(), metrics=metrics)
        upstream = TimeoutUpstream()
        handler = DnsHandler(
            upstream=upstream,
            cache=cache,
            metrics=metrics,
            config=HandlerConfig(upstream_timeout_s=0.05),
        )
        request = DNSRecord.question("example.com", qtype="A")

        resp = await handler.handle(request, ("127.0.0.1", 5353))
        assert resp.header.rcode == RCODE.SERVFAIL

        snap = metrics.snapshot()
        assert snap.get("cache_miss_total", 0) == 1
        assert snap.get("upstream_fail_total", 0) == 1
        assert snap.get("queries_total", 0) == 1

    asyncio.run(run())


def test_stale_timeout_serves_stale_immediately():
    async def run():
        metrics = Metrics()
        cache = MemoryDnsCache(CacheConfig(serve_stale_max_s=60), metrics=metrics)
        upstream = TimeoutUpstream()
        handler = DnsHandler(
            upstream=upstream,
            cache=cache,
            metrics=metrics,
            config=HandlerConfig(upstream_timeout_s=0.05),
        )
        request = DNSRecord.question("example.com", qtype="A")
        key = _cache_key(request)

        stale_response = _make_response(request.pack(), "1.2.3.4")
        now = time.monotonic()
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=stale_response,
                expires_at=now - 10,
                stale_until=now + 60,
                rcode=0,
            ),
        )

        start = time.perf_counter()
        resp = await handler.handle(request, ("127.0.0.1", 5353))
        elapsed = time.perf_counter() - start
        assert resp.pack() == stale_response
        assert elapsed < 0.08

        await asyncio.sleep(0)
        snap = metrics.snapshot()
        assert snap.get("cache_hit_stale_total", 0) == 1
        assert snap.get("upstream_fail_total", 0) == 1
        assert snap.get("queries_total", 0) == 1

    asyncio.run(run())


def test_stale_error_serves_stale_immediately():
    async def run():
        metrics = Metrics()
        cache = MemoryDnsCache(CacheConfig(serve_stale_max_s=60), metrics=metrics)
        upstream = ErrorUpstream()
        handler = DnsHandler(
            upstream=upstream,
            cache=cache,
            metrics=metrics,
            config=HandlerConfig(upstream_timeout_s=0.05),
        )
        request = DNSRecord.question("example.com", qtype="A")
        key = _cache_key(request)

        stale_response = _make_response(request.pack(), "1.2.3.4")
        now = time.monotonic()
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=stale_response,
                expires_at=now - 10,
                stale_until=now + 60,
                rcode=0,
            ),
        )

        resp = await handler.handle(request, ("127.0.0.1", 5353))
        assert resp.pack() == stale_response

        await asyncio.sleep(0.01)
        snap = metrics.snapshot()
        assert snap.get("cache_hit_stale_total", 0) == 1
        assert snap.get("upstream_fail_total", 0) == 1
        assert snap.get("queries_total", 0) == 1

    asyncio.run(run())
