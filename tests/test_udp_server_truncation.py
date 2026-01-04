import asyncio
import socket

from dnslib import QTYPE, RCODE, RR, TXT, DNSRecord

from resilientdns.dns.server import UdpDnsServer, UdpServerConfig
from resilientdns.metrics import Metrics


class LargeResponseHandler:
    async def handle(self, request: DNSRecord, client_addr):
        reply = request.reply()
        reply.header.rcode = RCODE.NOERROR
        reply.add_answer(
            RR(
                rname=request.q.qname,
                rtype=QTYPE.TXT,
                rclass=1,
                ttl=60,
                rdata=TXT("x" * 200),
            )
        )
        return reply


def test_udp_response_truncated():
    async def run():
        server = UdpDnsServer(
            UdpServerConfig(host="127.0.0.1", port=0, max_udp_payload=100),
            handler=LargeResponseHandler(),
        )
        server_task = asyncio.create_task(server.run())
        await server.ready.wait()

        assert server.transport is not None
        host, port = server.transport.get_extra_info("sockname")
        payload = DNSRecord.question("example.com", qtype="TXT").pack()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        try:
            sock.sendto(payload, (host, port))
            resp_wire, _ = await asyncio.to_thread(sock.recvfrom, 2048)
        finally:
            server.stop()
            await server_task
            sock.close()

        resp = DNSRecord.parse(resp_wire)
        assert resp.header.tc == 1
        assert resp.rr == []

    asyncio.run(run())


def test_udp_malformed_increments_metric():
    async def run():
        metrics = Metrics()
        server = UdpDnsServer(
            UdpServerConfig(host="127.0.0.1", port=0),
            handler=LargeResponseHandler(),
            metrics=metrics,
        )
        server_task = asyncio.create_task(server.run())
        await server.ready.wait()

        assert server.transport is not None
        host, port = server.transport.get_extra_info("sockname")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(b"\x00\x01", (host, port))
            await asyncio.sleep(0.01)
        finally:
            server.stop()
            await server_task
            sock.close()

        snap = metrics.snapshot()
        assert snap.get("malformed_total", 0) >= 1

    asyncio.run(run())
