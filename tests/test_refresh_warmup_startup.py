from pathlib import Path

from resilientdns.cache.memory import CacheConfig, MemoryDnsCache
from resilientdns.dns.handler import DnsHandler, HandlerConfig
from resilientdns.metrics import Metrics
from resilientdns.refresh_warmup import enqueue_warmup_file


class StubUpstream:
    async def query(self, wire: bytes):
        return None


def _make_handler(metrics: Metrics, refresh_queue_max: int = 10) -> DnsHandler:
    return DnsHandler(
        upstream=StubUpstream(),
        cache=MemoryDnsCache(CacheConfig()),
        metrics=metrics,
        config=HandlerConfig(refresh_queue_max=refresh_queue_max),
    )


def test_warmup_enqueues_up_to_limit(tmp_path: Path):
    lines = [f"example{i}.com A" for i in range(5)]
    path = tmp_path / "warmup.txt"
    path.write_text("\n".join(lines), encoding="utf-8")

    metrics = Metrics()
    handler = _make_handler(metrics)

    loaded, invalid, enqueued = enqueue_warmup_file(
        path,
        handler.enqueue_refresh,
        limit=2,
        metrics=metrics,
    )

    assert loaded == 2
    assert invalid == 0
    assert enqueued == 2
    assert handler.refresh_queue.qsize() == 2
    snapshot = metrics.snapshot()
    assert snapshot.get("cache_refresh_warmup_loaded_total") == 2


def test_warmup_ignores_invalid_lines_counts_metrics(tmp_path: Path):
    text = "\n".join(
        [
            "example.com",
            "example.net A",
            "bad.invalidtype TYPE9999",
        ]
    )
    path = tmp_path / "warmup.txt"
    path.write_text(text, encoding="utf-8")

    metrics = Metrics()
    handler = _make_handler(metrics)

    loaded, invalid, enqueued = enqueue_warmup_file(
        path,
        handler.enqueue_refresh,
        limit=10,
        metrics=metrics,
    )

    assert loaded == 1
    assert invalid == 2
    assert enqueued == 1
    snapshot = metrics.snapshot()
    assert snapshot.get("cache_refresh_warmup_loaded_total") == 1
    assert snapshot.get("cache_refresh_warmup_invalid_lines_total") == 2


def test_warmup_respects_queue_bounds_drops_when_full(tmp_path: Path):
    lines = [f"example{i}.com A" for i in range(3)]
    path = tmp_path / "warmup.txt"
    path.write_text("\n".join(lines), encoding="utf-8")

    metrics = Metrics()
    handler = _make_handler(metrics, refresh_queue_max=1)

    loaded, invalid, enqueued = enqueue_warmup_file(
        path,
        handler.enqueue_refresh,
        limit=3,
        metrics=metrics,
    )

    assert loaded == 3
    assert invalid == 0
    assert enqueued == 1
    snapshot = metrics.snapshot()
    assert snapshot.get("cache_refresh_dropped_total{reason=queue_full}") == 2


def test_warmup_dedup(tmp_path: Path):
    path = tmp_path / "warmup.txt"
    path.write_text("example.com A\nexample.com A\n", encoding="utf-8")

    metrics = Metrics()
    handler = _make_handler(metrics)

    loaded, invalid, enqueued = enqueue_warmup_file(
        path,
        handler.enqueue_refresh,
        limit=10,
        metrics=metrics,
    )

    assert loaded == 2
    assert invalid == 0
    assert enqueued == 1
    snapshot = metrics.snapshot()
    assert snapshot.get("cache_refresh_dropped_total{reason=duplicate}") == 1
