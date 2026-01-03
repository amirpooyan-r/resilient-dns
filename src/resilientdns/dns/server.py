import asyncio
import logging
from dataclasses import dataclass

from dnslib import DNSRecord

logger = logging.getLogger("resilientdns")


@dataclass(frozen=True)
class UdpServerConfig:
    host: str = "127.0.0.1"
    port: int = 5353


class UdpDnsServer(asyncio.DatagramProtocol):
    """
    Async UDP DNS server. Parses incoming DNS packets and delegates to a handler.

    handler signature:
        async def handle(request: DNSRecord, client_addr) -> DNSRecord
    """

    def __init__(self, config: UdpServerConfig, handler):
        self.config = config
        self.handler = handler
        self.transport: asyncio.DatagramTransport | None = None
        self.ready = asyncio.Event()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=(self.config.host, self.config.port)
        )
        self.ready.set()
        logger.info("Listening on udp://%s:%d", self.config.host, self.config.port)

        try:
            await asyncio.Future()  # run forever
        finally:
            if self.transport:
                self.transport.close()

    def datagram_received(self, data: bytes, addr):
        asyncio.create_task(self._handle_datagram(data, addr))

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
