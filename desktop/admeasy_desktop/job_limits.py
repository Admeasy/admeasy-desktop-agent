"""Per-tool timeouts (no global job/step cap on the desktop agent)."""
from __future__ import annotations

# Defaults are per tool call only; the backend ReAct loop owns iteration limits.
TOOL_DEFAULT_TIMEOUT_S = {
    "status": 30,
    "screenshot": 60,
    "screen": 120,
    "clipboard": 30,
    "notify": 15,
    "open": 60,
    "app": 120,
    "browser": 600,
    "cua": 120,
    "files": 120,
    "mail": 120,
    "messages": 120,
    "comms": 120,
    "whatsapp": 180,
    "ide": 300,
    "shell": 600,
    "terminal": 600,
    "cli": 600,
    "signin": 600,
}
FALLBACK_TIMEOUT_S = 600
MAX_TOOL_TIMEOUT_S = 1800
SHELL_DEFAULT_TIMEOUT_S = 600
BROWSER_MAX_TIMEOUT_S = 1800

# Back-compat alias for tests that referenced job-level names
DEFAULT_TIMEOUT_S = TOOL_DEFAULT_TIMEOUT_S


def tool_timeout_s(kind: str, job: dict, params: dict) -> float:
    """Per-tool wall clock for a single dispatch (params.timeout_s overrides)."""
    for v in ((job or {}).get("timeout_s"), (params or {}).get("timeout_s")):
        try:
            if v is not None and float(v) > 0:
                return min(float(v), MAX_TOOL_TIMEOUT_S)
        except (TypeError, ValueError):
            pass
    if kind == "browser":
        return float(TOOL_DEFAULT_TIMEOUT_S["browser"])
    return float(TOOL_DEFAULT_TIMEOUT_S.get(kind, FALLBACK_TIMEOUT_S))


def job_timeout_s(kind: str, job: dict, params: dict) -> float:
    """Deprecated name: same as tool_timeout_s (kept for existing imports)."""
    return tool_timeout_s(kind, job, params)


def job_idempotency_key(job_id: str, params: dict) -> str:
    key = str((params or {}).get("idempotency_key") or "").strip()
    return key or f"job:{job_id}"
