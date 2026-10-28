"""PTY-backed terminal sessions with streamed output (long-running commands).

On POSIX the session is a real pseudo-terminal, so the working directory survives
between writes and interactive programs (nano, top) receive a tty. Windows uses
ConPTY when pywinpty is installed, otherwise a PowerShell pipe.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

OnOutput = Callable[[str], Awaitable[None]]


@dataclass
class _Session:
    proc: asyncio.subprocess.Process | None = None
    buf: list[str] = field(default_factory=list)
    master: int | None = None
    winpty: object | None = None


_STORE: dict[str, _Session] = {}


def _shell_argv() -> list[str]:
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-NoLogo"]
    sh = next(
        (c for c in (os.environ.get("SHELL"), "/bin/zsh", "/bin/bash", "/bin/sh") if c and os.path.exists(c)),
        "/bin/sh",
    )
    return [sh, "-l"]


def _reader_thread(session_id: str, master: int, on_output: OnOutput | None, loop: asyncio.AbstractEventLoop | None) -> None:
    while True:
        try:
            data = os.read(master, 4096)
        except OSError:
            break
        if not data:
            break
        text = data.decode(errors="replace")
        sess = _STORE.get(session_id)
        if sess:
            sess.buf.append(text)
            if len(sess.buf) > 400:
                sess.buf = sess.buf[-200:]
        if on_output and text.strip() and loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(on_output(text[-300:]), loop)


async def _spawn_session(session_id: str, cwd: str, on_output: OnOutput | None) -> _Session:
    if sys.platform != "win32":
        import pty
        master, slave = pty.openpty()
        proc = await asyncio.create_subprocess_exec(
            *_shell_argv(),
            cwd=cwd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        sess = _Session(proc=proc, master=master)
        _STORE[session_id] = sess
        loop = asyncio.get_running_loop()
        threading.Thread(target=_reader_thread, args=(session_id, master, on_output, loop), daemon=True).start()
        return sess
    try:
        from winpty import PtyProcess  # type: ignore
        proc = PtyProcess.spawn(_shell_argv(), cwd=cwd)
        sess = _Session(winpty=proc)

        def _win_read():
            while proc.isalive():
                try:
                    text = proc.read(4096)
                except EOFError:
                    break
                except Exception:
                    break
                if text:
                    sess.buf.append(text)
        threading.Thread(target=_win_read, daemon=True).start()
        return sess
    except Exception:
        proc = await asyncio.create_subprocess_exec(
            *_shell_argv(),
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        asyncio.create_task(_drain(session_id, proc, on_output))
        return _Session(proc=proc)


async def _write_session(sess: _Session, data: str) -> None:
    payload = data.encode()
    if sess.master is not None:
        os.write(sess.master, payload)
        return
    if sess.winpty is not None:
        sess.winpty.write(data)
        return
    if sess.proc and sess.proc.stdin:
        sess.proc.stdin.write(payload)
        await sess.proc.stdin.drain()
        return
    raise RuntimeError("session has no input")


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
        sess = await _spawn_session(sid, cwd, on_output)
        _STORE[sid] = sess
        return {"status": "done", "result": {"session_id": sid, "pty": sess.master is not None or sess.winpty is not None}}

    if op == "write":
        sid = str(p.get("session_id") or "")
        sess = _STORE.get(sid)
        if not sess:
            return {"status": "failed", "error": "unknown session_id"}
        data = str(p.get("data") or "")
        if not p.get("raw") and not data.endswith("\n"):
            data += "\n"
        try:
            await _write_session(sess, data)
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}
        await asyncio.sleep(float(p.get("settle_s") or 0.3))
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
        if sess.proc and sess.proc.returncode is None:
            sess.proc.terminate()
            try:
                await asyncio.wait_for(sess.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                sess.proc.kill()
        if sess.master is not None:
            try:
                os.close(sess.master)
            except OSError:
                pass
        return {"status": "done", "result": {"session_id": sid, "exit_code": None if not sess.proc else sess.proc.returncode}}

    if op == "list":
        return {
            "status": "done",
            "result": {
                "sessions": [
                    {"session_id": k, "running": (v.proc.returncode is None) if v.proc else True} for k, v in _STORE.items()
                ]
            },
        }

    return {"status": "failed", "error": f"unknown terminal op {op}"}
