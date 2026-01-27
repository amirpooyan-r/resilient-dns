import asyncio
import time

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler, HandlerConfig
from resilientdns.metrics import Metrics


class GateUpstream:
    def __init__(self, gate: asyncio.Event, started: asyncio.Event):
        self._gate = gate
        self._started = started

    async def query(self, wire: bytes):
        self._started.set()
        await self._gate.wait()
        req = DNSRecord.parse(wire)
        reply = req.reply()
        reply.add_answer(
            RR(
                rname=req.q.qname,
                rtype=QTYPE.A,
                rclass=1,
                ttl=60,
                rdata=A("9.9.9.9"),
            )
        )
        return reply.pack()


class FailingUpstream:
    def __init__(self, started: asyncio.Event):
        self._started = started

    async def query(self, wire: bytes):
        self._started.set()
        raise RuntimeError("upstream failure")


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


def test_hybrid_gate_blocks_when_hits_below_threshold():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        handler = DnsHandler(
            upstream=GateUpstream(asyncio.Event(), asyncio.Event()),
            cache=cache,
            config=HandlerConfig(
                refresh_enabled=True,
                refresh_ahead_seconds=30,
                refresh_popularity_threshold=5,
                refresh_batch_size=10,
            ),
        )
        now = time.monotonic()
        key = ("example.com", int(QTYPE.A), 1)
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=b"x",
                expires_at=now + 10,
                stale_until=now + 40,
                rcode=0,
                hits=4,
            ),
        )

        await handler._refresh_scan_tick()
        assert handler.refresh_queue.qsize() == 0

    asyncio.run(run())


def test_hybrid_gate_allows_when_ttl_low_and_hits_high():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        handler = DnsHandler(
            upstream=GateUpstream(asyncio.Event(), asyncio.Event()),
            cache=cache,
            config=HandlerConfig(
                refresh_enabled=True,
                refresh_ahead_seconds=30,
                refresh_popularity_threshold=5,
                refresh_batch_size=10,
            ),
        )
        now = time.monotonic()
        key = ("example.com", int(QTYPE.A), 1)
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=b"x",
                expires_at=now + 10,
                stale_until=now + 40,
                rcode=0,
                hits=5,
            ),
        )

        await handler._refresh_scan_tick()
        assert handler.refresh_queue.qsize() == 1
        assert ("example.com", int(QTYPE.A), 1) in handler.queued_keys

    asyncio.run(run())


def test_refresh_scan_preserves_qclass():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        handler = DnsHandler(
            upstream=GateUpstream(asyncio.Event(), asyncio.Event()),
            cache=cache,
            config=HandlerConfig(
                refresh_enabled=True,
                refresh_ahead_seconds=30,
                refresh_popularity_threshold=1,
                refresh_batch_size=10,
            ),
        )
        now = time.monotonic()
        key = ("example.com", int(QTYPE.A), 3)
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=b"x",
                expires_at=now + 10,
                stale_until=now + 40,
                rcode=0,
                hits=5,
                last_hit_mono=now,
            ),
        )

        await handler._refresh_scan_tick()
        assert handler.refresh_queue.qsize() == 1
        assert key in handler.queued_keys
        queued_key, reason = handler.refresh_queue.get_nowait()
        assert queued_key == key
        assert reason == "tick"

    asyncio.run(run())


def test_hybrid_gate_blocks_when_decay_window_elapsed():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        handler = DnsHandler(
            upstream=GateUpstream(asyncio.Event(), asyncio.Event()),
            cache=cache,
            config=HandlerConfig(
                refresh_enabled=True,
                refresh_ahead_seconds=30,
                refresh_popularity_threshold=5,
                refresh_popularity_decay_seconds=30,
                refresh_batch_size=10,
            ),
        )
        now = time.monotonic()
        key = ("example.com", int(QTYPE.A), 1)
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=b"x",
                expires_at=now + 10,
                stale_until=now + 40,
                rcode=0,
                hits=10,
                last_hit_mono=now - 60,
            ),
        )

        await handler._refresh_scan_tick()
        assert handler.refresh_queue.qsize() == 0

    asyncio.run(run())


def test_refresh_never_blocks_foreground_cache_hit():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        gate = asyncio.Event()
        started = asyncio.Event()
        handler = DnsHandler(
            upstream=GateUpstream(gate, started),
            cache=cache,
            config=HandlerConfig(
                refresh_enabled=True,
                refresh_concurrency=1,
                refresh_queue_max=4,
            ),
        )

        req = DNSRecord.question("example.com", qtype="A")
        now = time.monotonic()
        key = ("example.com", int(QTYPE.A), 1)
        cached = _make_response(req.pack(), "1.2.3.4")
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=cached,
                expires_at=now + 60,
                stale_until=now + 120,
                rcode=0,
                hits=10,
            ),
        )

        handler.enqueue_refresh((key[0], key[1], 1), reason="tick")
        handler.start_refresh_tasks()

        await asyncio.wait_for(started.wait(), timeout=0.2)
        resp = await asyncio.wait_for(handler.handle(req, ("127.0.0.1", 5353)), timeout=0.1)
        assert resp.pack() == cached

        gate.set()
        await asyncio.wait_for(handler.refresh_queue.join(), timeout=0.5)
        await handler.stop_refresh_tasks()

    asyncio.run(run())


def test_worker_cleans_inflight_on_failure():
    async def run():
        metrics = Metrics()
        cache = MemoryDnsCache(CacheConfig())
        started = asyncio.Event()
        handler = DnsHandler(
            upstream=FailingUpstream(started),
            cache=cache,
            metrics=metrics,
            config=HandlerConfig(
                refresh_enabled=True,
                refresh_concurrency=1,
                refresh_queue_max=4,
            ),
        )

        req = DNSRecord.question("example.com", qtype="A")
        now = time.monotonic()
        key = ("example.com", int(QTYPE.A), 1)
        cached = _make_response(req.pack(), "1.2.3.4")
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=cached,
                expires_at=now + 60,
                stale_until=now + 120,
                rcode=0,
                hits=10,
            ),
        )

        refresh_key = key
        handler.enqueue_refresh(refresh_key, reason="tick")
        handler.start_refresh_tasks()

        await asyncio.wait_for(started.wait(), timeout=0.2)
        await asyncio.wait_for(handler.refresh_queue.join(), timeout=0.5)

        assert refresh_key not in handler.inflight_keys
        snapshot = metrics.snapshot()
        assert snapshot.get("cache_refresh_started_total") == 1
        assert snapshot.get("cache_refresh_completed_total{result=fail}") == 1

        await handler.stop_refresh_tasks()

    asyncio.run(run())
