import asyncio
import socket
from dataclasses import dataclass

from resilientdns.metrics import Metrics


@dataclass(frozen=True)
class UpstreamUdpConfig:
    host: str = "1.1.1.1"
    port: int = 53
    timeout_s: float = 2.0


class UdpUpstreamForwarder:
    """
    Minimal UDP forwarder to a classic DNS upstream.
    This is ONLY for early testing. We'll replace it with the batch gateway client.
    """

    def __init__(self, config: UpstreamUdpConfig, metrics: Metrics | None = None):
        self.config = config
        self.metrics = metrics

    async def query(self, wire: bytes) -> bytes | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._query_blocking, wire)

    def _query_blocking(self, wire: bytes) -> bytes | None:
        if self.metrics:
            self.metrics.inc("upstream_requests_total")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(self.config.timeout_s)
        try:
            s.sendto(wire, (self.config.host, self.config.port))
            data, _ = s.recvfrom(4096)
            return data
        except Exception:
            if self.metrics:
                self.metrics.inc("upstream_fail_total")
            return None
        finally:
            s.close()
