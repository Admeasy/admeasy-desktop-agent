"""Default browser name/profile path facts (no URLs)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def default_browser() -> dict:
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["defaults", "read", "com.apple.LaunchServices/com.apple.launchservices.secure", "LSHandlers"],
                text=True,
                timeout=3,
            )
            # crude: last http handler bundle — facts only
            if "chrome" in out.lower():
                return {"name": "Google Chrome", "profile": "system_default"}
            if "firefox" in out.lower():
                return {"name": "Firefox", "profile": "system_default"}
            if "edge" in out.lower():
                return {"name": "Microsoft Edge", "profile": "system_default"}
            if "brave" in out.lower():
                return {"name": "Brave", "profile": "system_default"}
        except Exception:
            pass
        return {"name": "Safari", "profile": "system_default"}
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice") as k:
                prog = winreg.QueryValueEx(k, "ProgId")[0]
            return {"name": prog, "profile": "system_default"}
        except Exception:
            return {"name": "unknown", "profile": "system_default"}
    return {"name": "unknown", "profile": "system_default"}
