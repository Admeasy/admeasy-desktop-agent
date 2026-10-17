"""Tunnel result statuses (v0.4). Facts only in result bodies."""
from __future__ import annotations

STATUSES = frozenset(
    {
        "ok",
        "needs_login",
        "needs_human",
        "offline",
        "blocked",
        "rate_limited",
        "permission_missing",
        "timeout",
        "captcha",
        "error",
        # legacy aliases normalized on wire
        "done",
        "failed",
        "denied",
        "needs_permission",
        "cancelled",
    }
)

# Wire alias: user-visible cancel still reports as cancelled (not mapped to blocked).

LEGACY_OK = frozenset({"done"})
LEGACY_ERR = frozenset({"failed", "denied", "cancelled", "needs_permission"})


def normalize_status(status: str | None) -> str:
    s = (status or "error").lower()
    if s in LEGACY_OK:
        return "ok"
    if s == "needs_permission":
        return "permission_missing"
    if s in LEGACY_ERR:
        return "error" if s == "failed" else s
    if s not in STATUSES:
        return "error"
    return s


def wrap(
    status: str,
    *,
    reason: str | None = None,
    evidence: dict | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> dict:
    """Executor payload before results.normalize."""
    st = normalize_status(status)
    out: dict = {"status": st}
    body = dict(result or {})
    if reason:
        body["reason"] = reason[:500]
    if evidence:
        body["evidence"] = evidence
    if body:
        out["result"] = body
    msg = error or reason
    if msg and st != "ok":
        out["error"] = str(msg)[:800]
    return out
