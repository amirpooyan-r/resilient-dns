from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class RelayConfig:
    base_url: str
    api_version: int = 1
    auth_token: str | None = None
    startup_check: Literal["require", "warn", "off"] = "require"
    limits: RelayLimits = field(default_factory=RelayLimits)

    @property
    def info_url(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/v{self.api_version}/info"

    @property
    def dns_url(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/v{self.api_version}/dns"


@dataclass(frozen=True)
class RelayDnsItemRequest:
    id: str
    q_b64: str


@dataclass(frozen=True)
class RelayDnsRequest:
    v: int
    id: str
    items: list[RelayDnsItemRequest]

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "id": self.id,
            "items": [{"id": item.id, "q": item.q_b64} for item in self.items],
        }


@dataclass(frozen=True)
class RelayDnsItemResponse:
    id: str
    ok: bool
    a_b64: str | None = None
    err: str | None = None


@dataclass(frozen=True)
class RelayDnsResponse:
    v: int
    id: str
    items: list[RelayDnsItemResponse]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelayDnsResponse:
        if not isinstance(data, dict):
            raise ValueError("response must be an object")

        for key in ("v", "id", "items"):
            if key not in data:
                raise ValueError(f"missing field: {key}")

        v = data["v"]
        if not isinstance(v, int):
            raise ValueError("field 'v' must be an int")

        request_id = data["id"]
        if not isinstance(request_id, str):
            raise ValueError("field 'id' must be a string")

        items = data["items"]
        if not isinstance(items, list):
            raise ValueError("field 'items' must be a list")

        parsed_items: list[RelayDnsItemResponse] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("item must be an object")
            if "id" not in item:
                raise ValueError("item missing field: id")
            if "ok" not in item:
                raise ValueError("item missing field: ok")

            item_id = item["id"]
            if not isinstance(item_id, str):
                raise ValueError("item field 'id' must be a string")

            ok = item["ok"]
            if not isinstance(ok, bool):
                raise ValueError("item field 'ok' must be a bool")

            if ok:
                payload = item.get("a")
                if not isinstance(payload, str):
                    raise ValueError("ok item missing field: a")
                parsed_items.append(
                    RelayDnsItemResponse(id=item_id, ok=True, a_b64=payload, err=None)
                )
            else:
                err = item.get("err")
                if not isinstance(err, str):
                    raise ValueError("error item missing field: err")
                parsed_items.append(RelayDnsItemResponse(id=item_id, ok=False, a_b64=None, err=err))

        return cls(v=v, id=request_id, items=parsed_items)


def validate_limits(limits: RelayLimits) -> None:
    for name, value in limits.as_dict().items():
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be > 0")


def validate_startup_check(value: str) -> None:
    if value not in ("require", "warn", "off"):
        raise ValueError("relay_startup_check must be 'require', 'warn', or 'off'")


def validate_base_url(base_url: str) -> None:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("relay_base_url must be non-empty")
    if base_url.strip() != base_url:
        raise ValueError("relay_base_url must not include surrounding whitespace")

    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("relay_base_url must start with http:// or https://")
    if not parts.netloc:
        raise ValueError("relay_base_url must include a host")
    if parts.query or parts.fragment:
        raise ValueError("relay_base_url must not include a querystring or fragment")
