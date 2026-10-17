"""Sign-in handoff: open login in default browser, notify user, poll session probe."""
from __future__ import annotations

import asyncio
import time

from .executors.app_launch import open_url_default
from .session_probe import probe_domain


def _notify(title: str, body: str) -> None:
    import sys

    if sys.platform == "darwin":
        import subprocess

        script = f'display notification "{body}" with title "{title}"'
        subprocess.Popen(["osascript", "-e", script])
    elif sys.platform == "win32":
        try:
            from win10toast import ToastNotifier

            ToastNotifier().show_toast(title, body, duration=8)
        except Exception:
            pass


async def run(params: dict) -> dict:
    domain = str(params.get("domain") or "").strip()
    url = params.get("url") or (f"https://{domain}" if domain else "")
    label = params.get("label") or domain or "this site"
    if url:
        open_url_default(url if str(url).startswith("http") else f"https://{url}")
    _notify("Admeasy", f"Please sign in to {label}")
    timeout = float(params.get("timeout_s") or 600)
    poll = float(params.get("poll_s") or 5)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if domain:
            probe = probe_domain(domain)
            if probe.get("session_present"):
                return {
                    "status": "ok",
                    "result": {"session_verified": True, "domain": domain, "probe": probe},
                }
        await asyncio.sleep(poll)
    return {
        "status": "needs_login",
        "reason": "session_not_verified_in_time",
        "result": {"session_verified": False, "domain": domain},
    }
