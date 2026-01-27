import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from dnslib import CLASS, QTYPE, RCODE, DNSRecord

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
    refresh_queue_max: int = 1024
    refresh_enabled: bool = False
    refresh_ahead_seconds: int = 30
    refresh_popularity_threshold: int = 5
    refresh_popularity_decay_seconds: int = 0
    refresh_tick_ms: int = 500
    refresh_batch_size: int = 50
    refresh_concurrency: int = 5


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
        self.refresh_queue: asyncio.Queue[tuple[tuple[str, int, int], str]] = asyncio.Queue(
            maxsize=self.config.refresh_queue_max
        )
        self.queued_keys: set[tuple[str, int, int]] = set()
        self.inflight_keys: set[tuple[str, int, int]] = set()
        self._refresh_tasks: list[asyncio.Task] = []

    async def handle(self, request: DNSRecord, client_addr) -> DNSRecord:
        if not request.questions:
            reply = request.reply()
            reply.header.rcode = RCODE.FORMERR
            return reply

        q = request.questions[0]
        qname = str(q.qname).rstrip(".").lower()
        qclass_id = int(q.qclass)

        if self.metrics:
            self.metrics.inc("queries_total")

        qtype_id, qtype_name = self._qtype_mapping(q.qtype)
        key: tuple[str, int, int] = (qname, qtype_id, qclass_id)
        refresh_key: tuple[str, int, int] = key

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
            self.enqueue_refresh(refresh_key, reason="stale_served")
            await self._schedule_refresh(key, qname, qtype_name, refresh_key)
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
            self.enqueue_refresh(refresh_key, reason="stale_served")
            await self._schedule_refresh(key, qname, qtype_name, refresh_key)
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

    def start_refresh_tasks(self) -> list[asyncio.Task]:
        if not self.config.refresh_enabled:
            return []
        if self._refresh_tasks:
            return list(self._refresh_tasks)
        self._refresh_tasks.append(asyncio.create_task(self._refresh_scan_loop()))
        for i in range(self.config.refresh_concurrency):
            self._refresh_tasks.append(asyncio.create_task(self._refresh_worker(i)))
        return list(self._refresh_tasks)

    async def stop_refresh_tasks(self) -> None:
        if not self._refresh_tasks:
            return
        for task in self._refresh_tasks:
            task.cancel()
        for task in self._refresh_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._refresh_tasks.clear()

    def _with_txid(self, request: DNSRecord, response: DNSRecord) -> DNSRecord:
        response.header.id = request.header.id
        return response

    async def _resolve_upstream(
        self, request: DNSRecord, key: tuple[str, int, int], qname: str, qtype_name: str
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

    def enqueue_refresh(self, key: tuple[str, int, int], reason: str) -> bool:
        if key in self.queued_keys or key in self.inflight_keys:
            if self.metrics:
                self.metrics.inc("cache_refresh_dropped_total{reason=duplicate}")
            return False
        if self.refresh_queue.full():
            if self.metrics:
                self.metrics.inc("cache_refresh_dropped_total{reason=queue_full}")
            return False
        self.refresh_queue.put_nowait((key, reason))
        self.queued_keys.add(key)
        if self.metrics:
            self.metrics.inc("cache_refresh_enqueued_total")
        return True

    async def _refresh_scan_loop(self) -> None:
        tick_s = max(0.0, self.config.refresh_tick_ms / 1000.0)
        try:
            while True:
                await asyncio.sleep(tick_s)
                await self._refresh_scan_tick()
        except asyncio.CancelledError:
            raise

    async def _refresh_scan_tick(self) -> None:
        now = time.monotonic()
        enqueued = 0
        entries = self.cache.entries_snapshot()
        for (qname, qtype_id, qclass_id), entry in entries:
            remaining = entry.expires_at - now
            if remaining < 0:
                continue
            if remaining > self.config.refresh_ahead_seconds:
                continue
            if entry.hits < self.config.refresh_popularity_threshold:
                continue
            if self.config.refresh_popularity_decay_seconds > 0:
                if entry.last_hit_mono <= 0:
                    continue
                if (now - entry.last_hit_mono) > self.config.refresh_popularity_decay_seconds:
                    continue
            refresh_key = (qname, qtype_id, qclass_id)
            if self.enqueue_refresh(refresh_key, reason="tick"):
                enqueued += 1
                if enqueued >= self.config.refresh_batch_size:
                    break
            if self.refresh_queue.full():
                break

    async def _refresh_worker(self, _worker_id: int) -> None:
        try:
            while True:
                refresh_key, _reason = await self.refresh_queue.get()
                self.queued_keys.discard(refresh_key)
                self.inflight_keys.add(refresh_key)
                cancelled = False
                attempted = False
                result = "skipped"
                try:
                    attempted, result = await self._refresh_via_worker(refresh_key)
                except asyncio.CancelledError:
                    cancelled = True
                    raise
                except Exception:
                    logger.exception("REFRESH WORKER ERROR %s", refresh_key)
                    attempted = True
                    result = "fail"
                finally:
                    if attempted and self.metrics:
                        self.metrics.inc("cache_refresh_started_total")
                    if not cancelled and self.metrics:
                        self.metrics.inc(f"cache_refresh_completed_total{{result={result}}}")
                    self.inflight_keys.discard(refresh_key)
                    self.refresh_queue.task_done()
        except asyncio.CancelledError:
            raise

    async def _schedule_refresh(
        self,
        key: tuple[str, int, int],
        qname: str,
        qtype_name: str,
        refresh_key: tuple[str, int, int],
    ) -> None:
        # Refresh is deduped too
        task, leader = await self._sf.get_or_create(
            ("refresh", key),
            lambda: self._refresh_once_tracked(key, qname, qtype_name, refresh_key),
        )
        if leader:
            if self.metrics:
                self.metrics.inc("swr_refresh_triggered_total")
            logger.info("REFRESH START %s %s", qname, qtype_name)
            asyncio.create_task(self._watch_refresh(task, qname, qtype_name))

    async def _refresh_once_tracked(
        self,
        key: tuple[str, int, int],
        qname: str,
        qtype_name: str,
        refresh_key: tuple[str, int, int],
    ) -> DNSRecord | None:
        self.queued_keys.discard(refresh_key)
        self.inflight_keys.add(refresh_key)
        try:
            return await self._refresh_once(key, qname, qtype_name)
        finally:
            self.inflight_keys.discard(refresh_key)

    async def _refresh_via_worker(self, refresh_key: tuple[str, int, int]) -> tuple[bool, str]:
        if not self.config.refresh_enabled:
            return False, "skipped"
        qname, qtype_id, qclass_id = refresh_key
        cache_key = (qname, qtype_id, qclass_id)
        entry = self.cache.peek(cache_key)
        if entry is None:
            return False, "skipped"
        now = time.monotonic()
        remaining = entry.expires_at - now
        if remaining < 0:
            return False, "skipped"
        if remaining > self.config.refresh_ahead_seconds:
            return False, "skipped"
        if entry.hits < self.config.refresh_popularity_threshold:
            return False, "skipped"
        if self.config.refresh_popularity_decay_seconds > 0:
            if entry.last_hit_mono <= 0:
                return False, "skipped"
            if (now - entry.last_hit_mono) > self.config.refresh_popularity_decay_seconds:
                return False, "skipped"
        try:
            qtype_name = QTYPE[qtype_id]
        except Exception:
            qtype_name = str(qtype_id)
        try:
            try:
                qclass_name = CLASS[qclass_id]
            except Exception:
                qclass_name = str(qclass_id)
            request = DNSRecord.question(qname, qtype_name, qclass_name)
        except Exception:
            return True, "fail"
        task, _leader = await self._sf.get_or_create(
            cache_key, lambda: self._resolve_upstream(request, cache_key, qname, qtype_name)
        )
        resp = await task
        if resp is None:
            return True, "fail"
        return True, "success"

    async def _refresh_once(
        self, key: tuple[str, int, int], qname: str, qtype_name: str
    ) -> DNSRecord | None:
        # Build a fresh query for this (qname, qtype_name, qclass)
        try:
            qclass_id = key[2]
            try:
                qclass_name = CLASS[qclass_id]
            except Exception:
                qclass_name = str(qclass_id)
            new_req = DNSRecord.question(qname, qtype_name, qclass_name)
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
