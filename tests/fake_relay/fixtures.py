from __future__ import annotations

from dataclasses import dataclass

import pytest_asyncio
from aiohttp import web

from .app import create_app
from .types import RelayScript


@dataclass
class RelayController:
    script: RelayScript


@pytest_asyncio.fixture
async def fake_relay_server(unused_tcp_port_factory) -> tuple[str, RelayController]:
    port = unused_tcp_port_factory()
    script = RelayScript()
    app = create_app(script)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    base_url = f"http://127.0.0.1:{port}"
    controller = RelayController(script=script)
    try:
        yield base_url, controller
    finally:
        await runner.cleanup()
