import asyncio
import socket

from dnslib import QTYPE, RCODE, RR, TXT, DNSRecord

from resilientdns.dns.server import TcpDnsServer, TcpServerConfig, UdpDnsServer, UdpServerConfig
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
        udp_server = UdpDnsServer(
            UdpServerConfig(host="127.0.0.1", port=0, max_udp_payload=100),
            handler=LargeResponseHandler(),
        )
        tcp_server = TcpDnsServer(
            TcpServerConfig(host="127.0.0.1", port=0, max_message_size=2048),
            handler=LargeResponseHandler(),
        )
        udp_task = asyncio.create_task(udp_server.run())
        tcp_task = asyncio.create_task(tcp_server.run())
        await asyncio.gather(udp_server.ready.wait(), tcp_server.ready.wait())

        assert udp_server.transport is not None
        udp_host, udp_port = udp_server.transport.get_extra_info("sockname")
        payload = DNSRecord.question("example.com", qtype="TXT").pack()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        try:
            sock.sendto(payload, (udp_host, udp_port))
            resp_wire, _ = await asyncio.to_thread(sock.recvfrom, 2048)
        finally:
            sock.close()

        resp = DNSRecord.parse(resp_wire)
        assert resp.header.tc == 1
        assert resp.rr == []

        assert tcp_server._server is not None
        tcp_host, tcp_port = tcp_server._server.sockets[0].getsockname()
        reader, writer = await asyncio.open_connection(tcp_host, tcp_port)
        writer.write(len(payload).to_bytes(2, "big") + payload)
        await writer.drain()
        tcp_len = int.from_bytes(await reader.readexactly(2), "big")
        tcp_wire = await reader.readexactly(tcp_len)
        tcp_resp = DNSRecord.parse(tcp_wire)
        assert tcp_resp.header.tc == 0
        assert tcp_resp.rr

        writer.close()
        await writer.wait_closed()
        udp_server.stop()
        tcp_server.stop()
        await asyncio.gather(udp_task, tcp_task)

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
