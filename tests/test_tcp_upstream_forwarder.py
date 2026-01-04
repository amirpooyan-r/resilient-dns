import asyncio

from dnslib import QTYPE, RR, A, DNSRecord

from resilientdns.metrics import Metrics
from resilientdns.upstream.tcp_forwarder import TcpUpstreamForwarder, UpstreamTcpConfig


async def _serve_once(host: str, port: int, handler):
    server = await asyncio.start_server(handler, host=host, port=port)
    return server


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


def test_tcp_upstream_happy_path():
    async def run():
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            length = int.from_bytes(await reader.readexactly(2), "big")
            wire = await reader.readexactly(length)
            resp = _make_response(wire, "1.2.3.4")
            writer.write(len(resp).to_bytes(2, "big") + resp)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await _serve_once("127.0.0.1", 0, handler)
        host, port = server.sockets[0].getsockname()

        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(host=host, port=port),
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        resp = await forwarder.query(wire)
        assert resp is not None
        parsed = DNSRecord.parse(resp)
        assert parsed.rr[0].rdata == A("1.2.3.4")

        server.close()
        await server.wait_closed()

    asyncio.run(run())


def test_tcp_upstream_connect_failure():
    async def run():
        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(host="127.0.0.1", port=1, connect_timeout_s=0.05),
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        resp = await forwarder.query(wire)
        assert resp is None

    asyncio.run(run())


def test_tcp_upstream_read_timeout():
    async def run():
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            await reader.readexactly(2)
            await asyncio.sleep(0.2)
            writer.close()
            await writer.wait_closed()

        server = await _serve_once("127.0.0.1", 0, handler)
        host, port = server.sockets[0].getsockname()
        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(
                host=host,
                port=port,
                read_timeout_s=0.05,
                connect_timeout_s=0.05,
            ),
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        resp = await forwarder.query(wire)
        assert resp is None

        server.close()
        await server.wait_closed()

    asyncio.run(run())


def test_tcp_upstream_oversize_response_dropped():
    async def run():
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            await reader.readexactly(2)
            writer.write((100).to_bytes(2, "big") + b"x" * 100)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        metrics = Metrics()
        server = await _serve_once("127.0.0.1", 0, handler)
        host, port = server.sockets[0].getsockname()
        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(host=host, port=port, max_message_size=32),
            metrics=metrics,
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        resp = await forwarder.query(wire)
        assert resp is None
        snap = metrics.snapshot()
        assert snap.get("dropped_total", 0) == 1

        server.close()
        await server.wait_closed()

    asyncio.run(run())
