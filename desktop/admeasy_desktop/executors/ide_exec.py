"""Cursor / VS Code control via CLI (`cursor`, `code`)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _ide_bin(ide: str) -> str | None:
    ide = ide.lower()
    if ide in ("cursor", "vscode", "code"):
        for cmd in ("cursor", "code"):
            if ide in ("cursor",) and cmd != "cursor":
                continue
            if ide in ("vscode", "code") and cmd != "code":
                continue
            p = shutil.which(cmd)
            if p:
                return p
    return shutil.which(ide) or shutil.which("code") or shutil.which("cursor")


def run(p: dict) -> dict:
    op = p.get("op") or "open"
    ide = str(p.get("ide") or "cursor")
    bin_path = _ide_bin(ide)
    if not bin_path:
        return {"status": "failed", "error": f"{ide} CLI not on PATH (install Cursor or VS Code)"}

    if op == "open":
        target = str(p.get("path") or p.get("folder") or ".")
        target = os.path.expanduser(target)
        argv = [bin_path, target]
        if p.get("line"):
            argv = [bin_path, "-g", f"{target}:{int(p['line'])}" + (f":{int(p['column'])}" if p.get("column") else "")]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        if r.returncode:
            return {"status": "failed", "error": (r.stderr or r.stdout or "open failed")[:400]}
        return {"status": "done", "result": {"opened": target, "ide": ide}}

    if op == "command":
        cmd = str(p.get("command") or "")
        argv = [bin_path, "--command", cmd]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return {
            "status": "done" if r.returncode == 0 else "failed",
            "result": {"output": (r.stdout or r.stderr or "")[-4000:]},
            **({"error": r.stderr[:300]} if r.returncode else {}),
        }

    if op == "diff":
        a, b = p.get("left"), p.get("right")
        if not a or not b:
            return {"status": "failed", "error": "left and right paths required"}
        r = subprocess.run([bin_path, "--diff", os.path.expanduser(a), os.path.expanduser(b)], capture_output=True, text=True, timeout=30)
        return {"status": "done" if r.returncode == 0 else "failed", "result": {"diff": True}}

    if op == "extensions":
        sub = p.get("subop") or "list"
        if sub == "list":
            r = subprocess.run([bin_path, "--list-extensions"], capture_output=True, text=True, timeout=30)
            exts = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
            return {"status": "done", "result": {"extensions": exts[:200]}}
        if sub == "install":
            ext = str(p.get("id") or "")
            r = subprocess.run([bin_path, "--install-extension", ext], capture_output=True, text=True, timeout=120)
            if r.returncode:
                return {"status": "failed", "error": (r.stderr or "install failed")[:300]}
            return {"status": "done", "result": {"installed": ext}}

    return {"status": "failed", "error": f"unknown ide op {op}"}
