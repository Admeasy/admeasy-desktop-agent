"""PTY-backed terminal sessions with streamed output (long-running commands)."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

OnOutput = Callable[[str], Awaitable[None]]


@dataclass
class _Session:
    proc: asyncio.subprocess.Process
    buf: list[str] = field(default_factory=list)


_STORE: dict[str, _Session] = {}


def _shell_argv() -> list[str]:
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-NoLogo"]
    sh = next(
        (c for c in (os.environ.get("SHELL"), "/bin/zsh", "/bin/bash", "/bin/sh") if c and os.path.exists(c)),
        "/bin/sh",
    )
    return [sh, "-l"]


async def _drain(session_id: str, proc: asyncio.subprocess.Process, on_output: OnOutput | None) -> None:
    assert proc.stdout
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        text = chunk.decode(errors="replace")
        sess = _STORE.get(session_id)
        if sess:
            sess.buf.append(text)
            if len(sess.buf) > 200:
                sess.buf = sess.buf[-100:]
        if on_output and text.strip():
            await on_output(text[-300:])


async def run(p: dict, on_output: OnOutput | None = None) -> dict:
    op = p.get("op") or "run"
    if op == "run":
        cmd = str(p.get("command") or "")
        cwd = os.path.expanduser(str(p.get("cwd") or "~"))
        if sys.platform == "win32":
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        else:
            sh = _shell_argv()[0]
            argv = [sh, "-lc", cmd]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout
        chunks: list[str] = []
        deadline = asyncio.get_event_loop().time() + min(int(p.get("timeout_s") or 120), 900)
        while True:
            if asyncio.get_event_loop().time() > deadline:
                proc.kill()
                return {"status": "failed", "error": "command timed out", "result": {"output": "".join(chunks)[-12000:]}}
            try:
                line = await asyncio.wait_for(proc.stdout.read(4096), timeout=0.5)
            except asyncio.TimeoutError:
                if proc.returncode is not None:
                    break
                continue
            if not line:
                break
            text = line.decode(errors="replace")
            chunks.append(text)
            if on_output and text.strip():
                await on_output(text[-300:])
        await proc.wait()
        out = "".join(chunks)[-12000:]
        body = {"exit_code": proc.returncode, "output": out}
        if proc.returncode != 0:
            return {"status": "failed", "error": f"exit {proc.returncode}", "result": body}
        return {"status": "done", "result": body}

    if op == "spawn":
        sid = str(p.get("session_id") or uuid.uuid4())
        cwd = os.path.expanduser(str(p.get("cwd") or "~"))
        proc = await asyncio.create_subprocess_exec(
            *_shell_argv(),
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        _STORE[sid] = _Session(proc=proc)
        asyncio.create_task(_drain(sid, proc, on_output))
        return {"status": "done", "result": {"session_id": sid}}

    if op == "write":
        sid = str(p.get("session_id") or "")
        sess = _STORE.get(sid)
        if not sess or not sess.proc.stdin:
            return {"status": "failed", "error": "unknown session_id"}
        data = str(p.get("data") or "")
        if not data.endswith("\n"):
            data += "\n"
        sess.proc.stdin.write(data.encode())
        await sess.proc.stdin.drain()
        await asyncio.sleep(0.2)
        tail = "".join(sess.buf)[-8000:]
        return {"status": "done", "result": {"session_id": sid, "output": tail}}

    if op == "read":
        sid = str(p.get("session_id") or "")
        sess = _STORE.get(sid)
        if not sess:
            return {"status": "failed", "error": "unknown session_id"}
        return {"status": "done", "result": {"session_id": sid, "output": "".join(sess.buf)[-12000:]}}

    if op == "close":
        sid = str(p.get("session_id") or "")
        sess = _STORE.pop(sid, None)
        if not sess:
            return {"status": "failed", "error": "unknown session_id"}
        if sess.proc.returncode is None:
            sess.proc.terminate()
            try:
                await asyncio.wait_for(sess.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                sess.proc.kill()
        return {"status": "done", "result": {"session_id": sid, "exit_code": sess.proc.returncode}}

    if op == "list":
        return {
            "status": "done",
            "result": {
                "sessions": [
                    {"session_id": k, "running": v.proc.returncode is None} for k, v in _STORE.items()
                ]
            },
        }

    return {"status": "failed", "error": f"unknown terminal op {op}"}
