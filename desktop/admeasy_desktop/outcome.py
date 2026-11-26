"""Typed tunnel outcome contract (v0.5.1).

Every job ends with this shape on the wire (plus job_id on the envelope).
"""
from __future__ import annotations

from typing import Any

WIRE_STATUSES = frozenset(
    {
        "done",
        "failed",
        "needs_auth",
        "needs_approval",
        "rate_limited",
        "blocked",
    }
)

# Map executor / legacy statuses → (wire_status, code)
_STATUS_MAP: dict[str, tuple[str, str]] = {
    "ok": ("done", "ok"),
    "done": ("done", "ok"),
    "error": ("failed", "error"),
    "failed": ("failed", "error"),
    "timeout": ("failed", "tool_timeout"),
    "cancelled": ("failed", "cancelled"),
    "denied": ("failed", "denied"),
    "needs_login": ("needs_auth", "needs_login"),
    "needs_human": ("needs_auth", "needs_human"),
    "captcha": ("needs_auth", "captcha"),
    "permission_missing": ("blocked", "permission_missing"),
    "needs_permission": ("blocked", "permission_missing"),
    "blocked": ("blocked", "blocked"),
    "rate_limited": ("rate_limited", "rate_limited"),
    "needs_approval": ("needs_approval", "needs_approval"),
    "offline": ("failed", "offline"),
}


def wire_status(legacy: str | None) -> tuple[bool, str, str]:
    key = (legacy or "error").lower()
    status, code = _STATUS_MAP.get(key, ("failed", key or "error"))
    ok = status == "done"
    if status == "rate_limited":
        ok = False
    return ok, status, code


def build(
    legacy_status: str,
    *,
    job_id: str = "",
    detail: str | None = None,
    code: str | None = None,
    connect_url: str | None = None,
    artifacts: dict | list | None = None,
    result: dict | None = None,
    approval_id: str | None = None,
    pending_action: dict | None = None,
) -> dict:
    ok, status, default_code = wire_status(legacy_status)
    out: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "code": code or default_code,
        "detail": (detail or "")[:2000],
    }
    if job_id:
        out["job_id"] = job_id
    if connect_url:
        out["connect_url"] = connect_url[:2000]
    if artifacts is not None:
        out["artifacts"] = artifacts
    if approval_id:
        out["approval_id"] = approval_id
    if pending_action:
        out["pending_action"] = pending_action
    if result is not None:
        out["result"] = result
    return out


def enrich_result_payload(job_id: str, normalized: dict) -> dict:
    """Merge legacy normalize() dict into tunnel result message."""
    legacy = str(normalized.get("status") or "error")
    detail = str(normalized.get("error") or normalized.get("detail") or "")
    body = normalized.get("result")
    connect = None
    if isinstance(body, dict):
        connect = body.get("connect_url") or body.get("upgrade_url")
    oc = build(
        legacy,
        job_id=job_id,
        detail=detail or None,
        result=body if body is not None else None,
        connect_url=str(connect) if connect else None,
        approval_id=normalized.get("approval_id"),
        pending_action=normalized.get("pending_action"),
    )
    msg = {**normalized, **oc}
    # Primary status for new backends; keep legacy alias for one release
    if legacy in ("ok", "done"):
        msg["status"] = "done"
    elif legacy == "needs_approval":
        msg["status"] = "needs_approval"
    return msg