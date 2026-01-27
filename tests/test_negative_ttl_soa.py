import time

from dnslib import QTYPE, RCODE, RR, SOA, DNSRecord

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache


def test_negative_ttl_uses_soa_minimum():
    cache = MemoryDnsCache(CacheConfig(negative_ttl_s=60))
    req = DNSRecord.question("example.com", qtype="A")
    reply = req.reply()
    reply.header.rcode = RCODE.NXDOMAIN

    soa = SOA(
        mname="ns.example.com.",
        rname="hostmaster.example.com.",
        times=(1, 2, 3, 4, 42),
    )
    reply.add_auth(
        RR(
            rname=req.q.qname,
            rtype=QTYPE.SOA,
            rclass=1,
            ttl=300,
            rdata=soa,
        )
    )

    qname = str(req.q.qname).rstrip(".").lower()
    key = (qname, int(QTYPE.A), 1)
    now = time.monotonic()
    cache.put(key, reply)
    entry = cache._store[key]

    delta = entry.expires_at - now
    assert abs(delta - 42) <= 1.0
