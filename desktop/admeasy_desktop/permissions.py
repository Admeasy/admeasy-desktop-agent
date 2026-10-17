"""OS permission checks. macOS is the strict one: the app needs Screen Recording (to see) and Accessibility (to click/type).
Both are granted per app bundle in System Settings > Privacy & Security, so the .app MUST have a stable bundle id and a
stable code signature, or macOS asks again after every update."""
from __future__ import annotations

import subprocess
import sys

SETTINGS_URLS = {
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "files": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
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


def missing(perms: dict) -> list[str]:
    return [k for k in ("screen", "accessibility") if perms.get(k) is False]
