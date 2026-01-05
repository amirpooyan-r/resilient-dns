import asyncio
import time
from dataclasses import dataclass

from resilientdns.metrics import Metrics


@dataclass(frozen=True)
class UpstreamTcpConfig:
    host: str = "1.1.1.1"
    port: int = 53
    connect_timeout_s: float = 2.0
    read_timeout_s: float = 2.0
    max_message_size: int = 65535
    pool_max_conns: int = 4
    pool_idle_timeout_s: float = 30.0
    max_inflight: int = 0


@dataclass
class _PooledConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    last_used_s: float


class TcpUpstreamForwarder:
    def __init__(self, config: UpstreamTcpConfig, metrics: Metrics | None = None):
        self.config = config
        self.metrics = metrics
        self._pool: list[_PooledConnection] = []
        self._pool_lock = asyncio.Lock()
        self._closed = False
        if config.max_inflight > 0:
            self._max_inflight = config.max_inflight
            self._inflight = 0
            self._inflight_lock = asyncio.Lock()
        else:
            self._max_inflight = 0
            self._inflight = 0
            self._inflight_lock = None

    async def close(self) -> None:
        self._closed = True
        async with self._pool_lock:
            conns = self._pool
            self._pool = []
        for conn in conns:
            await self._close_writer(conn.writer)

    async def _close_writer(self, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=0.2)
        except Exception:
            pass

    async def _acquire_from_pool(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
        if self._closed or self.config.pool_max_conns <= 0:
            return None
        now = time.monotonic()
        async with self._pool_lock:
            while self._pool:
                conn = self._pool.pop()
                if conn.writer.is_closing() or conn.reader.at_eof():
                    await self._close_writer(conn.writer)
                    continue
                if self.config.pool_idle_timeout_s <= 0:
                    await self._close_writer(conn.writer)
                    continue
                if now - conn.last_used_s > self.config.pool_idle_timeout_s:
                    await self._close_writer(conn.writer)
                    continue
                return conn.reader, conn.writer
        return None

    async def _release_to_pool(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if self._closed or self.config.pool_max_conns <= 0:
            await self._close_writer(writer)
            return
        if writer.is_closing() or reader.at_eof():
            await self._close_writer(writer)
            return
        async with self._pool_lock:
            if len(self._pool) >= self.config.pool_max_conns:
                await self._close_writer(writer)
                return
            self._pool.append(
                _PooledConnection(reader=reader, writer=writer, last_used_s=time.monotonic())
            )

    async def query(self, wire: bytes) -> bytes | None:
        if self._max_inflight > 0 and self._inflight_lock is not None:
            async with self._inflight_lock:
                if self._inflight >= self._max_inflight:
                    if self.metrics:
                        self.metrics.inc("dropped_total")
                    return None
                self._inflight += 1
        reader = None
        writer = None
        errored = True
        try:
            if self.metrics:
                self.metrics.inc("upstream_requests_total")

            conn = await self._acquire_from_pool()
            if conn is None:
                try:
                    conn = await asyncio.wait_for(
                        asyncio.open_connection(self.config.host, self.config.port),
                        timeout=self.config.connect_timeout_s,
                    )
                except Exception:
                    return None
            reader, writer = conn
            errored = False

            try:
                writer.write(len(wire).to_bytes(2, "big") + wire)
                await writer.drain()

                try:
                    length_bytes = await asyncio.wait_for(
                        reader.readexactly(2), timeout=self.config.read_timeout_s
                    )
                except Exception:
                    errored = True
                    return None

                msg_len = int.from_bytes(length_bytes, "big")
                if self.config.max_message_size > 0 and msg_len > self.config.max_message_size:
                    if self.metrics:
                        self.metrics.inc("dropped_total")
                    errored = True
                    return None

                try:
                    data = await asyncio.wait_for(
                        reader.readexactly(msg_len), timeout=self.config.read_timeout_s
                    )
                except Exception:
                    errored = True
                    return None

                if self.config.max_message_size > 0 and len(data) > self.config.max_message_size:
                    if self.metrics:
                        self.metrics.inc("dropped_total")
                    errored = True
                    return None

                return data
            except Exception:
                errored = True
                return None
            finally:
                if writer is not None:
                    if errored:
                        await self._close_writer(writer)
                    else:
                        await self._release_to_pool(reader, writer)
        finally:
            if self._max_inflight > 0 and self._inflight_lock is not None:
                async with self._inflight_lock:
                    self._inflight -= 1
