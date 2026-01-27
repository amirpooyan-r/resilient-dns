import argparse
import asyncio
import contextlib
import logging
import signal
import sys

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.config import Config, build_config, validate_config
from resilientdns.dns.handler import DnsHandler, HandlerConfig
from resilientdns.dns.server import (
    HttpMetricsConfig,
    HttpMetricsServer,
    ReadyState,
    TcpDnsServer,
    TcpServerConfig,
    UdpDnsServer,
    UdpServerConfig,
)
from resilientdns.metrics import Metrics, format_stats, periodic_stats_reporter
from resilientdns.relay_startup_check import run_relay_startup_check
from resilientdns.relay_types import RelayConfig, RelayLimits
from resilientdns.upstream.tcp_forwarder import TcpUpstreamForwarder, UpstreamTcpConfig
from resilientdns.upstream.udp_forwarder import UdpUpstreamForwarder, UpstreamUdpConfig


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _register_signal_handlers(loop, stop_fns, cache_clear_fn, logger) -> None:
    def stop_all() -> None:
        for fn in stop_fns:
            fn()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_all)
        except NotImplementedError:
            pass

    if hasattr(signal, "SIGHUP"):
        try:
            loop.add_signal_handler(
                signal.SIGHUP,
                lambda: _handle_sighup(cache_clear_fn, logger),
            )
        except NotImplementedError:
            pass


def _handle_sighup(cache_clear_fn, logger) -> None:
    cache_clear_fn()
    logger.info("Cache cleared (SIGHUP)")


def _build_relay_config(cfg: Config) -> RelayConfig:
    return RelayConfig(
        base_url=cfg.relay_base_url or "",
        api_version=cfg.relay_api_version,
        auth_token=cfg.relay_auth_token,
        startup_check=cfg.relay_startup_check,
        limits=RelayLimits(
            max_items=cfg.relay_max_items,
            max_request_bytes=cfg.relay_max_request_bytes,
            per_item_max_wire_bytes=cfg.relay_per_item_max_wire_bytes,
            max_response_bytes=cfg.relay_max_response_bytes,
        ),
    )


async def _run(cfg: Config) -> None:
    logger = logging.getLogger("resilientdns")
    metrics = Metrics()
    ready_state = ReadyState()
    if cfg.upstream_transport == "relay":
        relay_cfg = _build_relay_config(cfg)
        from resilientdns.relay_forwarder import RelayUpstreamForwarder

        upstream = RelayUpstreamForwarder(
            relay_cfg=relay_cfg,
            metrics=metrics,
            timeout_s=cfg.upstream_timeout_s,
        )
    elif cfg.upstream_transport == "tcp":
        upstream = TcpUpstreamForwarder(
            UpstreamTcpConfig(
                host=cfg.upstream_host,
                port=cfg.upstream_port,
                connect_timeout_s=cfg.upstream_timeout_s,
                read_timeout_s=cfg.upstream_timeout_s,
                pool_max_conns=cfg.tcp_pool_max_conns,
                pool_idle_timeout_s=cfg.tcp_pool_idle_timeout_s,
            ),
            metrics=metrics,
        )
    else:
        upstream = UdpUpstreamForwarder(
            UpstreamUdpConfig(
                host=cfg.upstream_host,
                port=cfg.upstream_port,
                timeout_s=cfg.upstream_timeout_s,
                max_workers=cfg.udp_max_workers,
            ),
            metrics=metrics,
        )
    cache = MemoryDnsCache(
        CacheConfig(
            serve_stale_max_s=cfg.serve_stale_max_s,
            negative_ttl_s=cfg.negative_ttl_s,
            max_entries=cfg.cache_max_entries,
        ),
        metrics=metrics,
    )
    handler = DnsHandler(
        upstream=upstream,
        cache=cache,
        metrics=metrics,
        config=HandlerConfig(
            upstream_timeout_s=cfg.upstream_timeout_s,
            refresh_watch_timeout_s=5.0,
            refresh_enabled=cfg.refresh_enabled,
            refresh_ahead_seconds=cfg.refresh_ahead_seconds,
            refresh_popularity_threshold=cfg.refresh_popularity_threshold,
            refresh_tick_ms=cfg.refresh_tick_ms,
            refresh_batch_size=cfg.refresh_batch_size,
            refresh_concurrency=cfg.refresh_concurrency,
            refresh_queue_max=cfg.refresh_queue_max,
        ),
    )
    udp_server = UdpDnsServer(
        UdpServerConfig(
            host=cfg.listen_host,
            port=cfg.listen_port,
            max_inflight=cfg.max_inflight,
        ),
        handler=handler,
        metrics=metrics,
    )
    tcp_server = TcpDnsServer(
        TcpServerConfig(
            host=cfg.listen_host,
            port=cfg.listen_port,
            max_inflight=cfg.max_inflight,
        ),
        handler=handler,
        metrics=metrics,
    )
    metrics_server = None
    if cfg.metrics_port > 0:
        metrics_server = HttpMetricsServer(
            HttpMetricsConfig(host=cfg.metrics_host, port=cfg.metrics_port),
            metrics=metrics,
            ready_state=ready_state,
            cache_stats_provider=cache.stats_snapshot,
        )
    loop = asyncio.get_running_loop()
    stop_fns = [udp_server.stop, tcp_server.stop]
    if metrics_server:
        stop_fns.append(metrics_server.stop)
    _register_signal_handlers(loop, stop_fns, cache.clear, logger)

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
    refresh_tasks = []

    try:
        await wait_ready(udp_task, udp_server.ready)
        await wait_ready(tcp_task, tcp_server.ready)
        if metrics_server and metrics_task:
            await wait_ready(metrics_task, metrics_server.ready)
        ready_state.set_ready()
        reporter_task = asyncio.create_task(periodic_stats_reporter(metrics))
        refresh_tasks = handler.start_refresh_tasks()
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
        if refresh_tasks:
            await handler.stop_refresh_tasks()
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
            result = close_fn()
            if asyncio.iscoroutine(result):
                await result
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
        choices=["udp", "tcp", "relay"],
        default="udp",
    )
    parser.add_argument("--upstream-host", default="1.1.1.1")
    parser.add_argument("--upstream-port", type=int, default=53)
    parser.add_argument("--upstream-timeout", type=float, default=2.0)

    # Relay upstream (skeleton configuration only)
    parser.add_argument("--relay-base-url", default=None)
    parser.add_argument("--relay-api-version", type=int, default=1)
    parser.add_argument("--relay-auth-token", default=None)
    parser.add_argument(
        "--relay-startup-check",
        choices=["require", "warn", "off"],
        default="require",
    )
    parser.add_argument("--relay-max-items", type=int, default=32)
    parser.add_argument("--relay-max-request-bytes", type=int, default=65536)
    parser.add_argument("--relay-per-item-max-wire-bytes", type=int, default=4096)
    parser.add_argument("--relay-max-response-bytes", type=int, default=262144)

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
    parser.add_argument("--refresh-enabled", action="store_true")
    parser.add_argument("--refresh-ahead-seconds", type=int, default=30)
    parser.add_argument("--refresh-popularity-threshold", type=int, default=5)
    parser.add_argument("--refresh-tick-ms", type=int, default=500)
    parser.add_argument("--refresh-batch-size", type=int, default=50)
    parser.add_argument("--refresh-concurrency", type=int, default=5)
    parser.add_argument("--refresh-queue-max", type=int, default=1024)

    # Logging
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    cfg = build_config(args)
    try:
        validate_config(cfg)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    _setup_logging(cfg.verbose)
    logger = logging.getLogger("resilientdns")

    if cfg.upstream_transport == "relay" and cfg.relay_startup_check != "off":
        relay_cfg = _build_relay_config(cfg)
        asyncio.run(
            run_relay_startup_check(
                relay_cfg=relay_cfg,
                timeout_s=cfg.upstream_timeout_s,
                client_limits=relay_cfg.limits,
                mode=cfg.relay_startup_check,
                logger=logger,
            )
        )
    asyncio.run(_run(cfg))


if __name__ == "__main__":
    main()
