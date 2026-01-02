import asyncio
import time

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler


class FakeUpstream:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.last_request = None
        self.called = asyncio.Event()

    async def query(self, wire: bytes):
        self.calls += 1
        self.last_request = DNSRecord.parse(wire)
        self.called.set()
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


def test_qtype_mapping_resolves_name():
    cache = MemoryDnsCache(CacheConfig())
    upstream = FakeUpstream([])
    handler = DnsHandler(upstream=upstream, cache=cache)
    request = DNSRecord.question("example.com", qtype="A")

    q = request.questions[0]
    qtype_id, qtype_name = handler._qtype_mapping(q.qtype)

    assert qtype_id == 1
    assert qtype_name == "A"


def test_swr_refresh_builds_query_with_qtype_name():
    async def run():
        cache = MemoryDnsCache(CacheConfig(serve_stale_max_s=60))
        upstream = FakeUpstream([lambda wire: _make_response(wire, "5.6.7.8")])
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

        await asyncio.wait_for(upstream.called.wait(), timeout=0.2)
        assert upstream.calls == 1
        assert int(upstream.last_request.q.qtype) == int(QTYPE.A)

    asyncio.run(run())
