import argparse

import pytest

from resilientdns.config import build_config, validate_config


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        listen_host="127.0.0.1",
        listen_port=5353,
        max_inflight=256,
        metrics_host="127.0.0.1",
        metrics_port=0,
        upstream_transport="udp",
        upstream_host="1.1.1.1",
        upstream_port=53,
        upstream_timeout=2.0,
        serve_stale_max=300,
        negative_ttl=60,
        verbose=False,
        relay_base_url=None,
        relay_api_version=1,
        relay_auth_token=None,
        relay_startup_check="require",
        relay_max_items=32,
        relay_max_request_bytes=65536,
        relay_per_item_max_wire_bytes=4096,
        relay_max_response_bytes=262144,
        refresh_enabled=False,
        refresh_ahead_seconds=30,
        refresh_popularity_threshold=5,
        refresh_tick_ms=500,
        refresh_batch_size=50,
        refresh_concurrency=5,
        refresh_queue_max=1024,
    )


def test_config_valid():
    cfg = build_config(_args())
    validate_config(cfg)


def test_config_invalid_listen_port():
    args = _args()
    args.listen_port = 0
    with pytest.raises(ValueError, match="listen_port"):
        validate_config(build_config(args))


def test_config_invalid_timeout():
    args = _args()
    args.upstream_timeout = 0
    with pytest.raises(ValueError, match="upstream_timeout_s"):
        validate_config(build_config(args))


def test_config_invalid_max_inflight():
    args = _args()
    args.max_inflight = 0
    with pytest.raises(ValueError, match="max_inflight"):
        validate_config(build_config(args))


def test_config_empty_upstream_host():
    args = _args()
    args.upstream_host = ""
    with pytest.raises(ValueError, match="upstream_host"):
        validate_config(build_config(args))
