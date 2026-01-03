import time
from dataclasses import dataclass
from typing import TypeAlias

from dnslib import RCODE, DNSRecord

from resilientdns.metrics import Metrics


@dataclass(frozen=True)
class CacheConfig:
    # If upstream fails, how long can we serve expired answers?
    serve_stale_max_s: int = 300  # 5 minutes

    # If response is negative (NXDOMAIN/NODATA) and has no SOA MINIMUM, use this TTL.
    negative_ttl_s: int = 60


@dataclass
class CacheEntry:
    response_wire: bytes
    expires_at: float
    stale_until: float
    rcode: int


CacheKey: TypeAlias = tuple[str, int]


class MemoryDnsCache:
    """
    Simple in-memory DNS cache keyed by (qname_lower, qtype_int).
    Stores full wire response bytes.
    """

    def __init__(self, config: CacheConfig, metrics: Metrics | None = None):
        self.config = config
        self.metrics = metrics
        self._store: dict[CacheKey, CacheEntry] = {}

    def get_fresh(self, key: CacheKey) -> bytes | None:
        e = self._store.get(key)
        if not e:
            return None
        now = time.time()
        if now <= e.expires_at:
            self._count_negative(e)
            return e.response_wire
        return None

    def get_stale(self, key: CacheKey) -> bytes | None:
        e = self._store.get(key)
        if not e:
            return None
        now = time.time()
        if e.expires_at < now <= e.stale_until:
            self._count_negative(e)
            return e.response_wire
        return None

    def put(self, key: CacheKey, response: DNSRecord) -> None:
        now = time.time()

        ttl = self._compute_ttl_seconds(response)
        ttl = max(0, ttl)

        expires_at = now + ttl
        stale_until = expires_at + self.config.serve_stale_max_s

        self._store[key] = CacheEntry(
            response_wire=response.pack(),
            expires_at=expires_at,
            stale_until=stale_until,
            rcode=response.header.rcode,
        )

    def _put_entry_for_test(self, key: CacheKey, entry: CacheEntry) -> None:
        """Test helper; not part of public API."""
        self._store[key] = entry

    def _count_negative(self, entry: CacheEntry) -> None:
        if self.metrics and entry.rcode != RCODE.NOERROR:
            self.metrics.inc("negative_cache_hit_total")

    def _compute_ttl_seconds(self, resp: DNSRecord) -> int:
        """
        Best-effort TTL extraction:
        - For positive answers: min TTL of all RR in answer section (rr)
        - For negative responses: use SOA MINIMUM if present, else negative_ttl_s
        """
        rcode = resp.header.rcode

        # Positive: use answer TTLs
        if rcode == RCODE.NOERROR and len(resp.rr) > 0:
            return int(min(r.ttl for r in resp.rr if hasattr(r, "ttl")))

        # Negative or NOERROR with no answers (NODATA): try SOA in authority
        soa_ttls = [int(r.ttl) for r in resp.auth if getattr(r, "rtype", None) == 6]  # SOA=6
        if soa_ttls:
            return min(soa_ttls)

        return self.config.negative_ttl_s
