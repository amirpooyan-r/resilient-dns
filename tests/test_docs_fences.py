from __future__ import annotations

from pathlib import Path


def test_observability_code_fences():
    doc = Path("docs/observability.md").read_text(encoding="utf-8")
    fence_lines = [line for line in doc.splitlines() if line.startswith("```")]
    assert len(fence_lines) % 2 == 0
    assert all(not line.startswith("``` ") for line in fence_lines)
