import argparse
import asyncio
import contextlib
import logging
import signal

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler
from resilientdns.dns.server import UdpDnsServer, UdpServerConfig
from resilientdns.metrics import Metrics, format_stats, periodic_stats_reporter
from resilientdns.upstream.udp_forwarder import (
    UdpUpstreamForwarder,
    UpstreamUdpConfig,
)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(args) -> None:
    logger = logging.getLogger("resilientdns")
    metrics = Metrics()
    upstream = UdpUpstreamForwarder(
        UpstreamUdpConfig(
            host=args.upstream_host, port=args.upstream_port, timeout_s=args.upstream_timeout
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
    server = UdpDnsServer(
        UdpServerConfig(
            host=args.listen_host,
            port=args.listen_port,
            max_inflight=args.max_inflight,
        ),
        handler=handler,
        metrics=metrics,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, server.stop)
        except NotImplementedError:
            pass
    server_task = asyncio.create_task(server.run())
    reporter_task = None

    try:
        await server.ready.wait()
        reporter_task = asyncio.create_task(periodic_stats_reporter(metrics))
        await server_task
    finally:
        logger.info("Shutting down...")
        if reporter_task:
            reporter_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reporter_task
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

    # Upstream DNS (temporary)
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
