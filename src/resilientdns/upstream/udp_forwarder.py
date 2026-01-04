import asyncio
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from resilientdns.metrics import Metrics


@dataclass(frozen=True)
class UpstreamUdpConfig:
    host: str = "1.1.1.1"
    port: int = 53
    timeout_s: float = 2.0
    max_workers: int = 32


class UdpUpstreamForwarder:
    """
    Minimal UDP forwarder to a classic DNS upstream.
    This is ONLY for early testing. We'll replace it with the batch gateway client.
    """

    def __init__(self, config: UpstreamUdpConfig, metrics: Metrics | None = None):
        self.config = config
        self.metrics = metrics
        self._executor = ThreadPoolExecutor(max_workers=config.max_workers)
        self._closed = False

    async def query(self, wire: bytes) -> bytes | None:
        if self._closed:
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._query_blocking, wire)

    def _query_blocking(self, wire: bytes) -> bytes | None:
        if self.metrics:
            self.metrics.inc("upstream_requests_total")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(self.config.timeout_s)
        try:
            s.sendto(wire, (self.config.host, self.config.port))
            data, _ = s.recvfrom(65535)
            return data
        except Exception:
            return None
        finally:
            s.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._executor.shutdown(wait=False)
