import asyncio
from dataclasses import dataclass

from resilientdns.metrics import Metrics


@dataclass(frozen=True)
class UpstreamTcpConfig:
    host: str = "1.1.1.1"
    port: int = 53
    connect_timeout_s: float = 2.0
    read_timeout_s: float = 2.0
    max_message_size: int = 65535


class TcpUpstreamForwarder:
    def __init__(self, config: UpstreamTcpConfig, metrics: Metrics | None = None):
        self.config = config
        self.metrics = metrics

    async def query(self, wire: bytes) -> bytes | None:
        if self.metrics:
            self.metrics.inc("upstream_requests_total")

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.config.host, self.config.port),
                timeout=self.config.connect_timeout_s,
            )
        except Exception:
            return None

        try:
            writer.write(len(wire).to_bytes(2, "big") + wire)
            await writer.drain()

            try:
                length_bytes = await asyncio.wait_for(
                    reader.readexactly(2), timeout=self.config.read_timeout_s
                )
            except Exception:
                return None

            msg_len = int.from_bytes(length_bytes, "big")
            if self.config.max_message_size > 0 and msg_len > self.config.max_message_size:
                if self.metrics:
                    self.metrics.inc("dropped_total")
                return None

            try:
                data = await asyncio.wait_for(
                    reader.readexactly(msg_len), timeout=self.config.read_timeout_s
                )
            except Exception:
                return None

            if self.config.max_message_size > 0 and len(data) > self.config.max_message_size:
                if self.metrics:
                    self.metrics.inc("dropped_total")
                return None

            return data
        finally:
            writer.close()
            await writer.wait_closed()
