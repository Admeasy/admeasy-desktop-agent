"""Wait until the screen stops changing before post-action screenshots."""
from __future__ import annotations

import hashlib
import time


def _thumb_hash(screenshot_fn) -> str:
    shot = screenshot_fn(som=False)
    raw = shot.get("screenshot_b64") or ""
    return hashlib.sha256(raw.encode("ascii")).hexdigest()[:16]


def wait_for_settle(screenshot_fn, *, max_wait_s: float = 3.0, poll_s: float = 0.2, stable_polls: int = 2) -> float:
    """
    Poll lightweight screenshot hashes until stable or timeout.
    Returns seconds waited.
    """
    t0 = time.monotonic()
    last = _thumb_hash(screenshot_fn)
    stable = 0
    while time.monotonic() - t0 < max_wait_s:
        time.sleep(poll_s)
        cur = _thumb_hash(screenshot_fn)
        if cur == last:
            stable += 1
            if stable >= stable_polls:
                return time.monotonic() - t0
        else:
            stable = 0
            last = cur
    return time.monotonic() - t0
