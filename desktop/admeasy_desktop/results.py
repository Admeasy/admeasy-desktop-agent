"""Normalize executor payloads into honest tunnel result messages for the backend."""
from __future__ import annotations

TERMINAL = frozenset(
    {"done", "failed", "denied", "needs_login", "needs_human", "needs_permission", "cancelled"}
)


def normalize(kind: str, out: dict | None) -> dict:
    if not isinstance(out, dict):
        return {"status": "failed", "error": "executor returned no result"}
    status = out.get("status")
    if status not in TERMINAL:
        return {"status": "failed", "error": f"invalid executor status: {status!r}"}
    res = {"status": status}
    if out.get("result") is not None:
        res["result"] = out["result"]
    err = out.get("error")
    if err:
        res["error"] = str(err)
    elif status in ("failed", "denied", "cancelled"):
        res["error"] = res.get("error") or f"job {status}"
    elif status in ("needs_login", "needs_human", "needs_permission"):
        res["error"] = res.get("error") or status.replace("_", " ")

    if status == "done" and kind in ("shell", "terminal", "cli"):
        ec = (out.get("result") or {}).get("exit_code")
        if ec not in (0, None):
            res["status"] = "failed"
            res["error"] = f"command exited with code {ec}"
    if status == "done" and kind == "open":
        if out.get("error"):
            res["status"] = "failed"
            res["error"] = str(out["error"])
    return res
