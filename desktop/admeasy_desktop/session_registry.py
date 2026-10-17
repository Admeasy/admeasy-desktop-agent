"""Execution sessions (terminal, cli) exposed as facts for status / backend orchestration."""
from __future__ import annotations

from typing import Any


def snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {"terminal": [], "cli": []}
    try:
        from .executors import terminal_exec

        for sid, sess in getattr(terminal_exec, "_STORE", {}).items():
            out["terminal"].append(
                {
                    "session_id": sid,
                    "alive": sess.proc.returncode is None,
                    "bytes_buffered": sum(len(x) for x in sess.buf),
                }
            )
    except Exception:
        pass
    try:
        from .executors import cli_exec

        for sid, meta in getattr(cli_exec, "_SESSIONS", {}).items():
            out["cli"].append({"session_id": sid, **meta})
    except Exception:
        pass
    return out
