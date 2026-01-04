import argparse
import asyncio
import contextlib
import logging
import signal

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler
from resilientdns.dns.server import (
    HttpMetricsConfig,
    HttpMetricsServer,
    TcpDnsServer,
    TcpServerConfig,
    UdpDnsServer,
    UdpServerConfig,
)
from resilientdns.metrics import Metrics, format_stats, periodic_stats_reporter
from resilientdns.upstream.tcp_forwarder import TcpUpstreamForwarder, UpstreamTcpConfig
from resilientdns.upstream.udp_forwarder import UdpUpstreamForwarder, UpstreamUdpConfig


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(args) -> None:
    logger = logging.getLogger("resilientdns")
    metrics = Metrics()
    if args.upstream_transport == "tcp":
        upstream = TcpUpstreamForwarder(
            UpstreamTcpConfig(
                host=args.upstream_host,
                port=args.upstream_port,
                connect_timeout_s=args.upstream_timeout,
                read_timeout_s=args.upstream_timeout,
            ),
            metrics=metrics,
        )
    else:
        upstream = UdpUpstreamForwarder(
            UpstreamUdpConfig(
                host=args.upstream_host,
                port=args.upstream_port,
                timeout_s=args.upstream_timeout,
            ),
            metrics=metrics,
        )
    cache = MemoryDnsCache(
        CacheConfig(
            serve_stale_max_s=args.serve_stale_max,
            negative_ttl_s=args.negative_ttl,
        ),
        metrics=metrics,
    )
    handler = DnsHandler(upstream=upstream, cache=cache, metrics=metrics)
    udp_server = UdpDnsServer(
        UdpServerConfig(
            host=args.listen_host,
            port=args.listen_port,
            max_inflight=args.max_inflight,
        ),
        handler=handler,
        metrics=metrics,
    )
    tcp_server = TcpDnsServer(
        TcpServerConfig(
            host=args.listen_host,
            port=args.listen_port,
            max_inflight=args.max_inflight,
        ),
        handler=handler,
        metrics=metrics,
    )
    metrics_server = None
    if args.metrics_port > 0:
        metrics_server = HttpMetricsServer(
            HttpMetricsConfig(host=args.metrics_host, port=args.metrics_port), metrics=metrics
        )
    loop = asyncio.get_running_loop()
    stop_fns = [udp_server.stop, tcp_server.stop]
    if metrics_server:
        stop_fns.append(metrics_server.stop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: [fn() for fn in stop_fns])
        except NotImplementedError:
            pass

    async def wait_ready(server_task: asyncio.Task, ready: asyncio.Event) -> None:
        ready_task = asyncio.create_task(ready.wait())
        try:
            done, _ = await asyncio.wait(
                {server_task, ready_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if server_task in done:
                await server_task
        finally:
            if not ready_task.done():
                ready_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ready_task

    udp_task = asyncio.create_task(udp_server.run())
    tcp_task = asyncio.create_task(tcp_server.run())
    metrics_task = asyncio.create_task(metrics_server.run()) if metrics_server else None
    reporter_task = None

    try:
        await wait_ready(udp_task, udp_server.ready)
        await wait_ready(tcp_task, tcp_server.ready)
        if metrics_server and metrics_task:
            await wait_ready(metrics_task, metrics_server.ready)
        reporter_task = asyncio.create_task(periodic_stats_reporter(metrics))
        tasks = [udp_task, tcp_task]
        if metrics_task:
            tasks.append(metrics_task)
        await asyncio.gather(*tasks)
    finally:
        logger.info("Shutting down...")
        if reporter_task:
            reporter_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reporter_task
        for fn in stop_fns:
            fn()
        tasks = [udp_task, tcp_task]
        if metrics_task:
            tasks.append(metrics_task)
        for task in tasks:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        close_fn = getattr(upstream, "close", None)
        if callable(close_fn):
            close_fn()
        snapshot = metrics.snapshot()
        if any(snapshot.values()):
            logger.info(format_stats(snapshot))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="resilientdns",
        description="ResilientDNS UDP server (MVP)",
    )

    # Listener options
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=5353)
    parser.add_argument("--max-inflight", type=int, default=256)
    parser.add_argument("--metrics-host", default="127.0.0.1")
    parser.add_argument("--metrics-port", type=int, default=0)

    # Upstream DNS (temporary)
    parser.add_argument(
        "--upstream-transport",
        choices=["udp", "tcp"],
        default="udp",
    )
    parser.add_argument("--upstream-host", default="1.1.1.1")
    parser.add_argument("--upstream-port", type=int, default=53)
    parser.add_argument("--upstream-timeout", type=float, default=2.0)

    # Cache tuning
    parser.add_argument(
        "--serve-stale-max",
        type=int,
        default=300,
        help="Max seconds to serve stale cache entries if upstream fails",
    )
    parser.add_argument(
        "--negative-ttl",
        type=int,
        default=60,
        help="TTL (seconds) for negative cache entries",
    )

    # Logging
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    _setup_logging(args.verbose)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
