import asyncio
import socket

from dnslib import DNSRecord

from resilientdns.dns.server import UdpDnsServer, UdpServerConfig
from resilientdns.metrics import Metrics


class BlockingHandler:
    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    async def handle(self, request: DNSRecord, client_addr):
        await self._gate.wait()
        return request.reply()


def test_inflight_cap_drops_packets():
    async def run():
        metrics = Metrics()
        gate = asyncio.Event()
        handler = BlockingHandler(gate)
        server = UdpDnsServer(
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
            await asyncio.sleep(0.01)
            for _ in range(20):
                sock.sendto(payload, (host, port))
            await asyncio.sleep(0.02)
        finally:
            gate.set()
            server.stop()
            await server_task
            sock.close()

        snap = metrics.snapshot()
        assert snap.get("dropped_total", 0) > 0
        assert snap.get("dropped_max_inflight_total", 0) > 0

    asyncio.run(run())
