import asyncio
import time

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler


class StubUpstream:
    def __init__(self, response_factory, delay_s=0.0, gate=None, started=None):
        self._response_factory = response_factory
        self._delay_s = delay_s
        self._gate = gate
        self._started = started
        self.calls = 0

    async def query(self, wire: bytes):
        self.calls += 1
        if self._started is not None:
            self._started.set()
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._gate is not None:
            await self._gate.wait()
        return self._response_factory(wire)


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


def test_singleflight_dedupes_concurrent_misses():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        upstream = StubUpstream(lambda wire: _make_response(wire, "1.2.3.4"), delay_s=0.05)
        handler = DnsHandler(upstream=upstream, cache=cache)
        request = DNSRecord.question("example.com", qtype="A")

        t1 = asyncio.create_task(handler.handle(request, ("127.0.0.1", 5353)))
        t2 = asyncio.create_task(handler.handle(request, ("127.0.0.1", 5353)))
        r1, r2 = await asyncio.gather(t1, t2)

        assert upstream.calls == 1
        assert r1.pack() == r2.pack()

    asyncio.run(run())


def test_stale_while_revalidate_refreshes_in_background():
    async def run():
        cache = MemoryDnsCache(CacheConfig(serve_stale_max_s=60))
        started = asyncio.Event()
        gate = asyncio.Event()
        upstream = StubUpstream(
            lambda wire: _make_response(wire, "5.6.7.8"),
            gate=gate,
            started=started,
        )
        handler = DnsHandler(upstream=upstream, cache=cache)
        request = DNSRecord.question("example.com", qtype="A")

        qname = "example.com"
        key = (qname, int(QTYPE.A))
        stale_response = _make_response(request.pack(), "1.2.3.4")
        now = time.time()
        cache._store[key] = CacheEntry(
            response_wire=stale_response,
            expires_at=now - 10,
            stale_until=now + 60,
            rcode=0,
        )

        resp = await asyncio.wait_for(handler.handle(request, ("127.0.0.1", 5353)), timeout=0.1)
        assert resp.pack() == stale_response

        await asyncio.wait_for(started.wait(), timeout=0.1)
        assert upstream.calls == 1

        gate.set()
        for _ in range(50):
            fresh = cache.get_fresh(key)
            if fresh is not None:
                break
            await asyncio.sleep(0.01)

        fresh_wire = cache.get_fresh(key)
        assert fresh_wire is not None
        fresh = DNSRecord.parse(fresh_wire)
        assert fresh.header.rcode == 0
        assert fresh.rr
        assert str(fresh.rr[0].rdata) == "5.6.7.8"

    asyncio.run(run())
