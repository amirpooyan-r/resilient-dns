import asyncio

import pytest
from fake_relay.types import DnsHandlerMode, DnsItemResult

from resilientdns.metrics import Metrics
from resilientdns.relay_forwarder import RelayUpstreamForwarder
from resilientdns.relay_types import RelayConfig, RelayLimits


@pytest.mark.asyncio
async def test_relay_forwarder_success(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.next_dns_results = [DnsItemResult.ok_result("0", b"response")]

    metrics = Metrics()
    forwarder = RelayUpstreamForwarder(
        relay_cfg=RelayConfig(base_url=base_url),
        metrics=metrics,
        timeout_s=0.5,
    )
    try:
        resp = await forwarder.query(b"query", request_id="req-1")
    finally:
        await forwarder.close()

    assert resp == b"response"


@pytest.mark.asyncio
async def test_relay_forwarder_auth_required(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.expected_token = "secret"

    metrics = Metrics()
    forwarder = RelayUpstreamForwarder(
        relay_cfg=RelayConfig(base_url=base_url),
        metrics=metrics,
        timeout_s=0.5,
    )
    try:
        resp = await forwarder.query(b"query", request_id="req-2")
    finally:
        await forwarder.close()

    assert resp is None
    snap = metrics.snapshot()
    assert snap.get("upstream_relay_requests_total", 0) == 1
    assert snap.get("upstream_relay_http_4xx_total", 0) == 1


@pytest.mark.asyncio
async def test_relay_forwarder_drops_oversize(fake_relay_server):
    base_url, controller = fake_relay_server
    limits = RelayLimits(per_item_max_wire_bytes=1)

    metrics = Metrics()
    forwarder = RelayUpstreamForwarder(
        relay_cfg=RelayConfig(base_url=base_url, limits=limits),
        metrics=metrics,
        timeout_s=0.5,
    )
    try:
        resp = await forwarder.query(b"too-big", request_id="req-3")
    finally:
        await forwarder.close()

    assert resp is None
    assert controller.script.received_dns_batches == []
    snap = metrics.snapshot()
    assert snap.get("dropped_total", 0) == 1
    assert snap.get("dropped_oversize_total", 0) == 1


@pytest.mark.asyncio
async def test_relay_forwarder_protocol_error(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.force_invalid_json = True

    metrics = Metrics()
    forwarder = RelayUpstreamForwarder(
        relay_cfg=RelayConfig(base_url=base_url),
        metrics=metrics,
        timeout_s=0.5,
    )
    try:
        with pytest.raises(ValueError):
            await forwarder.query(b"query", request_id="req-4")
    finally:
        await forwarder.close()

    snap = metrics.snapshot()
    assert snap.get("upstream_relay_protocol_errors_total", 0) == 1


@pytest.mark.asyncio
async def test_relay_forwarder_timeout(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.dns_handler_mode = DnsHandlerMode.TIMEOUT

    metrics = Metrics()
    forwarder = RelayUpstreamForwarder(
        relay_cfg=RelayConfig(base_url=base_url),
        metrics=metrics,
        timeout_s=0.05,
    )
    try:
        with pytest.raises(asyncio.TimeoutError):
            await forwarder.query(b"query", request_id="req-5")
    finally:
        await forwarder.close()

    snap = metrics.snapshot()
    assert snap.get("upstream_relay_timeouts_total", 0) == 1
