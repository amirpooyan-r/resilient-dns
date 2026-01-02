import asyncio

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler
from resilientdns.metrics import Metrics


class StubUpstream:
    def __init__(self, response_factory, delay_s=0.0):
        self._response_factory = response_factory
        self._delay_s = delay_s
        self.calls = 0

    async def query(self, wire: bytes):
        self.calls += 1
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
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


def test_metrics_singleflight_dedup():
    async def run():
        metrics = Metrics()
        cache = MemoryDnsCache(CacheConfig(), metrics=metrics)
        upstream = StubUpstream(lambda wire: _make_response(wire, "1.2.3.4"), delay_s=0.05)
        handler = DnsHandler(upstream=upstream, cache=cache, metrics=metrics)
        request = DNSRecord.question("example.com", qtype="A")

        t1 = asyncio.create_task(handler.handle(request, ("127.0.0.1", 5353)))
        t2 = asyncio.create_task(handler.handle(request, ("127.0.0.1", 5353)))
        await asyncio.gather(t1, t2)

        snap = metrics.snapshot()
        assert snap.get("singleflight_dedup_total", 0) == 1

    asyncio.run(run())
