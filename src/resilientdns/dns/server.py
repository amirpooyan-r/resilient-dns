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
    max_udp_payload: int = 1232


@dataclass(frozen=True)
class TcpServerConfig:
    host: str = "127.0.0.1"
    port: int = 5353
    max_inflight: int = 256
    max_message_size: int = 65535
    read_timeout_s: float = 2.0
    idle_timeout_s: float = 30.0


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
            logger.debug("Invalid DNS packet from %s", addr)
            if self.metrics:
                self.metrics.inc("malformed_total")
            return

        try:
            resp = await self.handler.handle(req, addr)
            if self.transport:
                wire = resp.pack()
                if self.config.max_udp_payload > 0 and len(wire) > self.config.max_udp_payload:
                    resp.header.tc = 1
                    resp.rr = []
                    resp.auth = []
                    resp.ar = []
                    wire = resp.pack()
                    if len(wire) > self.config.max_udp_payload:
                        if self.metrics:
                            self.metrics.inc("dropped_total")
                        return
                self.transport.sendto(wire, addr)
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
        self._inflight.clear()


class TcpDnsServer:
    """
    Async TCP DNS server with length-prefixed framing.

    handler signature:
        async def handle(request: DNSRecord, client_addr) -> DNSRecord
    """

    def __init__(self, config: TcpServerConfig, handler, metrics: Metrics | None = None):
        self.config = config
        self.handler = handler
        self.metrics = metrics
        self.ready = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._inflight: set[asyncio.Task] = set()
        self._server: asyncio.AbstractServer | None = None

    async def run(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, host=self.config.host, port=self.config.port
        )
        self.ready.set()
        logger.info("Listening on tcp://%s:%d", self.config.host, self.config.port)

        try:
            await self._stop_event.wait()
        finally:
            self._cancel_tasks()
            if self._server:
                self._server.close()
                await self._server.wait_closed()

    def stop(self) -> None:
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self._server:
            self._server.close()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        try:
            while True:
                try:
                    length_bytes = await asyncio.wait_for(
                        reader.readexactly(2), timeout=self.config.idle_timeout_s
                    )
                except asyncio.TimeoutError:
                    return
                except asyncio.IncompleteReadError:
                    return

                msg_len = int.from_bytes(length_bytes, "big")
                if self.config.max_message_size > 0 and msg_len > self.config.max_message_size:
                    if self.metrics:
                        self.metrics.inc("dropped_total")
                    return

                try:
                    data = await asyncio.wait_for(
                        reader.readexactly(msg_len), timeout=self.config.read_timeout_s
                    )
                except asyncio.TimeoutError:
                    return
                except asyncio.IncompleteReadError:
                    return

                if self.config.max_inflight > 0 and len(self._inflight) >= self.config.max_inflight:
                    if self.metrics:
                        self.metrics.inc("dropped_total")
                    return

                task = asyncio.create_task(self._handle_request(data, peer, writer))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
                await task
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_request(self, data: bytes, peer, writer: asyncio.StreamWriter) -> None:
        try:
            req = DNSRecord.parse(data)
        except Exception:
            logger.debug("Invalid DNS packet from %s", peer)
            if self.metrics:
                self.metrics.inc("malformed_total")
            return

        try:
            resp = await self.handler.handle(req, peer)
            wire = resp.pack()
            if self.config.max_message_size > 0 and len(wire) > self.config.max_message_size:
                if self.metrics:
                    self.metrics.inc("dropped_total")
                return
            writer.write(len(wire).to_bytes(2, "big") + wire)
            await writer.drain()
        except Exception:
            logger.exception("Handler failed for %s", peer)

    def _cancel_tasks(self) -> None:
        for task in list(self._inflight):
            if not task.done():
                task.cancel()
        self._inflight.clear()
