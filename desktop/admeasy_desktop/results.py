"""Normalize executor payloads into honest tunnel result messages for the backend."""
from __future__ import annotations

from .typed_status import LEGACY_ERR, LEGACY_OK, normalize_status

TERMINAL = frozenset(
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
        "done",
        "failed",
        "denied",
        "needs_permission",
        "cancelled",
    }
)


def normalize(kind: str, out: dict | None) -> dict:
    if not isinstance(out, dict):
        return {"status": "error", "error": "executor returned no result"}
    raw_status = out.get("status")
    status = normalize_status(str(raw_status) if raw_status is not None else "error")
    if raw_status not in TERMINAL and status == "error":
        return {"status": "error", "error": f"invalid executor status: {raw_status!r}"}
    res = {"status": status}
    if out.get("result") is not None:
        res["result"] = out["result"]
    err = out.get("error")
    reason = (out.get("result") or {}).get("reason") if isinstance(out.get("result"), dict) else None
    if err:
        res["error"] = str(err)
    elif reason and status != "ok":
        res["error"] = str(reason)
    elif status in LEGACY_ERR or status in ("error", "timeout", "blocked", "rate_limited", "captcha"):
        res["error"] = res.get("error") or status.replace("_", " ")
    elif status in ("needs_login", "needs_human", "permission_missing"):
        res["error"] = res.get("error") or status.replace("_", " ")

    if status == "ok" and kind in ("shell", "terminal", "cli"):
        ec = (out.get("result") or {}).get("exit_code")
        if ec not in (0, None):
            res["status"] = "error"
            res["error"] = f"command exited with code {ec}"
    if status == "ok" and kind == "open":
        if out.get("error"):
            res["status"] = "error"
            res["error"] = str(out["error"])
    return res
