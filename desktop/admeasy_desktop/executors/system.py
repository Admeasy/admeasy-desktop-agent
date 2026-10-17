"""Shell, open app/file/URL, files in shared folders, clipboard."""
from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
import sys

from ..policy import in_roots

MAX_FILE = 50 * 1024 * 1024


async def shell(p: dict, cancel: asyncio.Event | None = None) -> dict:
    cmd = str(p.get("command") or "")
    cwd = os.path.expanduser(p.get("cwd") or "~")
    if sys.platform == "win32":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        sh = next((c for c in (os.environ.get("SHELL"), "/bin/zsh", "/bin/bash", "/bin/sh") if c and os.path.exists(c)), "/bin/sh")
        argv = [sh, "-lc", cmd]
    proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=min(int(p.get("timeout_s") or 120), 900))
    except asyncio.TimeoutError:
        proc.kill()
        return {"status": "failed", "error": "command timed out"}
    except asyncio.CancelledError:
        proc.kill()
        raise
    text = out.decode(errors="replace")[-12000:]
    body = {"exit_code": proc.returncode, "output": text}
    if proc.returncode != 0:
        return {"status": "failed", "error": f"command exited with code {proc.returncode}", "result": body}
    return {"status": "done", "result": body}


def open_target(p: dict) -> dict:
    t = str(p.get("target") or "").strip()
    if not t:
        return {"status": "failed", "error": "target is required"}
    path = os.path.expanduser(t)
    if sys.platform == "darwin":
        argv = ["open", path] if (os.path.exists(path) or "://" in t) else ["open", "-a", t]
    elif sys.platform == "win32":
        if os.path.exists(path) or "://" in t:
            os.startfile(path)  # type: ignore[attr-defined]
            return {"status": "done", "result": {"opened": t}}
        argv = ["powershell", "-NoProfile", "-Command", f"Start-Process '{t}'"]
    else:
        argv = [shutil.which("xdg-open") or "xdg-open", path]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    if r.returncode:
        return {"status": "failed", "error": (r.stderr or "could not open").strip()[:300]}
    return {"status": "done", "result": {"opened": t}}


def files(p: dict, roots) -> dict:
    op = p.get("op", "list")
    path = os.path.realpath(os.path.expanduser(str(p.get("path") or roots[0])))
    if not in_roots(path, roots):
        return {"status": "failed", "error": "that folder is not shared with Admeasy"}
    if op == "list":
        items = []
        for n in sorted(os.listdir(path))[:500]:
            st = os.stat(os.path.join(path, n))
            items.append({"name": n, "dir": os.path.isdir(os.path.join(path, n)), "size": st.st_size,
                          "mtime": int(st.st_mtime)})
        return {"status": "done", "result": {"path": path, "items": items}}
    if op == "read":
        if os.path.getsize(path) > MAX_FILE:
            return {"status": "failed", "error": "file is larger than 50 MB"}
        with open(path, "rb") as fh:
            data = fh.read()
        return {"status": "done", "result": {"path": path, "size": len(data), "content_b64": base64.b64encode(data).decode()}}
    if op == "write":
        data = base64.b64decode(p["content_b64"]) if "content_b64" in p else str(p.get("text", "")).encode()
        if len(data) > MAX_FILE:
            return {"status": "failed", "error": "file is larger than 50 MB"}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return {"status": "done", "result": {"path": path, "size": len(data)}}
    if op == "mkdir":
        os.makedirs(path, exist_ok=True)
        return {"status": "done", "result": {"path": path}}
    if op == "delete":
        if path in [os.path.realpath(os.path.expanduser(r)) for r in roots]:
            return {"status": "failed", "error": "refusing to delete a shared root folder"}
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        return {"status": "done", "result": {"deleted": path}}
    return {"status": "failed", "error": f"unknown op {op}"}


def clipboard(p: dict) -> dict:
    import pyperclip
    if p.get("op") == "set":
        pyperclip.copy(str(p.get("text") or ""))
        return {"status": "done", "result": {"set": True}}
    return {"status": "done", "result": {"text": pyperclip.paste()[:8000]}}
