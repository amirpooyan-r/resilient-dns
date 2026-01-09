import gzip
import json
import os

import aiohttp
import pytest


async def _read_json(resp: aiohttp.ClientResponse) -> dict:
    raw = await resp.read()
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


async def _read_text_maybe_gzip(resp: aiohttp.ClientResponse) -> str:
    raw = await resp.read()
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


@pytest.mark.asyncio
async def test_relay_integration_env():
    base_url = os.getenv("RELAY_BASE_URL")
    if not base_url:
        pytest.skip("RELAY_BASE_URL not set; skipping real relay integration test")

    token = os.getenv("RELAY_AUTH_TOKEN")
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = aiohttp.ClientTimeout(total=5, sock_connect=2)
    base = base_url.rstrip("/")

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{base}/v1/info", headers=headers) as resp:
            assert resp.status == 200
            info = await _read_json(resp)

        assert info.get("protocol_version") == "v1"
        limits = info.get("limits")
        assert isinstance(limits, dict)
        assert limits.get("max_questions") == 1

        payload = {
            "id": "it",
            "question": {
                "qname": "example.com",
                "qtype": "A",
                "qclass": "IN",
            },
        }

        post_headers = dict(headers)
        post_headers["Content-Type"] = "application/json"
        async with session.post(f"{base}/v1/dns", json=payload, headers=post_headers) as resp:
            if resp.status != 200:
                body = await _read_text_maybe_gzip(resp)
                encoding = resp.headers.get("Content-Encoding")
                content_type = resp.headers.get("Content-Type")
                assert resp.status == 200, (
                    f"relay /v1/dns HTTP {resp.status} "
                    f"(encoding={encoding}, content_type={content_type}): "
                    f"{body}"
                )
            data = await _read_json(resp)

    assert data.get("id") == "it"
    assert isinstance(data.get("rcode"), str)
    assert isinstance(data.get("answers"), list)
