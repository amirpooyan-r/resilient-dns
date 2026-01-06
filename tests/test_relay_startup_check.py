import logging

import pytest
from fake_relay.types import InfoHandlerMode

from resilientdns.relay_startup_check import (
    RelayStartupCheckError,
    check_relay_startup,
    run_relay_startup_check,
)
from resilientdns.relay_types import RelayConfig, RelayLimits


@pytest.mark.asyncio
async def test_relay_startup_check_success(fake_relay_server):
    base_url, _controller = fake_relay_server
    relay_cfg = RelayConfig(base_url=base_url)
    await check_relay_startup(relay_cfg, timeout_s=0.5, client_limits=relay_cfg.limits)


@pytest.mark.asyncio
async def test_relay_startup_check_auth_required_require(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.expected_token = "secret"
    relay_cfg = RelayConfig(base_url=base_url)

    with pytest.raises(SystemExit, match="Relay startup check failed"):
        await run_relay_startup_check(
            relay_cfg=relay_cfg,
            timeout_s=0.5,
            client_limits=relay_cfg.limits,
            mode="require",
            logger=logging.getLogger("resilientdns"),
        )


@pytest.mark.asyncio
async def test_relay_startup_check_auth_required_warn(fake_relay_server, caplog):
    base_url, controller = fake_relay_server
    controller.script.expected_token = "secret"
    relay_cfg = RelayConfig(base_url=base_url)

    with caplog.at_level(logging.WARNING):
        await run_relay_startup_check(
            relay_cfg=relay_cfg,
            timeout_s=0.5,
            client_limits=relay_cfg.limits,
            mode="warn",
            logger=logging.getLogger("resilientdns"),
        )

    assert "Relay startup check failed" in caplog.text


@pytest.mark.asyncio
async def test_relay_startup_check_version_mismatch(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.force_protocol_v = 2
    relay_cfg = RelayConfig(base_url=base_url)

    with pytest.raises(RelayStartupCheckError, match="version mismatch"):
        await check_relay_startup(relay_cfg, timeout_s=0.5, client_limits=relay_cfg.limits)


@pytest.mark.asyncio
async def test_relay_startup_check_limits_mismatch(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.limits.max_items = 1
    relay_cfg = RelayConfig(base_url=base_url, limits=RelayLimits(max_items=32))

    with pytest.raises(RelayStartupCheckError, match="limits incompatible"):
        await check_relay_startup(relay_cfg, timeout_s=0.5, client_limits=relay_cfg.limits)


@pytest.mark.asyncio
async def test_relay_startup_check_timeout(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.info_handler_mode = InfoHandlerMode.TIMEOUT
    relay_cfg = RelayConfig(base_url=base_url)

    with pytest.raises(RelayStartupCheckError, match="timeout"):
        await check_relay_startup(relay_cfg, timeout_s=0.05, client_limits=relay_cfg.limits)
