from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from resilientdns.relay_types import RelayConfig, RelayLimits


class RelayStartupCheckError(RuntimeError):
    pass


async def check_relay_startup(
    relay_cfg: RelayConfig,
    timeout_s: float,
    client_limits: RelayLimits,
) -> None:
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    if relay_cfg.auth_token:
        headers["Authorization"] = f"Bearer {relay_cfg.auth_token}"

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(relay_cfg.info_url, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise RelayStartupCheckError(
                        "relay auth failed: missing or invalid Authorization token"
                    )
                if resp.status != 200:
                    raise RelayStartupCheckError(f"relay /info returned HTTP {resp.status}")
                raw = await resp.read()
    except asyncio.TimeoutError as exc:
        raise RelayStartupCheckError("relay /info timeout or unreachable") from exc
    except aiohttp.ClientError as exc:
        raise RelayStartupCheckError("relay /info request failed") from exc

    if len(raw) > client_limits.max_response_bytes:
        raise RelayStartupCheckError(
            "relay /info response exceeds max_response_bytes "
            f"(client={client_limits.max_response_bytes} bytes)"
        )

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RelayStartupCheckError("relay /info returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise RelayStartupCheckError("relay /info returned non-object JSON")

    v = data.get("v")
    if not isinstance(v, int):
        raise RelayStartupCheckError("relay /info missing integer field 'v'")
    if v != relay_cfg.api_version:
        raise RelayStartupCheckError(
            f"relay API version mismatch (client={relay_cfg.api_version}, relay={v})"
        )

    limits = data.get("limits")
    if not isinstance(limits, dict):
        raise RelayStartupCheckError("relay /info missing 'limits' object")

    relay_limits = _parse_limits(limits)
    _check_limit_compatibility(client_limits, relay_limits)


async def run_relay_startup_check(
    relay_cfg: RelayConfig,
    timeout_s: float,
    client_limits: RelayLimits,
    mode: str,
    logger: logging.Logger,
) -> None:
    if mode == "off":
        return
    try:
        await check_relay_startup(relay_cfg, timeout_s, client_limits)
    except RelayStartupCheckError as exc:
        if mode == "warn":
            logger.warning("Relay startup check failed: %s", exc)
            return
        raise SystemExit(f"Relay startup check failed: {exc}") from exc


def _parse_limits(data: dict[str, Any]) -> RelayLimits:
    required = (
        "max_items",
        "max_request_bytes",
        "per_item_max_wire_bytes",
        "max_response_bytes",
    )
    missing = [key for key in required if key not in data]
    if missing:
        raise RelayStartupCheckError(f"relay /info missing limits fields: {', '.join(missing)}")

    values: dict[str, int] = {}
    for key in required:
        value = data[key]
        if not isinstance(value, int):
            raise RelayStartupCheckError(f"relay /info limit '{key}' must be an int")
        if value <= 0:
            raise RelayStartupCheckError(f"relay /info limit '{key}' must be > 0")
        values[key] = value

    return RelayLimits(
        max_items=values["max_items"],
        max_request_bytes=values["max_request_bytes"],
        per_item_max_wire_bytes=values["per_item_max_wire_bytes"],
        max_response_bytes=values["max_response_bytes"],
    )


def _check_limit_compatibility(client: RelayLimits, relay: RelayLimits) -> None:
    mismatches = []
    if client.max_items > relay.max_items:
        mismatches.append(("max_items", client.max_items, relay.max_items))
    if client.max_request_bytes > relay.max_request_bytes:
        mismatches.append(("max_request_bytes", client.max_request_bytes, relay.max_request_bytes))
    if client.per_item_max_wire_bytes > relay.per_item_max_wire_bytes:
        mismatches.append(
            (
                "per_item_max_wire_bytes",
                client.per_item_max_wire_bytes,
                relay.per_item_max_wire_bytes,
            )
        )
    if client.max_response_bytes > relay.max_response_bytes:
        mismatches.append(
            ("max_response_bytes", client.max_response_bytes, relay.max_response_bytes)
        )

    if mismatches:
        details = ", ".join(
            f"{name} (client={client_value}, relay={relay_value})"
            for name, client_value, relay_value in mismatches
        )
        raise RelayStartupCheckError(f"relay limits incompatible: {details}")
