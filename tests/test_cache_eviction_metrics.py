from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.metrics import Metrics


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


def _key(qname: str) -> tuple[str, int, int]:
    return (qname.rstrip(".").lower(), int(QTYPE.A), 1)


def test_evictions_and_cache_entries_metrics():
    metrics = Metrics()
    cache = MemoryDnsCache(CacheConfig(max_entries=1), metrics=metrics)
    cache.put(_key("a.example"), _make_response("a.example", "1.1.1.1"))
    cache.put(_key("b.example"), _make_response("b.example", "2.2.2.2"))

    snap = metrics.snapshot()
    assert snap.get("evictions_total", 0) == 1
    assert snap.get("cache_entries", 0) == 1
