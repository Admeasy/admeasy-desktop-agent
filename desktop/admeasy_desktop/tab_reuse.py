"""Reuse a tab that already shows the site instead of opening a new one (macOS, user's real browser).

Lists the default browser's tabs over AppleScript (scripts live in chromium_browsers.json), picks the best tab
for the URL by host (and path when one is given), and focuses it. Anything unsupported returns None so the
caller opens the URL normally."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)
_DATA = Path(__file__).with_name("chromium_browsers.json")


def _host(u: str) -> str:
    h = (urlparse(u if "://" in u else "https://" + u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def parse_tabs(raw: str) -> list[tuple[int, int, str]]:
    out = []
    for line in (raw or "").splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            out.append((int(parts[0]), int(parts[1]), parts[2]))
    return out


def best_tab(tabs: list[tuple[int, int, str]], url: str) -> tuple[int, int] | None:
    """Same host required; a tab whose path starts with the wanted path wins, else the first same-host tab."""
    want = urlparse(url if "://" in url else "https://" + url)
    host, path = _host(url), (want.path or "/").rstrip("/")
    if not host:
        return None
    same = [(w, t, u) for w, t, u in tabs if _host(u) == host]
    if not same:
        return None
    if path:
        for w, t, u in same:
            if (urlparse(u).path or "/").rstrip("/").startswith(path):
                return w, t
    return same[0][0], same[0][1]


def _entry(browser_name: str) -> tuple[dict, dict] | None:
    try:
        cat = json.loads(_DATA.read_text())
    except Exception:
        return None
    low = (browser_name or "").lower()
    for key, val in cat.items():
        if key.startswith("_"):
            continue
        e = (val or {}).get("darwin") or {}
        if e.get("app_name") and (e["app_name"].lower() == low or key in low):
            scripts = (cat.get("_tab_scripts") or {}).get(e.get("tab_dialect", ""))
            if scripts:
                return e, scripts
    return None


def _osa(script: str) -> tuple[int, str]:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()


def focus_existing_tab(browser_name: str, url: str) -> dict | None:
    """{"reused": True, "window": w, "tab": t} when an open tab was focused; None otherwise."""
    found = _entry(browser_name)
    if not found:
        return None
    e, scripts = found
    app = e["app_name"]
    try:
        rc, out = _osa(scripts["list"].replace("{app}", app))
        if rc != 0:
            log.info("tab reuse: cannot list %s tabs (%s)", app, out[:120])
            return None
        hit = best_tab(parse_tabs(out), url)
        if not hit:
            return None
        rc, out = _osa(scripts["activate"].replace("{app}", app).replace("{w}", str(hit[0]))
                       .replace("{t}", str(hit[1])))
        if rc != 0:
            log.info("tab reuse: cannot focus tab in %s (%s)", app, out[:120])
            return None
        log.info("tab reuse: focused existing %s tab host=%s", app, _host(url))
        return {"reused": True, "window": hit[0], "tab": hit[1]}
    except Exception as ex:
        log.info("tab reuse failed: %s", type(ex).__name__)
        return None
