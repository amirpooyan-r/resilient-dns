import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TypeAlias

from dnslib import RCODE, DNSRecord

from resilientdns.metrics import Metrics

_HIT_CAP = 1024


@dataclass(frozen=True)
class CacheConfig:
    # If upstream fails, how long can we serve expired answers?
    serve_stale_max_s: int = 300  # 5 minutes

    # If response is negative (NXDOMAIN/NODATA) and has no SOA MINIMUM, use this TTL.
    negative_ttl_s: int = 60
    max_entries: int = 0


@dataclass
class CacheEntry:
    response_wire: bytes
    expires_at: float
    stale_until: float
    rcode: int
    hits: int = 0
    last_hit_mono: float = 0.0


CacheKey: TypeAlias = tuple[str, int]


class MemoryDnsCache:
    """
    Simple in-memory DNS cache keyed by (qname_lower, qtype_int).
    Stores full wire response bytes.
    """

    def __init__(self, config: CacheConfig, metrics: Metrics | None = None):
        self.config = config
        self.metrics = metrics
        self._store: OrderedDict[CacheKey, CacheEntry] = OrderedDict()

    def get_fresh(self, key: CacheKey) -> bytes | None:
        e = self._store.get(key)
        if not e:
            return None
        now = time.monotonic()
        if now <= e.expires_at:
            e.hits = min(_HIT_CAP, e.hits + 1)
            e.last_hit_mono = now
            self._count_negative(e)
            self._touch(key)
            return e.response_wire
        return None

    def get_stale(self, key: CacheKey) -> bytes | None:
        e = self._store.get(key)
        if not e:
            return None
        now = time.monotonic()
        if e.expires_at < now <= e.stale_until:
            e.hits = min(_HIT_CAP, e.hits + 1)
            e.last_hit_mono = now
            self._count_negative(e)
            self._touch(key)
            return e.response_wire
        return None

    def peek(self, key: CacheKey) -> CacheEntry | None:
        return self._store.get(key)

    def entries_snapshot(self) -> list[tuple[CacheKey, CacheEntry]]:
        return list(self._store.items())

    def put(self, key: CacheKey, response: DNSRecord) -> None:
        now = time.monotonic()

        ttl = self._compute_ttl_seconds(response)
        ttl = max(0, ttl)

        expires_at = now + ttl
        stale_until = expires_at + self.config.serve_stale_max_s

        self._store[key] = CacheEntry(
            response_wire=response.pack(),
            expires_at=expires_at,
            stale_until=stale_until,
            rcode=response.header.rcode,
            hits=0,
            last_hit_mono=0.0,
        )
        self._touch(key)
        self._evict_if_needed()
        self._update_cache_entries()

    def _put_entry_for_test(self, key: CacheKey, entry: CacheEntry) -> None:
        """Test helper; not part of public API."""
        self._store[key] = entry
        self._touch(key)
        self._update_cache_entries()

    def _count_negative(self, entry: CacheEntry) -> None:
        if self.metrics and entry.rcode != RCODE.NOERROR:
            self.metrics.inc("negative_cache_hit_total")

    def _touch(self, key: CacheKey) -> None:
        if key in self._store:
            self._store.move_to_end(key)

    def _evict_if_needed(self) -> None:
        if self.config.max_entries == 0:
            return
        if len(self._store) <= self.config.max_entries:
            return
        now = time.monotonic()
        for key, entry in list(self._store.items()):
            if len(self._store) <= self.config.max_entries:
                return
            if now > entry.stale_until:
                if self._store.pop(key, None) is not None:
                    if self.metrics:
                        self.metrics.inc("evictions_total")
        while len(self._store) > self.config.max_entries:
            self._store.popitem(last=False)
            if self.metrics:
                self.metrics.inc("evictions_total")

    def _update_cache_entries(self) -> None:
        if self.metrics:
            self.metrics.set("cache_entries", len(self._store))

    def stats_snapshot(self) -> dict[str, int]:
        now = time.monotonic()
        expired_total = 0
        stale_servable_total = 0
        fresh_total = 0
        negative_total = 0
        for entry in self._store.values():
            if entry.expires_at <= now:
                expired_total += 1
                if entry.expires_at < now <= entry.stale_until:
                    stale_servable_total += 1
            else:
                fresh_total += 1
            if entry.rcode != RCODE.NOERROR:
                negative_total += 1

        evictions_total = 0
        if self.metrics:
            evictions_total = self.metrics.snapshot().get("evictions_total", 0)

        return {
            "entries_total": len(self._store),
            "expired_total": expired_total,
            "stale_servable_total": stale_servable_total,
            "fresh_total": fresh_total,
            "negative_total": negative_total,
            "evictions_total": evictions_total,
        }

    def clear(self) -> None:
        self._store.clear()
        if self.metrics:
            self.metrics.set("cache_entries", 0)
            self.metrics.inc("cache_clears_total")

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

        # Negative or NOERROR with no answers (NODATA): try SOA MINIMUM in authority
        for r in resp.auth:
            if getattr(r, "rtype", None) == 6:  # SOA=6
                soa_rdata = getattr(r, "rdata", None)
                minttl = getattr(soa_rdata, "minttl", None)
                if minttl is None:
                    times = getattr(soa_rdata, "times", None)
                    if isinstance(times, (list, tuple)) and len(times) >= 5:
                        minttl = times[4]
                if minttl is not None:
                    return int(minttl)

        return self.config.negative_ttl_s
