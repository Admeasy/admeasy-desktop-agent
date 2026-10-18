"""Per-job idempotency keys and time limits.

The desktop runs one job at a time. A step with no limit of its own used to get 300 s, so one stuck click or
screenshot held the queue for five minutes and every later request from the chat waited behind it.
"""
from __future__ import annotations

# Interactive steps are short; long-running kinds keep a generous limit.
DEFAULT_TIMEOUT_S = {
    "status": 15, "screenshot": 20, "clipboard": 15, "open": 30, "app": 45, "browser": 60, "cua": 60,
    "files": 60, "mail": 60, "messages": 60, "comms": 60, "whatsapp": 90, "ide": 120,
    "shell": 180, "terminal": 300, "cli": 600, "signin": 600,
}
FALLBACK_TIMEOUT_S = 120
MAX_TIMEOUT_S = 1800


def job_timeout_s(kind: str, job: dict, params: dict) -> float:
    """The job's own limit (envelope, then params.timeout_s), else the per-kind default."""
    for v in ((job or {}).get("timeout_s"), (params or {}).get("timeout_s")):
        try:
            if v is not None and float(v) > 0:
                return min(float(v), MAX_TIMEOUT_S)
        except (TypeError, ValueError):
            pass
    return float(DEFAULT_TIMEOUT_S.get(kind, FALLBACK_TIMEOUT_S))


def job_idempotency_key(job_id: str, params: dict) -> str:
    key = str((params or {}).get("idempotency_key") or "").strip()
    return key or f"job:{job_id}"
