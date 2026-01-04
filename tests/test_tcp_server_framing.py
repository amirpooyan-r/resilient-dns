import asyncio

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.dns.server import TcpDnsServer, TcpServerConfig


class EchoHandler:
    async def handle(self, request: DNSRecord, client_addr):
        reply = request.reply()
        reply.add_answer(
            RR(
                rname=request.q.qname,
                rtype=QTYPE.A,
                rclass=1,
                ttl=60,
                rdata=A("1.2.3.4"),
            )
        )
        return reply


def test_tcp_framing_partial_reads():
    async def run():
        server = TcpDnsServer(
            TcpServerConfig(host="127.0.0.1", port=0),
            handler=EchoHandler(),
        )
        server_task = asyncio.create_task(server.run())
        await server.ready.wait()

        assert server._server is not None
        host, port = server._server.sockets[0].getsockname()
        reader, writer = await asyncio.open_connection(host, port)
        req = DNSRecord.question("example.com", qtype="A").pack()
        prefix = len(req).to_bytes(2, "big")

        writer.write(prefix[:1])
        await writer.drain()
        writer.write(prefix[1:] + req[:3])
        await writer.drain()
        writer.write(req[3:])
        await writer.drain()

        resp_len = int.from_bytes(await reader.readexactly(2), "big")
        resp_wire = await reader.readexactly(resp_len)
        resp = DNSRecord.parse(resp_wire)
        assert resp.rr[0].rdata == A("1.2.3.4")

        writer.close()
        await writer.wait_closed()
        server.stop()
        await server_task

    asyncio.run(run())


def test_tcp_oversize_length_drop():
    async def run():
        server = TcpDnsServer(
            TcpServerConfig(host="127.0.0.1", port=0, max_message_size=32),
            handler=EchoHandler(),
        )
        server_task = asyncio.create_task(server.run())
        await server.ready.wait()

        assert server._server is not None
        host, port = server._server.sockets[0].getsockname()
        reader, writer = await asyncio.open_connection(host, port)

        writer.write((1000).to_bytes(2, "big"))
        await writer.drain()
        data = await reader.read(1)
        assert data == b""

        writer.close()
        await writer.wait_closed()
        server.stop()
        await server_task

    asyncio.run(run())
