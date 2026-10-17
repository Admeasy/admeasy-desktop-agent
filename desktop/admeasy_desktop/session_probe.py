"""Per-domain session probe: cookie *presence* only (never export cookie values)."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


def _chrome_family_profiles() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    if sys.platform == "darwin":
        roots += [
            home / "Library/Application Support/Google/Chrome",
            home / "Library/Application Support/Microsoft Edge",
            home / "Library/Application Support/BraveSoftware/Brave-Browser",
            home / "Library/Application Support/Chromium",
        ]
    elif sys.platform == "win32":
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            roots += [
                Path(la) / "Google/Chrome/User Data",
                Path(la) / "Microsoft/Edge/User Data",
                Path(la) / "BraveSoftware/Brave-Browser/User Data",
            ]
    else:
        roots.append(home / ".config/google-chrome")
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        default = root / "Default/Cookies"
        if default.is_file():
            out.append(default)
        for prof in root.glob("Profile */Cookies"):
            if prof.is_file():
                out.append(prof)
    return out


def probe_domain(domain: str) -> dict[str, Any]:
    """Return {session_present: bool, browser: str|None, last_seen_at: int|None}."""
    host = (domain or "").strip().lower().lstrip(".")
    if not host or "/" in host:
        return {"session_present": False, "browser": None, "last_seen_at": None}
    needle = host if host.startswith(".") else f".{host}"
    for cookies_path in _chrome_family_profiles():
        browser = "chrome"
        p = cookies_path.as_posix().lower()
        if "edge" in p:
            browser = "edge"
        elif "brave" in p:
            browser = "brave"
        try:
            conn = sqlite3.connect(f"file:{cookies_path}?mode=ro", uri=True)
            cur = conn.execute(
                "SELECT MAX(last_access_utc) FROM cookies WHERE host_key LIKE ? OR host_key = ?",
                (f"%{host}", needle),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                ts = int(row[0] / 1_000_000 - 11644473600) if row[0] > 10_000_000_000 else int(time.time())
                return {"session_present": True, "browser": browser, "last_seen_at": ts}
        except Exception:
            continue
    return {"session_present": False, "browser": None, "last_seen_at": None}
