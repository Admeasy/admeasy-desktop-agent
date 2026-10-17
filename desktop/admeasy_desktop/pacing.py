"""Per-domain pacing from backend rate_limit_hints (no hardcoded domains)."""
from __future__ import annotations

import random
import time
from typing import Any

_last: dict[str, float] = {}
_counts: dict[str, int] = {}


def wait_if_needed(domain: str, hints: dict[str, Any] | None) -> None:
    if not domain or not hints:
        return
    rpm = float(hints.get("requests_per_minute") or 0)
    jitter_ms = int(hints.get("jitter_ms") or 0)
    daily_cap = int(hints.get("daily_cap") or 0)
    key = domain.lower()
    if daily_cap and _counts.get(key, 0) >= daily_cap:
        time.sleep(60)
    if rpm > 0:
        min_gap = 60.0 / rpm
        last = _last.get(key, 0)
        gap = time.time() - last
        if gap < min_gap:
            time.sleep(min_gap - gap + random.uniform(0, jitter_ms / 1000.0))
    _last[key] = time.time()
    _counts[key] = _counts.get(key, 0) + 1
