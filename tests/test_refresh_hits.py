import time

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache


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


def test_hits_increment_on_cache_hits_and_stale_served():
    cache = MemoryDnsCache(CacheConfig(serve_stale_max_s=60))
    req = DNSRecord.question("example.com", qtype="A")
    key = ("example.com", int(QTYPE.A), 1)
    wire = _make_response(req.pack(), "1.2.3.4")
    now = time.monotonic()
    cache._put_entry_for_test(
        key,
        CacheEntry(
            response_wire=wire,
            expires_at=now + 60,
            stale_until=now + 120,
            rcode=0,
        ),
    )

    assert cache.get_fresh(key) is not None
    entry = cache.peek(key)
    assert entry is not None
    assert entry.hits == 1
    assert entry.last_hit_mono > 0
    first_hit = entry.last_hit_mono

    entry.expires_at = time.monotonic() - 1
    assert cache.get_stale(key) is not None
    entry = cache.peek(key)
    assert entry is not None
    assert entry.hits == 2
    assert entry.last_hit_mono >= first_hit


def test_hit_cap_is_enforced():
    cache = MemoryDnsCache(CacheConfig())
    req = DNSRecord.question("example.com", qtype="A")
    key = ("example.com", int(QTYPE.A), 1)
    wire = _make_response(req.pack(), "1.2.3.4")
    now = time.monotonic()
    cache._put_entry_for_test(
        key,
        CacheEntry(
            response_wire=wire,
            expires_at=now + 60,
            stale_until=now + 120,
            rcode=0,
        ),
    )

    for _ in range(2000):
        assert cache.get_fresh(key) is not None

    entry = cache.peek(key)
    assert entry is not None
    assert entry.hits <= 1024
