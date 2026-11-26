"""Attach Playwright to the user's running Chromium via CDP (remote debugging port)."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_PORTS = (9222, 9333, 9229)
_CDP_RE = re.compile(r"DevTools listening on (ws://[^\s]+)")


def _read_json_url(url: str, timeout: float = 2.0) -> Any:
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as res:
        return json.loads(res.read().decode())


def detect_debug_port() -> int | None:
    """Return an open remote-debugging port if the user already launched Chromium with one."""
    for port in _DEFAULT_PORTS:
        try:
            _read_json_url(f"http://127.0.0.1:{port}/json/version", timeout=1.5)
            return port
        except Exception:
            continue
    env = os.environ.get("ADMEASY_CDP_PORT") or os.environ.get("CHROME_REMOTE_DEBUGGING_PORT")
    if env:
        try:
            port = int(env)
            _read_json_url(f"http://127.0.0.1:{port}/json/version", timeout=1.5)
            return port
        except Exception:
            pass
    return None


def cdp_ws_endpoint(port: int) -> str | None:
    try:
        ver = _read_json_url(f"http://127.0.0.1:{port}/json/version")
        return ver.get("webSocketDebuggerUrl")
    except Exception:
        return None


async def connect_playwright(playwright, port: int | None = None):
    """Return (browser, context, mode) where mode is cdp or None."""
    port = port or detect_debug_port()
    if not port:
        return None, None, None
    ws = cdp_ws_endpoint(port)
    if not ws:
        return None, None, None
    try:
        browser = await playwright.chromium.connect_over_cdp(ws)
        if browser.contexts:
            return browser, browser.contexts[0], "cdp"
        ctx = await browser.new_context()
        return browser, ctx, "cdp"
    except Exception as exc:
        log.warning("cdp attach failed port=%s: %s", port, exc)
        return None, None, None


def relaunch_hint(executable: str | None = None) -> dict:
    """User-consent relaunch args (never auto-launch without UI approval)."""
    exe = executable or "Google Chrome"
    return {
        "mode": "relaunch_with_debug_port",
        "executable": exe,
        "args": ["--remote-debugging-port=9222"],
        "message": "Close Chrome and reopen with remote debugging, or approve one-click relaunch in Admeasy.",
    }


def parse_cdp_from_process_list(ps_output: str) -> int | None:
    for line in ps_output.splitlines():
        m = re.search(r"--remote-debugging-port=(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def probe_process_list() -> int | None:
    try:
        if os.name == "posix":
            r = subprocess.run(["ps", "ax"], capture_output=True, text=True, timeout=3)
            return parse_cdp_from_process_list(r.stdout or "")
    except Exception:
        pass
    return None