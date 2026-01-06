import base64
import gzip
import json

import aiohttp
import pytest
from fake_relay.types import DnsItemResult


@pytest.mark.asyncio
async def test_info_returns_v_and_limits(fake_relay_server):
    base_url, _controller = fake_relay_server
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/v1/info") as resp:
            assert resp.status == 200
            data = await resp.json()

    assert data["v"] == 1
    assert "limits" in data
    assert data["auth_required"] is False


@pytest.mark.asyncio
async def test_info_requires_auth_when_configured(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.expected_token = "secret"

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/v1/info") as resp:
            assert resp.status == 401

        async with session.get(
            f"{base_url}/v1/info",
            headers={"Authorization": "Bearer secret"},
        ) as resp:
            assert resp.status == 200
            data = await resp.json()

    assert data["auth_required"] is True


@pytest.mark.asyncio
async def test_dns_echoes_id_and_items(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.next_dns_results = [
        DnsItemResult.ok_result("a", b"\x01\x02"),
        DnsItemResult.err_result("b", "timeout"),
    ]

    payload = {
        "v": 1,
        "id": "req-1",
        "items": [
            {"id": "a", "q": base64.b64encode(b"q1").decode("ascii")},
            {"id": "b", "q": base64.b64encode(b"q2").decode("ascii")},
        ],
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base_url}/v1/dns", json=payload) as resp:
            assert resp.status == 200
            data = await resp.json()

    assert data["id"] == "req-1"
    assert data["v"] == 1
    assert len(data["items"]) == 2

    item_by_id = {item["id"]: item for item in data["items"]}
    assert item_by_id["a"]["ok"] is True
    assert base64.b64decode(item_by_id["a"]["a"]) == b"\x01\x02"
    assert item_by_id["b"]["ok"] is False
    assert item_by_id["b"]["err"] == "timeout"


@pytest.mark.asyncio
async def test_dns_gzip_response(fake_relay_server):
    base_url, controller = fake_relay_server
    controller.script.next_dns_results = [DnsItemResult.ok_result("a", b"")]

    payload = {
        "v": 1,
        "id": "req-2",
        "items": [{"id": "a", "q": base64.b64encode(b"q").decode("ascii")}],
    }

    async with aiohttp.ClientSession(auto_decompress=False) as session:
        async with session.post(
            f"{base_url}/v1/dns",
            json=payload,
            headers={"Accept-Encoding": "gzip"},
        ) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Encoding") == "gzip"
            body = await resp.read()

    decompressed = gzip.decompress(body)
    data = json.loads(decompressed.decode("utf-8"))
    assert data["id"] == "req-2"
    assert data["items"][0]["ok"] is True
