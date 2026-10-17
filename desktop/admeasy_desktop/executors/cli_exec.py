"""Managed CLI sessions: Claude Code, Gemini CLI, Cursor agent, git, etc."""
from __future__ import annotations

import os
import shutil
import sys

from . import terminal_exec

_PROFILES: dict[str, dict] = {
    "claude": {"command": "claude", "args": []},
    "gemini": {"command": "gemini", "args": []},
    "cursor": {"command": "cursor-agent", "args": []},
    "git": {"command": "git", "args": []},
}


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


async def run(p: dict, on_output=None) -> dict:
    op = p.get("op") or "run"
    profile = str(p.get("profile") or "git")
    prof = _PROFILES.get(profile, {"command": profile, "args": []})
    bin_name = prof["command"]
    path = _which(bin_name)
    if not path and profile in ("claude", "gemini", "cursor"):
        return {
            "status": "failed",
            "error": f"{bin_name} not found on PATH — install the {profile} CLI and retry",
        }
    if not path:
        path = bin_name

    if op == "profiles":
        found = [k for k, v in _PROFILES.items() if _which(v["command"]) or k == "git"]
        return {"status": "done", "result": {"profiles": found}}

    if op == "run":
        args = list(prof.get("args") or [])
        prompt = str(p.get("prompt") or p.get("command") or "")
        cwd = os.path.expanduser(str(p.get("cwd") or "~"))
        if profile == "git":
            cmd = prompt if prompt.startswith("git ") else f"git {prompt}"
        elif profile in ("claude", "gemini", "cursor"):
            # Non-interactive one-shot when prompt is provided.
            if profile == "claude":
                cmd = f'"{path}" -p { _shell_quote(prompt) }'
            elif profile == "gemini":
                cmd = f'"{path}" { _shell_quote(prompt) }'
            else:
                cmd = f'"{path}" -p { _shell_quote(prompt) }'
        else:
            extra = " ".join(_shell_quote(str(a)) for a in (p.get("args") or []))
            cmd = f'"{path}" {extra} { _shell_quote(prompt) }'.strip()
        return await terminal_exec.run(
            {"op": "run", "command": cmd, "cwd": cwd, "timeout_s": p.get("timeout_s", 600)},
            on_output=on_output,
        )

    if op == "spawn":
        init = str(p.get("init") or "")
        cwd = os.path.expanduser(str(p.get("cwd") or "~"))
        if profile == "git":
            boot = init or "git status"
        else:
            boot = f'"{path}"' + (f" {init}" if init else "")
        spawned = await terminal_exec.run({"op": "spawn", "cwd": cwd}, on_output=on_output)
        if spawned.get("status") != "done":
            return spawned
        sid = spawned["result"]["session_id"]
        if boot.strip():
            await terminal_exec.run({"op": "write", "session_id": sid, "data": boot})
        return {"status": "done", "result": {"session_id": sid, "profile": profile}}

    if op in ("write", "read", "close", "list"):
        return await terminal_exec.run({**p, "op": op}, on_output=on_output)

    return {"status": "failed", "error": f"unknown cli op {op}"}


def _shell_quote(s: str) -> str:
    if sys.platform == "win32":
        return "'" + s.replace("'", "''") + "'"
    import shlex

    return shlex.quote(s)
