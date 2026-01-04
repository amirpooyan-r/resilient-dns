import time

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache


def _make_response(qname: str, ip: str) -> DNSRecord:
    req = DNSRecord.question(qname, qtype="A")
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
    return reply


def _key(qname: str) -> tuple[str, int]:
    return (qname.rstrip(".").lower(), int(QTYPE.A))


def test_lru_eviction_on_put():
    cache = MemoryDnsCache(CacheConfig(max_entries=2))
    cache.put(_key("a.example"), _make_response("a.example", "1.1.1.1"))
    cache.put(_key("b.example"), _make_response("b.example", "2.2.2.2"))
    cache.put(_key("c.example"), _make_response("c.example", "3.3.3.3"))

    assert cache.get_fresh(_key("a.example")) is None
    assert cache.get_fresh(_key("b.example")) is not None
    assert cache.get_fresh(_key("c.example")) is not None


def test_lru_touch_on_get():
    cache = MemoryDnsCache(CacheConfig(max_entries=2))
    cache.put(_key("a.example"), _make_response("a.example", "1.1.1.1"))
    cache.put(_key("b.example"), _make_response("b.example", "2.2.2.2"))

    assert cache.get_fresh(_key("a.example")) is not None
    cache.put(_key("c.example"), _make_response("c.example", "3.3.3.3"))

    assert cache.get_fresh(_key("b.example")) is None
    assert cache.get_fresh(_key("a.example")) is not None
    assert cache.get_fresh(_key("c.example")) is not None


def test_no_eviction_when_unlimited():
    cache = MemoryDnsCache(CacheConfig(max_entries=0))
    cache.put(_key("a.example"), _make_response("a.example", "1.1.1.1"))
    cache.put(_key("b.example"), _make_response("b.example", "2.2.2.2"))
    cache.put(_key("c.example"), _make_response("c.example", "3.3.3.3"))

    assert cache.get_fresh(_key("a.example")) is not None
    assert cache.get_fresh(_key("b.example")) is not None
    assert cache.get_fresh(_key("c.example")) is not None


def test_expired_entries_evicted_first():
    cache = MemoryDnsCache(CacheConfig(max_entries=2))
    now = time.monotonic()
    cache._put_entry_for_test(
        _key("expired.example"),
        CacheEntry(
            response_wire=b"expired",
            expires_at=now - 20,
            stale_until=now - 10,
            rcode=0,
        ),
    )
    cache._put_entry_for_test(
        _key("valid.example"),
        CacheEntry(
            response_wire=b"valid",
            expires_at=now + 20,
            stale_until=now + 40,
            rcode=0,
        ),
    )
    cache.put(_key("new.example"), _make_response("new.example", "3.3.3.3"))

    assert _key("expired.example") not in cache._store
    assert _key("valid.example") in cache._store
    assert _key("new.example") in cache._store
