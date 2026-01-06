from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DnsHandlerMode(str, Enum):
    NORMAL = "normal"
    TIMEOUT = "timeout"


class ParseErrorMode(str, Enum):
    RETURN_400 = "return_400"
    RETURN_INVALID_JSON_200 = "return_invalid_json_200"


@dataclass
class RelayLimits:
    max_items: int = 32
    max_request_bytes: int = 65536
    per_item_max_wire_bytes: int = 4096
    max_response_bytes: int = 262144

    def as_dict(self) -> dict[str, int]:
        return {
            "max_items": self.max_items,
            "max_request_bytes": self.max_request_bytes,
            "per_item_max_wire_bytes": self.per_item_max_wire_bytes,
            "max_response_bytes": self.max_response_bytes,
        }


@dataclass
class DnsItemResult:
    item_id: str
    ok: bool
    response_bytes: bytes | None = None
    err: str | None = None

    @classmethod
    def ok_result(cls, item_id: str, response_bytes: bytes) -> DnsItemResult:
        return cls(item_id=item_id, ok=True, response_bytes=response_bytes)

    @classmethod
    def err_result(cls, item_id: str, err: str) -> DnsItemResult:
        return cls(item_id=item_id, ok=False, err=err)


InfoResponse = Callable[["RelayScript"], dict[str, Any]] | dict[str, Any]
DnsResultsFactory = Callable[[dict[str, Any]], list[DnsItemResult]]


# Tests mutate this script to drive deterministic responses and capture requests.


@dataclass
class RelayScript:
    expected_token: str | None = None
    info_response: InfoResponse | None = None
    dns_handler_mode: DnsHandlerMode = DnsHandlerMode.NORMAL
    next_dns_results: list[DnsItemResult] | DnsResultsFactory | None = None
    force_http_status: int | None = None
    force_invalid_json: bool = False
    parse_error_mode: ParseErrorMode = ParseErrorMode.RETURN_400
    force_protocol_v: int | None = None
    enforce_limits: bool = False
    limits: RelayLimits = field(default_factory=RelayLimits)
    timeout_event: asyncio.Event = field(default_factory=asyncio.Event)

    last_request_headers: dict[str, str] | None = None
    last_request_body: bytes | None = None
    last_request_json: Any = None
    received_dns_batches: list[dict[str, Any]] = field(default_factory=list)
