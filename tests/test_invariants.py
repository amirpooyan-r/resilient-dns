import asyncio
import socket
import time

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.cache.memory import CacheConfig, CacheEntry, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler
from resilientdns.dns.server import UdpDnsServer, UdpServerConfig
from resilientdns.metrics import Metrics


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


class BlockingHandler:
    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    async def handle(self, request: DNSRecord, client_addr):
        await self._gate.wait()
        return request.reply()


class FailingUpstream:
    def __init__(self, started: asyncio.Event, finished: asyncio.Event) -> None:
        self.started = started
        self.finished = finished
        self.calls = 0

    async def query(self, wire: bytes):
        self.calls += 1
        self.started.set()
        try:
            raise RuntimeError("boom")
        finally:
            self.finished.set()


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


def _cache_key(request: DNSRecord) -> tuple[str, int]:
    qname = str(request.q.qname).rstrip(".").lower()
    return (qname, int(request.q.qtype))


def test_invariant_txid_rewrite_on_cache_hit():
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


def test_invariant_saturation_is_drop_not_upstream_error():
    async def run():
        metrics = Metrics()
        gate = asyncio.Event()
        handler = BlockingHandler(gate)
        server = UdpDnsServer(
            UdpServerConfig(host="127.0.0.1", port=0, max_inflight=1),
            handler=handler,
            metrics=metrics,
        )
        payload = DNSRecord.question("example.com", qtype="A").pack()

        server.datagram_received(payload, ("127.0.0.1", 5353))
        server.datagram_received(payload, ("127.0.0.1", 5353))

        gate.set()
        if server._inflight:
            await asyncio.gather(*list(server._inflight), return_exceptions=True)

        snap = metrics.snapshot()
        assert snap.get("dropped_total", 0) >= 1
        assert snap.get("upstream_requests_total", 0) == 0
        assert snap.get("upstream_udp_errors_total", 0) == 0
        assert snap.get("upstream_tcp_errors_total", 0) == 0

    asyncio.run(run())


def test_invariant_serve_stale_does_not_block_on_refresh_failure():
    async def run():
        metrics = Metrics()
        cache = MemoryDnsCache(CacheConfig(serve_stale_max_s=60), metrics=metrics)
        started = asyncio.Event()
        finished = asyncio.Event()
        upstream = FailingUpstream(started, finished)
        handler = DnsHandler(upstream=upstream, cache=cache, metrics=metrics)

        request = DNSRecord.question("example.com", qtype="A")
        key = _cache_key(request)
        stale_response = _make_response(request.pack(), "1.2.3.4")
        now = time.monotonic()
        cache._put_entry_for_test(
            key,
            CacheEntry(
                response_wire=stale_response,
                expires_at=now - 10,
                stale_until=now + 60,
                rcode=0,
            ),
        )

        resp = await handler.handle(request, ("127.0.0.1", 5353))
        assert resp.pack() == stale_response

        await asyncio.wait_for(started.wait(), timeout=0.1)
        await asyncio.wait_for(finished.wait(), timeout=0.1)

        snap = metrics.snapshot()
        assert snap.get("cache_hit_stale_total", 0) == 1
        assert snap.get("upstream_fail_total", 0) == 1
        assert snap.get("dropped_total", 0) == 0

    asyncio.run(run())


def test_no_upstream_attempt_after_max_inflight_drop():
    async def run():
        metrics = Metrics()
        gate = asyncio.Event()
        started = asyncio.Event()
        drop_event = asyncio.Event()

        class CountingUpstream:
            def __init__(self, metrics: Metrics):
                self.calls = 0
                self._metrics = metrics

            async def query(self, wire: bytes):
                self.calls += 1
                self._metrics.inc("upstream_requests_total")
                return None

        upstream = CountingUpstream(metrics)
        cache = MemoryDnsCache(CacheConfig(), metrics=metrics)
        handler = DnsHandler(upstream=upstream, cache=cache, metrics=metrics)

        original_handle = handler.handle

        async def blocked_handle(request, client_addr):
            started.set()
            await gate.wait()
            return await original_handle(request, client_addr)

        handler.handle = blocked_handle  # type: ignore[assignment]

        class TestUdpServer(UdpDnsServer):
            def datagram_received(self, data: bytes, addr):
                if self.config.max_inflight > 0 and len(self._inflight) >= self.config.max_inflight:
                    if self.metrics:
                        self.metrics.inc("dropped_total")
                        self.metrics.inc("dropped_max_inflight_total")
                    drop_event.set()
                    return
                return super().datagram_received(data, addr)

        server = TestUdpServer(
            UdpServerConfig(host="127.0.0.1", port=0, max_inflight=1),
            handler=handler,
            metrics=metrics,
        )
        server_task = asyncio.create_task(server.run())
        await server.ready.wait()

        assert server.transport is not None
        host, port = server.transport.get_extra_info("sockname")
        payload = DNSRecord.question("example.com", qtype="A").pack()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(payload, (host, port))
            await asyncio.wait_for(started.wait(), timeout=0.2)
            before = metrics.snapshot().get("upstream_requests_total", 0)
            sock.sendto(payload, (host, port))
            await asyncio.wait_for(drop_event.wait(), timeout=0.2)
            after = metrics.snapshot().get("upstream_requests_total", 0)
        finally:
            gate.set()
            if server._inflight:
                await asyncio.gather(*list(server._inflight), return_exceptions=True)
            server.stop()
            await server_task
            sock.close()

        snap = metrics.snapshot()
        assert snap.get("dropped_total", 0) >= 1
        assert snap.get("dropped_max_inflight_total", 0) >= 1
        assert after == before
        assert upstream.calls == 1

    asyncio.run(run())
