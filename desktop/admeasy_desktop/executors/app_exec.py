"""Install / uninstall apps (brew, winget, choco) and open installed apps."""
from __future__ import annotations

import shutil
import subprocess
import sys

from . import terminal_exec


async def run(p: dict, on_output=None) -> dict:
    op = p.get("op") or "open"
    name = str(p.get("name") or p.get("package") or "").strip()
    if not name and op not in ("list",):
        return {"status": "failed", "error": "name or package is required"}

    if op == "open":
        from . import system

        return system.open_target({"target": name})

    if op == "list":
        if sys.platform == "darwin" and shutil.which("brew"):
            return await terminal_exec.run({"op": "run", "command": "brew list --formula | head -n 80"}, on_output)
        if sys.platform == "win32" and shutil.which("winget"):
            return await terminal_exec.run(
                {"op": "run", "command": "winget list --accept-source-agreements | Select-Object -First 40"},
                on_output,
            )
        return {"status": "done", "result": {"packages": [], "note": "no package manager detected"}}

    if op == "install":
        if sys.platform == "darwin":
            if not shutil.which("brew"):
                return {"status": "failed", "error": "Homebrew not found"}
            cmd = f"brew install {name}"
        elif sys.platform == "win32":
            if shutil.which("winget"):
                cmd = f"winget install --id {name} -e --accept-package-agreements --accept-source-agreements"
            elif shutil.which("choco"):
                cmd = f"choco install {name} -y"
            else:
                return {"status": "failed", "error": "install winget or chocolatey"}
        else:
            cmd = f"sudo apt-get install -y {name}" if shutil.which("apt-get") else f"echo install {name}"
        return await terminal_exec.run({"op": "run", "command": cmd, "timeout_s": 900}, on_output)

    if op == "uninstall":
        if sys.platform == "darwin":
            cmd = f"brew uninstall {name}"
        elif sys.platform == "win32":
            cmd = f"winget uninstall --id {name} -e" if shutil.which("winget") else f"choco uninstall {name} -y"
        else:
            cmd = f"sudo apt-get remove -y {name}"
        return await terminal_exec.run({"op": "run", "command": cmd, "timeout_s": 600}, on_output)

    if op == "which":
        path = shutil.which(name)
        return {"status": "done", "result": {"name": name, "path": path}}

    return {"status": "failed", "error": f"unknown app op {op}"}
