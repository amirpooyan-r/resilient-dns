import asyncio
import logging
from dataclasses import dataclass

from dnslib import QTYPE, RCODE, DNSRecord

from resilientdns.cache.memory import MemoryDnsCache
from resilientdns.dns.singleflight import SingleFlight
from resilientdns.metrics import Metrics

logger = logging.getLogger("resilientdns")


@dataclass(frozen=True)
class HandlerConfig:
    # How long we wait for a single upstream query (in seconds) during normal misses
    upstream_timeout_s: float = 2.0

    # If serving stale, how long we wait before declaring refresh "failed" (log only)
    refresh_watch_timeout_s: float = 5.0


class DnsHandler:
    """
    Handler implementing:
    - TTL-aware cache (via MemoryDnsCache)
    - Negative caching (via MemoryDnsCache)
    - Serve-stale on upstream failure
    - Stale-while-revalidate (SWR): serve stale immediately and refresh in background
    - SingleFlight: deduplicate concurrent misses and concurrent refreshes per key
    """

    def __init__(
        self,
        upstream: object,
        cache: MemoryDnsCache,
        config: HandlerConfig | None = None,
        metrics: Metrics | None = None,
    ):
        self.upstream = upstream
        self.cache = cache
        self.config = config or HandlerConfig()
        self.metrics = metrics
        self._sf = SingleFlight(metrics=metrics)

    async def handle(self, request: DNSRecord, client_addr) -> DNSRecord:
        if not request.questions:
            reply = request.reply()
            reply.header.rcode = RCODE.FORMERR
            return reply

        q = request.questions[0]
        qname = str(q.qname).rstrip(".").lower()

        if self.metrics:
            self.metrics.inc("queries_total")

        qtype_id, qtype_name = self._qtype_mapping(q.qtype)
        key: tuple[str, int] = (qname, qtype_id)

        # 1) Fresh cache
        fresh = self.cache.get_fresh(key)
        if fresh:
            logger.info("CACHE HIT (fresh) %s %s", qname, qtype_name)
            if self.metrics:
                self.metrics.inc("cache_hit_fresh_total")
            return self._with_txid(request, DNSRecord.parse(fresh))

        # 2) Stale cache => serve immediately and refresh in background
        stale = self.cache.get_stale(key)
        if stale:
            logger.info("CACHE HIT (stale) %s %s (refresh scheduled)", qname, qtype_name)
            if self.metrics:
                self.metrics.inc("cache_hit_stale_total")
            await self._schedule_refresh(key, qname, qtype_name)
            return self._with_txid(request, DNSRecord.parse(stale))

        # 3) Cache miss => singleflight upstream resolve
        if self.metrics:
            self.metrics.inc("cache_miss_total")

        task, leader = await self._sf.get_or_create(
            key, lambda: self._resolve_upstream(request, key, qname, qtype_name)
        )
        if leader:
            logger.info("CACHE MISS (leader) %s %s", qname, qtype_name)
        else:
            logger.info("CACHE MISS (join) %s %s", qname, qtype_name)

        try:
            resp = await task
        except Exception:
            logger.exception("UPSTREAM ERROR %s %s", qname, qtype_name)
            resp = None

        if resp is not None:
            return self._with_txid(request, resp)

        # 4) Upstream failed: if stale appeared meanwhile, serve it
        stale2 = self.cache.get_stale(key)
        if stale2:
            logger.warning("SERVE STALE (late) %s %s", qname, qtype_name)
            if self.metrics:
                self.metrics.inc("cache_hit_stale_total")
            await self._schedule_refresh(key, qname, qtype_name)
            return self._with_txid(request, DNSRecord.parse(stale2))

        reply = request.reply()
        reply.header.rcode = RCODE.SERVFAIL
        return self._with_txid(request, reply)

    def _qtype_mapping(self, qtype) -> tuple[int, str]:
        # Cache key uses integer qtype; dnslib APIs want the string name ("A", "AAAA", ...)
        qtype_id = int(qtype)
        try:
            qtype_name = QTYPE[qtype_id]  # reverse lookup: 1 -> "A"
        except Exception:
            qtype_name = str(qtype)  # fallback (shouldn't happen)
        return qtype_id, qtype_name

    def _with_txid(self, request: DNSRecord, response: DNSRecord) -> DNSRecord:
        response.header.id = request.header.id
        return response

    async def _resolve_upstream(
        self, request: DNSRecord, key: tuple[str, int], qname: str, qtype_name: str
    ) -> DNSRecord | None:
        resp_bytes = await self._query_upstream(
            request.pack(),
            qname,
            qtype_name,
            request_id=str(request.header.id),
        )
        if resp_bytes is None:
            return None

        try:
            resp = DNSRecord.parse(resp_bytes)
        except Exception:
            logger.exception("UPSTREAM PARSE FAIL %s %s", qname, qtype_name)
            return None

        self.cache.put(key, resp)
        logger.info("UPSTREAM OK %s %s (cached)", qname, qtype_name)
        return resp

    async def _schedule_refresh(self, key: tuple[str, int], qname: str, qtype_name: str) -> None:
        # Refresh is deduped too
        task, leader = await self._sf.get_or_create(
            ("refresh", key), lambda: self._refresh_once(key, qname, qtype_name)
        )
        if leader:
            if self.metrics:
                self.metrics.inc("swr_refresh_triggered_total")
            logger.info("REFRESH START %s %s", qname, qtype_name)
            asyncio.create_task(self._watch_refresh(task, qname, qtype_name))

    async def _refresh_once(
        self, key: tuple[str, int], qname: str, qtype_name: str
    ) -> DNSRecord | None:
        # Build a fresh query for this (qname, qtype_name)
        try:
            new_req = DNSRecord.question(qname, qtype_name)
        except Exception:
            logger.exception("REFRESH BUILD FAIL %s %s", qname, qtype_name)
            return None

        refresh_id = f"refresh-{qname}-{qtype_name}"
        resp_bytes = await self._query_upstream(
            new_req.pack(),
            qname,
            qtype_name,
            request_id=refresh_id,
        )
        if resp_bytes is None:
            return None

        try:
            resp = DNSRecord.parse(resp_bytes)
        except Exception:
            logger.exception("REFRESH PARSE FAIL %s %s", qname, qtype_name)
            return None

        self.cache.put(key, resp)
        return resp

    async def _watch_refresh(self, task: asyncio.Task, qname: str, qtype_name: str) -> None:
        try:
            resp = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=self.config.refresh_watch_timeout_s,
            )
            if resp is None:
                logger.error("REFRESH FAIL %s %s", qname, qtype_name)
            else:
                logger.info("REFRESH OK %s %s (updated cache)", qname, qtype_name)
        except asyncio.TimeoutError:
            logger.error("REFRESH TIMEOUT %s %s", qname, qtype_name)
        except Exception:
            logger.exception("REFRESH ERROR %s %s", qname, qtype_name)

    async def _query_upstream(
        self,
        wire: bytes,
        qname: str,
        qtype_name: str,
        request_id: str | None = None,
    ) -> bytes | None:
        try:
            if request_id is None:
                resp = await self.upstream.query(wire)
            else:
                try:
                    resp = await self.upstream.query(wire, request_id=request_id)
                except TypeError:
                    resp = await self.upstream.query(wire)
        except asyncio.TimeoutError:
            logger.warning("UPSTREAM TIMEOUT %s %s", qname, qtype_name)
            resp = None
        except Exception:
            logger.exception("UPSTREAM ERROR %s %s", qname, qtype_name)
            resp = None

        if resp is None:
            if self.metrics:
                self.metrics.inc("upstream_fail_total")
            return None

        return resp
