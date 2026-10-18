"""Default browser name and user profile path (existing logged-in profile, not guest)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _chrome_profile() -> str:
    return str(Path.home() / "Library/Application Support/Google/Chrome")


def _edge_profile() -> str:
    return str(Path.home() / "Library/Application Support/Microsoft Edge")


def _firefox_profile() -> str:
    base = Path.home() / "Library/Application Support/Firefox/Profiles"
    if base.is_dir():
        for p in sorted(base.iterdir()):
            if p.is_dir():
                return str(p)
    return str(base)


def _win_profile(name: str) -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    low = name.lower()
    if "chrome" in low:
        return os.path.join(local, "Google", "Chrome", "User Data")
    if "edge" in low:
        return os.path.join(local, "Microsoft", "Edge", "User Data")
    if "firefox" in low:
        return os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")
    if "brave" in low:
        return os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data")
    return ""


def _darwin_http_handler() -> tuple[str, str]:
    """Return (app_name, bundle_hint) for http/https default handler."""
    try:
        out = subprocess.check_output(
            ["defaults", "read", "com.apple.LaunchServices/com.apple.launchservices.secure", "LSHandlers"],
            text=True,
            timeout=3,
        )
        low = out.lower()
        if "comet" in low or "cometbrowser" in low:
            return "Comet", "comet"
        if "google.chrome" in low or "chrome" in low:
            return "Google Chrome", "chrome"
        if "firefox" in low:
            return "Firefox", "firefox"
        if "microsoft edge" in low or "edge" in low:
            return "Microsoft Edge", "edge"
        if "brave" in low:
            return "Brave Browser", "brave"
        if "arc" in low:
            return "Arc", "arc"
    except Exception:
        pass
    return "Safari", "safari"


def default_browser() -> dict:
    if sys.platform == "darwin":
        name, hint = _darwin_http_handler()
        paths = {
            "chrome": _chrome_profile(),
            "firefox": _firefox_profile(),
            "edge": _edge_profile(),
            "brave": str(Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser"),
            "arc": str(Path.home() / "Library/Application Support/Arc/User Data"),
            "comet": str(Path.home() / "Library/Application Support/Comet"),
            "safari": str(Path.home() / "Library/Safari"),
        }
        profile_path = paths.get(hint, "")
        return {"name": name, "profile": "system_default", "profile_path": profile_path}
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
            ) as k:
                prog = winreg.QueryValueEx(k, "ProgId")[0]
            return {"name": prog, "profile": "system_default", "profile_path": _win_profile(prog)}
        except Exception:
            return {"name": "unknown", "profile": "system_default", "profile_path": ""}
    return {"name": "unknown", "profile": "system_default", "profile_path": ""}


def open_url_in_default_browser(url: str, reuse_tab: bool = True) -> dict:
    """Open url in the default browser. On macOS an already-open tab for the same site is focused instead of
    opening a duplicate (pass reuse_tab=False to force a new tab)."""
    info = default_browser()
    name = info.get("name") or ""
    if sys.platform == "darwin" and reuse_tab:
        from .tab_reuse import focus_existing_tab

        hit = focus_existing_tab(name, url)
        if hit:
            return hit
    if sys.platform == "darwin":
        if name and name not in ("unknown", "Safari"):
            r = subprocess.run(["open", "-a", name, url], capture_output=True, timeout=20)
            if r.returncode == 0:
                return {"reused": False}
        subprocess.run(["open", url], check=False, timeout=15)
    elif sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined, name-defined]
    else:
        import webbrowser

        webbrowser.open(url)
    return {"reused": False}
