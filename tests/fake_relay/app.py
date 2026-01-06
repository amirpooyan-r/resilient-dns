from __future__ import annotations

import base64
import gzip
import json
from typing import Any

from aiohttp import web

from .types import (
    DnsHandlerMode,
    DnsItemResult,
    InfoHandlerMode,
    ParseErrorMode,
    RelayScript,
)

SCRIPT_KEY = web.AppKey("relay_script", RelayScript)
CAPTURE_KEY = web.AppKey("relay_capture", dict[str, Any])


def create_app(script: RelayScript) -> web.Application:
    app = web.Application()
    app[SCRIPT_KEY] = script
    app[CAPTURE_KEY] = {}
    app.router.add_get("/v1/info", handle_info)
    app.router.add_post("/v1/dns", handle_dns)
    return app


def _capture_request(script: RelayScript, request: web.Request, body: bytes, data: Any) -> None:
    script.last_request_headers = dict(request.headers)
    script.last_request_body = body
    script.last_request_json = data
    capture = request.app[CAPTURE_KEY]
    capture["last_request_headers"] = script.last_request_headers
    capture["last_request_body"] = script.last_request_body
    capture["last_request_json"] = script.last_request_json


def _auth_required(script: RelayScript, request: web.Request) -> bool:
    if script.expected_token is None:
        return False
    auth = request.headers.get("Authorization", "")
    return auth != f"Bearer {script.expected_token}"


def _accepts_gzip(request: web.Request) -> bool:
    enc = request.headers.get("Accept-Encoding", "")
    return "gzip" in enc.lower()


def _response_json(request: web.Request, payload: dict[str, Any]) -> web.Response:
    body = json.dumps(payload).encode("utf-8")
    if _accepts_gzip(request):
        body = gzip.compress(body)
        return web.Response(
            body=body,
            status=200,
            content_type="application/json",
            headers={"Content-Encoding": "gzip"},
        )
    return web.Response(body=body, status=200, content_type="application/json")


def _invalid_json_response(request: web.Request) -> web.Response:
    body = b"{invalid"
    if _accepts_gzip(request):
        body = gzip.compress(body)
        return web.Response(
            body=body,
            status=200,
            content_type="application/json",
            headers={"Content-Encoding": "gzip"},
        )
    return web.Response(body=body, status=200, content_type="application/json")


def _parse_content_encoding(request: web.Request) -> str | None:
    enc = request.headers.get("Content-Encoding", "").strip().lower()
    return enc or None


def _decode_json_body(script: RelayScript, request: web.Request, body: bytes) -> Any | None:
    if script.force_invalid_json:
        return _invalid_json_response(request)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        if script.parse_error_mode == ParseErrorMode.RETURN_INVALID_JSON_200:
            return _invalid_json_response(request)
        return None


def _coerce_results(script: RelayScript, data: dict[str, Any]) -> list[DnsItemResult]:
    results = script.next_dns_results
    if callable(results):
        return results(data)
    if isinstance(results, list):
        return results
    return []


async def handle_info(request: web.Request) -> web.Response:
    script: RelayScript = request.app[SCRIPT_KEY]
    _capture_request(script, request, b"", None)

    if script.info_handler_mode == InfoHandlerMode.TIMEOUT:
        # Deterministic timeout: the test controls when/if the event is set.
        await script.info_timeout_event.wait()

    if _auth_required(script, request):
        return web.Response(status=401)

    if script.force_http_status is not None:
        return web.Response(status=script.force_http_status)

    info: dict[str, Any]
    if script.info_response is None:
        info = {
            "v": 1,
            "limits": script.limits.as_dict(),
            "auth_required": script.expected_token is not None,
        }
    elif callable(script.info_response):
        info = script.info_response(script)
    else:
        info = dict(script.info_response)

    if script.force_protocol_v is not None:
        info["v"] = script.force_protocol_v

    return _response_json(request, info)


async def handle_dns(request: web.Request) -> web.Response:
    script: RelayScript = request.app[SCRIPT_KEY]

    if _auth_required(script, request):
        _capture_request(script, request, b"", None)
        return web.Response(status=401)

    if script.force_http_status is not None:
        _capture_request(script, request, b"", None)
        return web.Response(status=script.force_http_status)

    if script.dns_handler_mode == DnsHandlerMode.TIMEOUT:
        _capture_request(script, request, b"", None)
        # Deterministic timeout: the test controls when/if the event is set.
        await script.timeout_event.wait()

    body = await request.read()

    content_encoding = _parse_content_encoding(request)
    if content_encoding:
        if content_encoding != "gzip":
            _capture_request(script, request, body, None)
            return web.Response(status=415)
        try:
            body = gzip.decompress(body)
        except OSError:
            _capture_request(script, request, body, None)
            return web.Response(status=400)

    if script.enforce_limits and len(body) > script.limits.max_request_bytes:
        _capture_request(script, request, body, None)
        return web.Response(status=413)

    data = _decode_json_body(script, request, body)
    if isinstance(data, web.Response):
        _capture_request(script, request, body, None)
        return data
    if data is None:
        _capture_request(script, request, body, None)
        return web.Response(status=400)

    _capture_request(script, request, body, data)
    script.received_dns_batches.append(data)

    if not isinstance(data, dict):
        return web.Response(status=400)

    if not isinstance(data.get("v"), int):
        return web.Response(status=400)

    items = data.get("items")
    if not isinstance(items, list):
        return web.Response(status=400)

    if script.enforce_limits and len(items) > script.limits.max_items:
        return web.Response(status=400)

    request_id = data.get("id")
    results = _coerce_results(script, data)
    response_items: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return web.Response(status=400)
        item_id = item.get("id")
        q = item.get("q")
        if not isinstance(item_id, str) or not isinstance(q, str):
            return web.Response(status=400)
        try:
            wire = base64.b64decode(q, validate=True)
        except (ValueError, TypeError):
            return web.Response(status=400)

        forced_too_large = (
            script.enforce_limits and len(wire) > script.limits.per_item_max_wire_bytes
        )

        result = results[index] if index < len(results) else None
        if result is None:
            result = DnsItemResult.ok_result(item_id=item_id, response_bytes=b"")
        elif result.item_id != item_id:
            result = DnsItemResult(
                item_id=item_id,
                ok=result.ok,
                response_bytes=result.response_bytes,
                err=result.err,
            )

        if forced_too_large:
            # When enforcing limits, per-item violations are returned
            # # as ok=false with err=too_large.
            response_items.append({"id": item_id, "ok": False, "err": "too_large"})
            continue

        if result.ok:
            payload = base64.b64encode(result.response_bytes or b"").decode("ascii")
            response_items.append({"id": item_id, "ok": True, "a": payload})
        else:
            response_items.append({"id": item_id, "ok": False, "err": result.err or ""})

    response_v = script.force_protocol_v if script.force_protocol_v is not None else data["v"]
    response = {"v": response_v, "id": request_id, "items": response_items}
    return _response_json(request, response)
