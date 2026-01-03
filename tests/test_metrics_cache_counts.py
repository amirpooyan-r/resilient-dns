import asyncio
import time

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler
from resilientdns.metrics import Metrics


class FakeUpstream:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def query(self, wire: bytes):
        self.calls += 1
        if not self._responses:
            return None
        resp = self._responses.pop(0)
        if callable(resp):
            resp = resp(wire)
        return resp


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


def test_metrics_cache_counts():
    async def run():
        metrics = Metrics()
        cache = MemoryDnsCache(CacheConfig(), metrics=metrics)
        upstream = FakeUpstream(
            [
                lambda wire: _make_response(wire, "1.2.3.4"),
                lambda wire: _make_response(wire, "5.6.7.8"),
            ]
        )
        handler = DnsHandler(upstream=upstream, cache=cache, metrics=metrics)
        request = DNSRecord.question("example.com", qtype="A")

        await handler.handle(request, ("127.0.0.1", 5353))
        snap = metrics.snapshot()
        assert snap.get("cache_miss_total", 0) == 1
        assert snap.get("cache_hit_fresh_total", 0) == 0
        assert snap.get("cache_hit_stale_total", 0) == 0
        assert snap.get("queries_total", 0) == 1

        await handler.handle(request, ("127.0.0.1", 5353))
        snap = metrics.snapshot()
        assert snap.get("cache_hit_fresh_total", 0) == 1
        assert snap.get("cache_miss_total", 0) == 1
        assert snap.get("queries_total", 0) == 2

        qname = str(request.q.qname).rstrip(".").lower()
        key = (qname, int(QTYPE.A))
        stale_response = _make_response(request.pack(), "9.9.9.9")
        now = time.time()
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=stale_response,
                expires_at=now - 10,
                stale_until=now + 60,
                rcode=0,
            ),
        )

        await handler.handle(request, ("127.0.0.1", 5353))
        snap = metrics.snapshot()
        assert snap.get("cache_hit_stale_total", 0) == 1
        assert snap.get("cache_miss_total", 0) == 1
        assert snap.get("queries_total", 0) == 3

    asyncio.run(run())
