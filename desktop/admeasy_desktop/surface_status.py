"""`status` job kind — surface facts for surfaces_status (no recommendations)."""
from __future__ import annotations

import platform
import sys
import time
from typing import Any

from . import VERSION
from . import permissions
from .default_browser import default_browser
from .session_probe import probe_domain
from .browser_bridge import extension_status


def _active_app() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ],
            text=True,
            timeout=2,
        )
        return out.strip() or None
    except Exception:
        return None


def _idle_seconds() -> float | None:
    if sys.platform != "darwin":
        return None
    try:
        import subprocess

        out = subprocess.check_output(["ioreg", "-c", "IOHIDSystem"], text=True, timeout=2)
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                nano = int(line.split("=")[-1].strip())
                return nano / 1_000_000_000.0
    except Exception:
        return None
    return None


def collect(params: dict) -> dict[str, Any]:
    snap = permissions.wire_snapshot()
    missing = permissions.missing_all(snap)
    domains = params.get("domains") or []
    if isinstance(domains, str):
        domains = [domains]
    sessions = {str(d): probe_domain(str(d)) for d in domains if d}
    ext = extension_status()
    return {
        "online": True,
        "os": platform.platform(),
        "agent_version": VERSION,
        "permissions": snap,
        "permissions_missing": missing,
        "default_browser": default_browser(),
        "sessions": sessions,
        "active_app": _active_app(),
        "idle_seconds": _idle_seconds(),
        "extension_installed": ext.get("installed"),
        "extension_bridge": ext,
        "speed_tier": "medium",
        "timestamp": int(time.time()),
    }
