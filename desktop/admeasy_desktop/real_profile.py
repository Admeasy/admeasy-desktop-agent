"""Which browser binary + user-data dir Playwright should use so automation runs with the user's real logins.

Data lives in chromium_browsers.json; Settings.playwright_executable / playwright_user_data_dir override it."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_DATA = Path(__file__).with_name("chromium_browsers.json")


def _catalog() -> dict:
    try:
        return json.loads(_DATA.read_text())
    except Exception:
        return {}


def hint_for(browser_name: str) -> str:
    low = (browser_name or "").lower()
    cat = _catalog()
    return next((k for k, v in cat.items() if not k.startswith("_") and k in low
                 and ((v or {}).get(sys.platform) or (v or {}).get("darwin") or {}).get("user_data_dir")), "")


def resolve(hint: str, settings=None, platform: str | None = None, exists=os.path.exists) -> dict | None:
    """{executable, user_data_dir, source} for the default browser, or None (use the isolated profile)."""
    exe = str(getattr(settings, "playwright_executable", "") or "")
    udd = str(getattr(settings, "playwright_user_data_dir", "") or "")
    if exe and udd:
        return {"executable": os.path.expanduser(exe), "user_data_dir": os.path.expanduser(udd), "source": "settings"}
    entry = (_catalog().get(hint or "") or {}).get(platform or sys.platform) or {}
    exe = os.path.expanduser(exe or entry.get("executable", ""))
    udd = os.path.expanduser(udd or entry.get("user_data_dir", ""))
    if exe and udd and exists(exe) and exists(udd):
        return {"executable": exe, "user_data_dir": udd, "source": hint}
    return None
