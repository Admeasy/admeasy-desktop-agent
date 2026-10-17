"""WhatsApp Web (Playwright) and desktop app launch."""
from __future__ import annotations

import sys

from .browser import Browser

_BROWSER = Browser()


async def run(p: dict) -> dict:
    op = p.get("op") or "status"
    if op == "open_desktop":
        from . import system

        if sys.platform == "darwin":
            return system.open_target({"target": "WhatsApp"})
        return system.open_target({"target": "whatsapp:"})

    params = {
        "op": "navigate" if op in ("open", "navigate") else op,
        "url": p.get("url") or "https://web.whatsapp.com/",
        **{k: v for k, v in p.items() if k not in ("op",)},
    }
    if op in ("open", "navigate", "read", "click", "type", "press", "scroll", "search"):
        params["op"] = op if op != "open" else "navigate"
        out = await _BROWSER.run(params)
        if out.get("status") == "done" and op == "read":
            text = (out.get("result") or {}).get("text") or ""
            if "QR" in text or "Scan" in text:
                out["status"] = "needs_human"
                out["error"] = "scan WhatsApp QR in the browser window"
        return out
    if op == "status":
        out = await _BROWSER.run({"op": "read", "url": "https://web.whatsapp.com/"})
        return out
    return {"status": "failed", "error": f"unknown whatsapp op {op}"}
