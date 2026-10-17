"""admeasy-desktop run | login | doctor | devices | logout   (the .dmg / .exe launches `run`)"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import shutil
import sys
import threading

import httpx

from . import VERSION, auth, permissions, system_hooks
from .api import (
    DEVICES_DISABLED,
    DEVICES_NOT_DEPLOYED,
    DevicesDisabledError,
    DevicesNotDeployedError,
    devices_api_state,
)
from .config import CONFIG_PATH, LOG_DIR, Settings
from .runtime import app_executable, frozen


def _enrol_caps(agent) -> dict:
    return agent.capabilities()


def cmd_run(background: bool) -> None:
    from .agent import Agent
    from .log_buffer import configure_logging
    from .ui.server import UiState, serve
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    configure_logging(str(LOG_DIR / "agent.log"))
    s = Settings.load()
    ui = UiState(s)
    agent = Agent(s)
    ui.agent = agent
    agent.status_cb = ui.set_status
    system_hooks.keep_awake(s.keep_awake and not s.paused)
    if s.start_at_login:
        system_hooks.set_autostart(True, app_executable())
    elif frozen() and not CONFIG_PATH.exists():
        s.start_at_login = True
        s.save()
        system_hooks.set_autostart(True, app_executable())
    threading.Thread(target=lambda: asyncio.run(agent.tunnel()), daemon=True).start()
    _srv, port = serve(ui)
    url = f"http://127.0.0.1:{port}/"

    def set_paused(p: bool) -> None:
        s.paused = p
        s.save()
        system_hooks.keep_awake(s.keep_awake and not s.paused)

    if background and auth.state()["signed_in"]:
        from .tray import start_tray
        start_tray(s.paused, set_paused, lambda: os._exit(0))
        threading.Event().wait()
        return
    try:
        import webview

        webview.create_window("Admeasy", url, width=460, height=720)
        webview.start()  # must own the main thread on macOS
    except Exception as exc:
        logging.getLogger("admeasy-desktop").warning("webview unavailable (%s), using browser", exc)
        import webbrowser

        webbrowser.open(url)
        if sys.platform == "win32" and frozen():
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(
                    0,
                    "Admeasy opened in your browser. Install Microsoft Edge WebView2 from "
                    "https://go.microsoft.com/fwlink/p/?LinkId=2124703 and reinstall for the desktop window.",
                    "Admeasy",
                    0x40,
                )
            except Exception:
                pass
        threading.Event().wait()


def cmd_doctor() -> int:
    s = Settings.load()
    ok = True

    def line(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"[{'ok' if good else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    line("version", True, f"{VERSION} on {platform.platform()}")
    try:
        r = httpx.get(s.backend.rstrip("/") + "/health", timeout=8)
        line("backend reachable", r.status_code == 200, s.backend)
    except Exception as e:
        line("backend reachable", False, f"{s.backend}: {e}")
    st = auth.state()
    line("signed in", st["signed_in"], st.get("email") or "run: python -m admeasy_desktop login")
    line("computer enrolled", bool(st["device_id"]))
    tok = auth.load_secret("access_token")
    if auth.refresh(s.backend):
        tok = auth.load_secret("access_token")
    api_state = devices_api_state(s.backend, tok if st["signed_in"] else None)
    api_detail = {
        "ok": "routes live",
        "auth_required": "routes live (sign in to list devices)",
        "disabled": DEVICES_DISABLED,
        "not_deployed": DEVICES_NOT_DEPLOYED,
        "unreachable": "could not reach GET /devices",
    }[api_state]
    line("devices API", api_state in ("ok", "auth_required"), api_detail)
    perms = permissions.check()
    for k in ("screen", "accessibility"):
        line(f"permission: {k}", perms.get(k), "" if perms.get(k) else "System Settings > Privacy & Security")
    chrome = shutil.which("google-chrome") or shutil.which("chrome") or sys.platform in ("darwin", "win32")
    line("Chrome (for browser control)", chrome, "install Google Chrome if browser ops fail")
    try:
        from .executors import screen
        shot = screen.screenshot()
        line("screenshot", True, f"{shot['size'][0]}x{shot['size'][1]}")
    except Exception as e:
        line("screenshot", False, str(e))
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(prog="admeasy-desktop")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--background", action="store_true")
    for n in ("login", "doctor", "devices", "logout"):
        sub.add_parser(n)
    a = ap.parse_args()
    s = Settings.load()
    if a.cmd in (None, "run"):
        cmd_run(getattr(a, "background", False))
    elif a.cmd == "doctor":
        sys.exit(cmd_doctor())
    elif a.cmd == "login":
        from .agent import Agent
        t = auth.login_via_browser(s.backend)
        for k in ("access_token", "refresh_token", "email"):
            auth.save_secret(k, t[k])
        try:
            auth.enrol(s, _enrol_caps(Agent(s)), platform.platform())
        except (DevicesDisabledError, DevicesNotDeployedError) as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        permissions.check(prompt=True)
        print("signed in as", t["email"])
    elif a.cmd == "devices":
        from .ui.server import UiState
        for d in UiState(s).devices():
            print(("online " if d["online"] else "offline"), d["name"], d["platform"])
    elif a.cmd == "logout":
        from .ui.server import UiState
        UiState(s).logout()


if __name__ == "__main__":
    main()
