"""WhatsApp: native desktop app first; web only when fallback_web=true."""
from __future__ import annotations

import asyncio

from ..config import Settings
from . import screen
from .app_launch import launch
from .browser import Browser

_BROWSER = Browser()


async def _desktop_shot(settle: float = 2.5) -> dict:
    await asyncio.sleep(settle)
    shot = await asyncio.get_event_loop().run_in_executor(None, screen.screenshot)
    return {
        "status": "done",
        "result": {
            **shot,
            "surface": "whatsapp_desktop",
            "interaction": "use cua to scroll/read/click; messages kind for chat.db export on macOS",
        },
    }


async def run(p: dict) -> dict:
    op = p.get("op") or "open"
    use_web = bool(p.get("fallback_web"))

    if op == "open_desktop" or (not use_web and op in ("open", "status", "read", "navigate")):
        opened = launch("WhatsApp")
        if opened.get("status") != "done":
            if use_web:
                use_web = True
            else:
                return opened
        if not use_web:
            return await _desktop_shot(float(p.get("settle_s") or 2.5))

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
                out["error"] = "WhatsApp Web needs QR scan — use native WhatsApp (default) or scan QR"
        return out
    if op == "status":
        return await _BROWSER.run({"op": "read", "url": "https://web.whatsapp.com/"})
    return {"status": "failed", "error": f"unknown whatsapp op {op}"}
