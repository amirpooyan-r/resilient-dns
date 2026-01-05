import asyncio

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.metrics import Metrics
from resilientdns.upstream.udp_forwarder import UdpUpstreamForwarder, UpstreamUdpConfig


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


def test_udp_upstream_max_inflight():
    async def run():
        first_received = asyncio.Event()
        unblock = asyncio.Event()
        request_count = 0

        class ServerProtocol(asyncio.DatagramProtocol):
            def connection_made(self, transport: asyncio.DatagramTransport) -> None:
                self.transport = transport

            def datagram_received(self, data: bytes, addr) -> None:
                nonlocal request_count
                request_count += 1
                if request_count == 1:
                    first_received.set()

                    async def delayed_response() -> None:
                        await asyncio.wait_for(unblock.wait(), timeout=0.5)
                        resp = _make_response(data, "1.2.3.4")
                        self.transport.sendto(resp, addr)

                    asyncio.create_task(delayed_response())
                    return
                resp = _make_response(data, "1.2.3.4")
                self.transport.sendto(resp, addr)

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            ServerProtocol, local_addr=("127.0.0.1", 0)
        )
        host, port = transport.get_extra_info("sockname")[:2]

        metrics = Metrics()
        forwarder = UdpUpstreamForwarder(
            UpstreamUdpConfig(host=host, port=port, max_inflight=1),
            metrics=metrics,
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        task1 = asyncio.create_task(forwarder.query(wire))
        await asyncio.wait_for(first_received.wait(), timeout=0.2)
        task2 = asyncio.create_task(forwarder.query(wire))
        try:
            resp2 = await asyncio.wait_for(task2, timeout=0.05)
            assert resp2 is None
            assert request_count == 1
            snap = metrics.snapshot()
            assert snap.get("dropped_total", 0) >= 1
        finally:
            unblock.set()

        resp1 = await asyncio.wait_for(task1, timeout=0.2)
        assert resp1 is not None

        resp3 = await asyncio.wait_for(forwarder.query(wire), timeout=0.2)
        assert resp3 is not None

        forwarder.close()
        transport.close()

    asyncio.run(run())


def test_udp_upstream_error_metric():
    async def run():
        class DropProtocol(asyncio.DatagramProtocol):
            def connection_made(self, transport: asyncio.DatagramTransport) -> None:
                self.transport = transport

            def datagram_received(self, data: bytes, addr) -> None:
                return

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            DropProtocol, local_addr=("127.0.0.1", 0)
        )
        host, port = transport.get_extra_info("sockname")[:2]

        metrics = Metrics()
        forwarder = UdpUpstreamForwarder(
            UpstreamUdpConfig(host=host, port=port, timeout_s=0.05),
            metrics=metrics,
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        resp = await asyncio.wait_for(forwarder.query(wire), timeout=0.2)
        assert resp is None
        snap = metrics.snapshot()
        assert snap.get("upstream_udp_errors_total", 0) == 1

        forwarder.close()
        transport.close()

    asyncio.run(run())
