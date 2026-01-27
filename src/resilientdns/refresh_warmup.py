from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dnslib import CLASS, QTYPE

WarmupItem = tuple[str, int, int]


def parse_warmup_source(source: str | Path) -> tuple[list[WarmupItem], int]:
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
    else:
        text = source

    items: list[WarmupItem] = []
    invalid = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            invalid += 1
            continue
        qname_raw, qtype_raw = parts
        qname = _normalize_qname(qname_raw)
        if not qname:
            invalid += 1
            continue
        qtype_id = _parse_qtype(qtype_raw)
        if qtype_id is None:
            invalid += 1
            continue
        items.append((qname, qtype_id, CLASS.IN))
    return items, invalid


def enqueue_warmup_file(
    source: str | Path,
    enqueue_fn: Callable[[WarmupItem, str], bool],
    *,
    limit: int,
    metrics=None,
) -> tuple[int, int, int]:
    items, invalid = parse_warmup_source(source)
    loaded = min(len(items), limit) if limit > 0 else 0
    if metrics:
        metrics.inc("cache_refresh_warmup_loaded_total", loaded)
        metrics.inc("cache_refresh_warmup_invalid_lines_total", invalid)
    enqueued = 0
    for item in items[:loaded]:
        if enqueue_fn(item, "warmup"):
            enqueued += 1
    return loaded, invalid, enqueued


def _normalize_qname(qname: str) -> str:
    return qname.strip().rstrip(".").lower()


def _parse_qtype(token: str) -> int | None:
    if token.isdigit():
        qtype_id = int(token)
        if qtype_id in QTYPE.forward:
            return qtype_id
        return None
    return QTYPE.reverse.get(token.upper())
