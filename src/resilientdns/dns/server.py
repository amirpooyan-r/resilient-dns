import asyncio
import logging
from dataclasses import dataclass

from dnslib import DNSRecord

from resilientdns.metrics import Metrics

logger = logging.getLogger("resilientdns")


@dataclass(frozen=True)
class UdpServerConfig:
    host: str = "127.0.0.1"
    port: int = 5353
    max_inflight: int = 256


class UdpDnsServer(asyncio.DatagramProtocol):
    """
    Async UDP DNS server. Parses incoming DNS packets and delegates to a handler.

    handler signature:
        async def handle(request: DNSRecord, client_addr) -> DNSRecord
    """

    def __init__(self, config: UdpServerConfig, handler, metrics: Metrics | None = None):
        self.config = config
        self.handler = handler
        self.metrics = metrics
        self.transport: asyncio.DatagramTransport | None = None
        self.ready = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._inflight: set[asyncio.Task] = set()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=(self.config.host, self.config.port)
        )
        self.ready.set()
        logger.info("Listening on udp://%s:%d", self.config.host, self.config.port)

        try:
            await self._stop_event.wait()
        finally:
            self._cancel_tasks()
            if self.transport:
                self.transport.close()

    def datagram_received(self, data: bytes, addr):
        if self.config.max_inflight > 0 and len(self._inflight) >= self.config.max_inflight:
            if self.metrics:
                self.metrics.inc("dropped_total")
            return
        task = asyncio.create_task(self._handle_datagram(data, addr))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _handle_datagram(self, data: bytes, addr):
        try:
            req = DNSRecord.parse(data)
        except Exception:
            logger.warning("Invalid DNS packet from %s", addr)
            return

        try:
            resp = await self.handler.handle(req, addr)
            if self.transport:
                self.transport.sendto(resp.pack(), addr)
        except Exception:
            logger.exception("Handler failed for %s", addr)

    def stop(self) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self.transport:
            self.transport.close()

    def _cancel_tasks(self) -> None:
        for task in list(self._inflight):
            if not task.done():
                task.cancel()
