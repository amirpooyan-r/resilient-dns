from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import aiohttp

from resilientdns.metrics import Metrics
from resilientdns.relay_types import (
    RelayConfig,
    RelayDnsItemRequest,
    RelayDnsRequest,
    RelayDnsResponse,
)


class RelayUpstreamForwarder:
    def __init__(self, relay_cfg: RelayConfig, metrics: Metrics | None, timeout_s: float) -> None:
        self.relay_cfg = relay_cfg
        self.metrics = metrics
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._session.close()

    async def query(self, wire_query: bytes, *, request_id: str) -> bytes | None:
        if self._closed:
            return None

        limits = self.relay_cfg.limits
        if len(wire_query) > limits.per_item_max_wire_bytes:
            if self.metrics:
                self.metrics.inc("dropped_total")
                self.metrics.inc("dropped_oversize_total")
            return None

        payload = RelayDnsRequest(
            v=1,
            id=request_id,
            items=[
                RelayDnsItemRequest(
                    id="0",
                    q_b64=base64.b64encode(wire_query).decode("ascii"),
                )
            ],
        )
        body = json.dumps(payload.to_dict()).encode("utf-8")
        if len(body) > limits.max_request_bytes:
            if self.metrics:
                self.metrics.inc("dropped_total")
                self.metrics.inc("dropped_oversize_total")
            return None

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        if self.relay_cfg.auth_token:
            headers["Authorization"] = f"Bearer {self.relay_cfg.auth_token}"

        if self.metrics:
            self.metrics.inc("upstream_requests_total")
            self.metrics.inc("upstream_relay_requests_total")

        try:
            async with self._session.post(
                self.relay_cfg.dns_url,
                data=body,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    if 400 <= resp.status < 500:
                        if self.metrics:
                            self.metrics.inc("upstream_relay_http_4xx_total")
                    elif 500 <= resp.status < 600:
                        if self.metrics:
                            self.metrics.inc("upstream_relay_http_5xx_total")
                    else:
                        if self.metrics:
                            self.metrics.inc("upstream_relay_protocol_errors_total")
                    return None
                raw = await resp.read()
        except asyncio.TimeoutError:
            if self.metrics:
                self.metrics.inc("upstream_relay_timeouts_total")
            raise
        except aiohttp.ClientError:
            if self.metrics:
                self.metrics.inc("upstream_relay_client_errors_total")
            return None

        if len(raw) > limits.max_response_bytes:
            if self.metrics:
                self.metrics.inc("upstream_relay_protocol_errors_total")
            raise ValueError("relay response exceeds max_response_bytes")

        data = self._parse_json(raw)
        response = self._parse_response(data)
        if response.v != 1:
            if self.metrics:
                self.metrics.inc("upstream_relay_protocol_errors_total")
            raise ValueError("relay response version mismatch")

        item = None
        for candidate in response.items:
            if candidate.id == "0":
                item = candidate
                break
        if item is None:
            if self.metrics:
                self.metrics.inc("upstream_relay_protocol_errors_total")
            raise ValueError("relay response missing item")

        if item.ok:
            if item.a_b64 is None:
                if self.metrics:
                    self.metrics.inc("upstream_relay_protocol_errors_total")
                raise ValueError("relay response missing payload")
            try:
                return base64.b64decode(item.a_b64, validate=True)
            except (ValueError, TypeError) as exc:
                if self.metrics:
                    self.metrics.inc("upstream_relay_protocol_errors_total")
                raise ValueError("relay response payload invalid base64") from exc

        return None

    def _parse_json(self, raw: bytes) -> dict[str, Any]:
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            if self.metrics:
                self.metrics.inc("upstream_relay_protocol_errors_total")
            raise ValueError("relay response invalid JSON") from exc
        if not isinstance(data, dict):
            if self.metrics:
                self.metrics.inc("upstream_relay_protocol_errors_total")
            raise ValueError("relay response must be an object")
        return data

    def _parse_response(self, data: dict[str, Any]) -> RelayDnsResponse:
        try:
            return RelayDnsResponse.from_dict(data)
        except ValueError as exc:
            if self.metrics:
                self.metrics.inc("upstream_relay_protocol_errors_total")
            raise ValueError(str(exc)) from exc
