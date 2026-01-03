import asyncio

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler


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


def test_cache_hit_txid_rewrite():
    async def run():
        cache = MemoryDnsCache(CacheConfig())
        upstream = FakeUpstream([lambda wire: _make_response(wire, "1.2.3.4")])
        handler = DnsHandler(upstream=upstream, cache=cache)

        req1 = DNSRecord.question("example.com", qtype="A")
        req1.header.id = 0x1234
        resp1 = await handler.handle(req1, ("127.0.0.1", 5353))
        assert resp1.header.id == req1.header.id

        req2 = DNSRecord.question("example.com", qtype="A")
        req2.header.id = 0x5678
        resp2 = await handler.handle(req2, ("127.0.0.1", 5353))

        assert upstream.calls == 1
        assert resp2.header.id == req2.header.id
        assert resp2.rr[0].rdata == resp1.rr[0].rdata

    asyncio.run(run())
