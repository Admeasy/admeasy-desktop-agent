"""Resolve friendly app names to OS-native launches (Dock / Launchpad / Start menu)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

# Spoken name -> macOS -a name / Windows Start-Process name
APP_ALIASES: dict[str, str] = {
    "whatsapp": "WhatsApp",
    "cursor": "Cursor",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "safari": "Safari",
    "firefox": "Firefox",
    "edge": "Microsoft Edge",
    "mail": "Mail",
    "messages": "Messages",
    "facetime": "FaceTime",
    "slack": "Slack",
    "discord": "Discord",
    "spotify": "Spotify",
    "notes": "Notes",
    "calendar": "Calendar",
    "finder": "Finder",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "cloud": "Cloud",  # user-specific; falls through to open -a
    "claude": "Claude",
}

_URL_RE = re.compile(r"^https?://", re.I)


def looks_like_url(target: str) -> bool:
    t = target.strip()
    return bool(_URL_RE.match(t) or t.startswith("www."))


def resolve_app_name(target: str) -> str:
    key = target.strip().lower()
    if key in APP_ALIASES:
        return APP_ALIASES[key]
    return target.strip()


def launch(target: str) -> dict:
    """Open URL in default browser, or native app by name."""
    t = str(target or "").strip()
    if not t:
        return {"status": "failed", "error": "target is required"}

    if looks_like_url(t):
        if not t.startswith("http"):
            t = "https://" + t
        open_url_default(t)
        return {"status": "done", "result": {"opened": t, "surface": "default_browser", "hint": "use cua for clicks/typing"}}

    app = resolve_app_name(t)
    path = os.path.expanduser(app)
    if os.path.exists(path):
        return _open_path(path)

    if sys.platform == "darwin":
        r = subprocess.run(["open", "-a", app], capture_output=True, text=True, timeout=25)
        if r.returncode == 0:
            return {"status": "done", "result": {"opened": app, "surface": "native_app", "hint": "use cua screenshot to see UI"}}
        # Try bundle id style path
        for guess in (f"/Applications/{app}.app", os.path.expanduser(f"~/Applications/{app}.app")):
            if os.path.isdir(guess):
                subprocess.run(["open", guess], check=False, timeout=15)
                return {"status": "done", "result": {"opened": guess, "surface": "native_app"}}
        return {"status": "failed", "error": (r.stderr or f"could not open app {app}").strip()[:300]}

    if sys.platform == "win32":
        if shutil.which(app):
            os.startfile(app)  # type: ignore[attr-defined]
            return {"status": "done", "result": {"opened": app, "surface": "native_app"}}
        ps = f"Start-Process '{app.replace(chr(39), chr(39)+chr(39))}'"
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=25)
        if r.returncode == 0:
            return {"status": "done", "result": {"opened": app, "surface": "native_app"}}
        return {"status": "failed", "error": (r.stderr or r.stdout or "could not start app")[:300]}

    xdg = shutil.which("xdg-open") or "xdg-open"
    r = subprocess.run([xdg, app], capture_output=True, text=True, timeout=20)
    if r.returncode:
        return {"status": "failed", "error": (r.stderr or "could not open").strip()[:300]}
    return {"status": "done", "result": {"opened": app, "surface": "native_app"}}


def open_url_default(url: str, reuse_tab: bool = True) -> dict:
    from ..default_browser import open_url_in_default_browser

    return open_url_in_default_browser(url, reuse_tab=reuse_tab) or {"reused": False}


def _open_path(path: str) -> dict:
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False, timeout=15)
    elif sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run([shutil.which("xdg-open") or "xdg-open", path], check=False)
    return {"status": "done", "result": {"opened": path, "surface": "path"}}
