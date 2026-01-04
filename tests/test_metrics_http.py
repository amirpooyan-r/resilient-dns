import asyncio

from resilientdns.dns.server import HttpMetricsConfig, HttpMetricsServer
from resilientdns.metrics import Metrics


def test_metrics_http_endpoint():
    async def run():
        metrics = Metrics()
        metrics.inc("b_total", 1)
        metrics.inc("a_total", 2)
        server = HttpMetricsServer(HttpMetricsConfig(host="127.0.0.1", port=0), metrics)
        server_task = asyncio.create_task(server.run())
        await server.ready.wait()

        assert server._server is not None
        host, port = server._server.sockets[0].getsockname()
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(b"GET /metrics HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        resp = await reader.read()
        writer.close()
        await writer.wait_closed()

        server.stop()
        await server_task

        header, body = resp.split(b"\r\n\r\n", 1)
        assert b"200 OK" in header
        assert body == b"a_total 2\nb_total 1\n"

    asyncio.run(run())


def test_metrics_healthz():
    async def run():
        metrics = Metrics()
        server = HttpMetricsServer(HttpMetricsConfig(host="127.0.0.1", port=0), metrics)
        server_task = asyncio.create_task(server.run())
        await server.ready.wait()

        assert server._server is not None
        host, port = server._server.sockets[0].getsockname()
        reader, writer = await asyncio.open_connection(host, port)
        writer.write(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        resp = await reader.read()
        writer.close()
        await writer.wait_closed()

        server.stop()
        await server_task

        header, body = resp.split(b"\r\n\r\n", 1)
        assert b"200 OK" in header
        assert body == b"ok"

    asyncio.run(run())
