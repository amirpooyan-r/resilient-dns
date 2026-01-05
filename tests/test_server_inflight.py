import asyncio
import socket

from dnslib import DNSRecord

from resilientdns.dns.server import UdpDnsServer, UdpServerConfig
from resilientdns.metrics import Metrics


def test_inflight_cap_drops_packets():
    async def run():
        metrics = Metrics()
        gate = asyncio.Event()
        started = asyncio.Event()

        class BlockingHandler:
            def __init__(self, gate: asyncio.Event, started: asyncio.Event) -> None:
                self._gate = gate
                self._started = started

            async def handle(self, request: DNSRecord, client_addr):
                self._started.set()
                await self._gate.wait()
                return request.reply()

        drop_event = asyncio.Event()

        class TestUdpServer(UdpDnsServer):
            def datagram_received(self, data: bytes, addr):
                if self.config.max_inflight > 0 and len(self._inflight) >= self.config.max_inflight:
                    if self.metrics:
                        self.metrics.inc("dropped_total")
                        self.metrics.inc("dropped_max_inflight_total")
                    drop_event.set()
                    return
                return super().datagram_received(data, addr)

        handler = BlockingHandler(gate, started)
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
            sock.sendto(payload, (host, port))
            await asyncio.wait_for(drop_event.wait(), timeout=0.2)
        finally:
            gate.set()
            if server._inflight:
                await asyncio.gather(*list(server._inflight), return_exceptions=True)
            server.stop()
            await server_task
            sock.close()

        snap = metrics.snapshot()
        assert snap.get("dropped_total", 0) > 0
        assert snap.get("dropped_max_inflight_total", 0) > 0

    asyncio.run(run())
