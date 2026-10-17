"""OS permission checks. macOS is the strict one: the app needs Screen Recording (to see) and Accessibility (to click/type).
Both are granted per app bundle in System Settings > Privacy & Security, so the .app MUST have a stable bundle id and a
stable code signature, or macOS asks again after every update."""
from __future__ import annotations

import os
import subprocess
import sys

SETTINGS_URLS = {
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "files": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    "full_disk": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
}


def check(prompt: bool = False) -> dict:
    """{screen, accessibility}: True/False on macOS, True on Windows/Linux (no per-app grant exists there)."""
    if sys.platform != "darwin":
        return {"screen": True, "accessibility": True, "platform_note": "no per-app permission on this OS"}
    out = {"screen": False, "accessibility": False}
    try:
        import Quartz
        out["screen"] = bool(Quartz.CGPreflightScreenCaptureAccess())
        if prompt and not out["screen"]:
            Quartz.CGRequestScreenCaptureAccess()  # shows the system dialog once
    except Exception:
        pass
    try:
        import ApplicationServices as AS
        if prompt:
            out["accessibility"] = bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
        else:
            out["accessibility"] = bool(AS.AXIsProcessTrusted())
    except Exception:
        pass
    return out


def open_settings(which: str) -> None:
    if sys.platform == "darwin" and which in SETTINGS_URLS:
        subprocess.Popen(["open", SETTINGS_URLS[which]])
    elif sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "ms-settings:privacy"])


def can_read_full_disk() -> bool:
    """True when Messages / call history / notification DBs are readable (macOS Full Disk Access)."""
    if sys.platform != "darwin":
        return True
    probes = (
        os.path.expanduser("~/Library/Messages/chat.db"),
        os.path.expanduser("~/Library/Group Containers/group.com.apple.usernoted/db2/db"),
    )
    for path in probes:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as fh:
                fh.read(1)
            return True
        except OSError:
            return False
    return False


def missing(perms: dict) -> list[str]:
    return [k for k in ("screen", "accessibility", "full_disk") if perms.get(k) is False]


def missing_for_kind(kind: str, params: dict | None, perms: dict) -> list[str]:
    p = params or {}
    need: list[str] = []
    if kind in ("screenshot", "cua"):
        need.extend(missing({k: perms.get(k) for k in ("screen", "accessibility")}))
    if kind == "messages" or (kind == "comms" and p.get("op") in ("notifications", "calls", None)):
        if not perms.get("full_disk"):
            need.append("full_disk")
    return need


def wire_snapshot() -> dict:
    """Permission fields sent on hello / permissions."""
    p = check()
    return {
        "screen": bool(p.get("screen")),
        "accessibility": bool(p.get("accessibility")),
        "full_disk": can_read_full_disk(),
        "automation": bool(p.get("accessibility")),
    }


def missing_all(perms: dict) -> list[str]:
    out = missing({k: perms.get(k) for k in ("screen", "accessibility")})
    if not perms.get("full_disk"):
        out.append("full_disk")
    return out
