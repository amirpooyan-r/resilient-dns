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
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            writer.close()
            await writer.wait_closed()

        server = await _serve_once("127.0.0.1", 0, handler)
        host, port = server.sockets[0].getsockname()
        server.close()
        await server.wait_closed()

        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(host=host, port=port, connect_timeout_s=0.05),
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


def test_tcp_upstream_reuses_connection():
    async def run():
        connection_count = 0

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            nonlocal connection_count
            connection_count += 1
            try:
                while True:
                    length = int.from_bytes(await reader.readexactly(2), "big")
                    wire = await reader.readexactly(length)
                    resp = _make_response(wire, "1.2.3.4")
                    writer.write(len(resp).to_bytes(2, "big") + resp)
                    await writer.drain()
            except asyncio.IncompleteReadError:
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await _serve_once("127.0.0.1", 0, handler)
        host, port = server.sockets[0].getsockname()

        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(host=host, port=port),
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        resp1 = await forwarder.query(wire)
        resp2 = await forwarder.query(wire)
        assert resp1 is not None
        assert resp2 is not None
        assert connection_count == 1

        await forwarder.close()
        server.close()
        await server.wait_closed()

    asyncio.run(run())


def test_tcp_upstream_pool_idle_timeout():
    async def run():
        connection_count = 0

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            nonlocal connection_count
            connection_count += 1
            try:
                while True:
                    length = int.from_bytes(await reader.readexactly(2), "big")
                    wire = await reader.readexactly(length)
                    resp = _make_response(wire, "1.2.3.4")
                    writer.write(len(resp).to_bytes(2, "big") + resp)
                    await writer.drain()
            except asyncio.IncompleteReadError:
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        server = await _serve_once("127.0.0.1", 0, handler)
        host, port = server.sockets[0].getsockname()

        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(host=host, port=port, pool_idle_timeout_s=0.05),
        )
        wire = DNSRecord.question("example.com", qtype="A").pack()
        resp1 = await forwarder.query(wire)
        assert resp1 is not None
        await asyncio.sleep(0.1)
        resp2 = await forwarder.query(wire)
        assert resp2 is not None
        assert connection_count == 2

        await forwarder.close()
        server.close()
        await server.wait_closed()

    asyncio.run(run())


def test_tcp_upstream_closed_connection_not_reused():
    async def run():
        connection_count = 0

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            nonlocal connection_count
            connection_count += 1
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
        resp1 = await forwarder.query(wire)
        assert resp1 is not None
        await asyncio.sleep(0.1)
        resp2 = await forwarder.query(wire)
        assert resp2 is not None
        assert connection_count == 2

        await forwarder.close()
        server.close()
        await server.wait_closed()

    asyncio.run(run())


def test_tcp_upstream_max_inflight():
    async def run():
        first_received = asyncio.Event()
        unblock = asyncio.Event()
        request_count = 0

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            nonlocal request_count
            try:
                length = int.from_bytes(await reader.readexactly(2), "big")
                wire = await reader.readexactly(length)
                request_count += 1
                first_received.set()
                await asyncio.wait_for(unblock.wait(), timeout=0.5)
                resp = _make_response(wire, "1.2.3.4")
                writer.write(len(resp).to_bytes(2, "big") + resp)
                await writer.drain()
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

        metrics = Metrics()
        server = await _serve_once("127.0.0.1", 0, handler)
        host, port = server.sockets[0].getsockname()

        forwarder = TcpUpstreamForwarder(
            UpstreamTcpConfig(host=host, port=port, max_inflight=1),
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

        await forwarder.close()
        server.close()
        await server.wait_closed()

    asyncio.run(run())
