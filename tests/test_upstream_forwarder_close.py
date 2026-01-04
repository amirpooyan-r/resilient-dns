from resilientdns.upstream.udp_forwarder import UdpUpstreamForwarder, UpstreamUdpConfig


def test_udp_forwarder_close_idempotent():
    forwarder = UdpUpstreamForwarder(UpstreamUdpConfig())
    forwarder.close()
    forwarder.close()
