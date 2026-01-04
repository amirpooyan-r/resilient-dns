import asyncio

from resilientdns.upstream.udp_forwarder import UdpUpstreamForwarder, UpstreamUdpConfig


def test_udp_forwarder_query_after_close_returns_none():
    async def run():
        forwarder = UdpUpstreamForwarder(UpstreamUdpConfig())
        forwarder.close()
        resp = await forwarder.query(b"\x00\x01")
        assert resp is None

    asyncio.run(run())
