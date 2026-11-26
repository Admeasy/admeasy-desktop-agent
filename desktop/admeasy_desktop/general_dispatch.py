"""Dispatch for general tools (terminal, files, screen, browser, notify, clipboard)."""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Awaitable, Callable

OnOutput = Callable[[str], Awaitable[None]]

LEGACY_KINDS = frozenset(
    {
        "whatsapp",
        "messages",
        "mail",
        "comms",
        "app",
        "ide",
        "cli",
        "signin",
        "open",
        "shell",
    }
)


def legacy_handlers_enabled() -> bool:
    return os.environ.get("ADMEASY_LEGACY_HANDLERS", "").strip().lower() in ("1", "true", "yes")


async def dispatch_screen(p: dict, on_output: OnOutput | None, scaler_ref: list) -> dict:
    from .executors import screen

    op = p.get("op") or "screenshot"
    loop = asyncio.get_running_loop()
    if op == "screenshot":
        shot = await loop.run_in_executor(None, screen.screenshot)
        scaler_ref.clear()
        scaler_ref.append(screen.scaler_for(shot))
        return {"status": "ok", "result": shot}
    if op == "act":
        action = p.get("action") or {}
        if sys.platform == "darwin":
            from . import input_darwin

            if not input_darwin.accessibility_trusted():
                return {
                    "status": "permission_missing",
                    "error": "grant Accessibility in System Settings",
                    "result": {"permissions_missing": ["accessibility"]},
                }
        scaler = scaler_ref[0] if scaler_ref else None
        if scaler is None:
            prime = await loop.run_in_executor(None, screen.screenshot)
            scaler = screen.scaler_for(prime)
            scaler_ref.append(scaler)
        try:
            report = await loop.run_in_executor(None, screen.act, action, scaler)
        except ValueError as e:
            return {"status": "error", "error": str(e)}
        except RuntimeError as e:
            return {"status": "permission_missing", "error": str(e)}
        from .ui_settle import wait_for_settle

        await loop.run_in_executor(
            None,
            lambda: wait_for_settle(screen.screenshot, max_wait_s=max(screen.settle_seconds(action), 0.5)),
        )
        shot = await loop.run_in_executor(None, screen.screenshot)
        scaler_ref.clear()
        scaler_ref.append(screen.scaler_for(shot))
        shot["last_action"] = report
        return {"status": "ok", "result": shot}
    return {"status": "error", "error": f"unknown screen op {op}"}


async def dispatch_notify(p: dict) -> dict:
    from .notify import toast

    title = str(p.get("title") or "Admeasy")
    body = str(p.get("body") or p.get("text") or "")
    if not body:
        return {"status": "error", "error": "notify body required"}
    ok = toast(title, body)
    if ok:
        return {"status": "ok", "result": {"shown": True}}
    return {"status": "error", "error": "notification failed", "result": {"shown": False}}