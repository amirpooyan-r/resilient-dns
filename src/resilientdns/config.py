import argparse
from dataclasses import dataclass

from resilientdns.relay_types import (
    RelayLimits,
    validate_base_url,
    validate_limits,
    validate_startup_check,
)


@dataclass(frozen=True)
class Config:
    listen_host: str = "127.0.0.1"
    listen_port: int = 5353
    max_inflight: int = 256
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 0
    upstream_transport: str = "udp"
    upstream_host: str = "1.1.1.1"
    upstream_port: int = 53
    upstream_timeout_s: float = 2.0
    serve_stale_max_s: int = 300
    negative_ttl_s: int = 60
    cache_max_entries: int = 0
    tcp_pool_max_conns: int = 4
    tcp_pool_idle_timeout_s: float = 30.0
    udp_max_workers: int = 32
    verbose: bool = False
    relay_base_url: str | None = None
    relay_api_version: int = 1
    relay_auth_token: str | None = None
    relay_startup_check: str = "require"
    relay_max_items: int = 32
    relay_max_request_bytes: int = 65536
    relay_per_item_max_wire_bytes: int = 4096
    relay_max_response_bytes: int = 262144


def build_config(args: argparse.Namespace) -> Config:
    return Config(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        max_inflight=args.max_inflight,
        metrics_host=args.metrics_host,
        metrics_port=args.metrics_port,
        upstream_transport=args.upstream_transport,
        upstream_host=args.upstream_host,
        upstream_port=args.upstream_port,
        upstream_timeout_s=args.upstream_timeout,
        serve_stale_max_s=args.serve_stale_max,
        negative_ttl_s=args.negative_ttl,
        verbose=args.verbose,
        relay_base_url=args.relay_base_url,
        relay_api_version=args.relay_api_version,
        relay_auth_token=args.relay_auth_token,
        relay_startup_check=args.relay_startup_check,
        relay_max_items=args.relay_max_items,
        relay_max_request_bytes=args.relay_max_request_bytes,
        relay_per_item_max_wire_bytes=args.relay_per_item_max_wire_bytes,
        relay_max_response_bytes=args.relay_max_response_bytes,
    )


def validate_config(cfg: Config) -> None:
    if not cfg.listen_host.strip():
        raise ValueError("listen_host must be non-empty")
    if not cfg.upstream_host.strip():
        raise ValueError("upstream_host must be non-empty")
    if not cfg.metrics_host.strip():
        raise ValueError("metrics_host must be non-empty")

    if cfg.listen_port < 1 or cfg.listen_port > 65535:
        raise ValueError("listen_port must be between 1 and 65535")
    if cfg.upstream_port < 1 or cfg.upstream_port > 65535:
        raise ValueError("upstream_port must be between 1 and 65535")
    if cfg.metrics_port != 0 and (cfg.metrics_port < 1 or cfg.metrics_port > 65535):
        raise ValueError("metrics_port must be 0 or between 1 and 65535")

    if cfg.upstream_transport not in ("udp", "tcp"):
        raise ValueError("upstream_transport must be 'udp' or 'tcp'")

    if cfg.upstream_timeout_s <= 0:
        raise ValueError("upstream_timeout_s must be > 0")
    if cfg.serve_stale_max_s < 0:
        raise ValueError("serve_stale_max_s must be >= 0")
    if cfg.negative_ttl_s < 0:
        raise ValueError("negative_ttl_s must be >= 0")
    if cfg.cache_max_entries < 0:
        raise ValueError("cache_max_entries must be >= 0")

    if cfg.max_inflight < 1:
        raise ValueError("max_inflight must be >= 1")
    if cfg.udp_max_workers < 1:
        raise ValueError("udp_max_workers must be >= 1")
    if cfg.tcp_pool_max_conns < 0:
        raise ValueError("tcp_pool_max_conns must be >= 0")
    if cfg.tcp_pool_idle_timeout_s <= 0:
        raise ValueError("tcp_pool_idle_timeout_s must be > 0")

    if cfg.relay_base_url:
        validate_base_url(cfg.relay_base_url)
        validate_startup_check(cfg.relay_startup_check)
        limits = RelayLimits(
            max_items=cfg.relay_max_items,
            max_request_bytes=cfg.relay_max_request_bytes,
            per_item_max_wire_bytes=cfg.relay_per_item_max_wire_bytes,
            max_response_bytes=cfg.relay_max_response_bytes,
        )
        validate_limits(limits)
