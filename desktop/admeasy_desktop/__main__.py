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

from admeasy_desktop import VERSION, auth, permissions, system_hooks
from admeasy_desktop.api import (
    DEVICES_DISABLED,
    DEVICES_NOT_DEPLOYED,
    DevicesDisabledError,
    DevicesNotDeployedError,
    devices_api_state,
)
from admeasy_desktop.config import CONFIG_PATH, LOG_DIR, Settings
from admeasy_desktop.runtime import app_executable, frozen


def cmd_run(background: bool) -> None:
    from admeasy_desktop.agent import Agent
    from admeasy_desktop.log_buffer import configure_logging
    from admeasy_desktop.ui.server import UiState, serve
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
        from admeasy_desktop.tray import start_tray
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


def cmd_click_test() -> int:
    """Corners + centre: real click, pointer check, overlay coordinate mapping."""
    from admeasy_desktop import cursor_overlay
    from admeasy_desktop import screen_coords_mac
    from admeasy_desktop.executors import screen

    ok = True

    def line(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"[{'ok' if good else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")

    if sys.platform == "darwin":
        from admeasy_desktop import delivery_check, input_darwin

        ident = input_darwin.process_identity()
        app = delivery_check.responsible_app(ident)
        line("responsible app (what macOS checks)", True,
             f"{app} executable={ident.get('executable')} parent={ident.get('parent')}")
        line("AXIsProcessTrusted", bool(ident.get("ax_trusted")), f"for {app}")
        line("screen recording", ident.get("screen_capture") is not False, f"for {app}")
        for tip in delivery_check.tcc_advice(ident):
            print("  FIX: " + tip)
        if not ident.get("ax_trusted"):
            print("CLICK TEST FAILED: macOS will silently drop every click and keystroke from this process.")
            return 1
        good, detail = delivery_check.run_delivery_test()
        line("click + type delivered to another app (TextEdit read-back)", good, detail)
        if not good:
            print(f"CLICK TEST FAILED: {detail}. Grant Accessibility to {app}, fully quit and reopen it, then retry.")
            return 1
    pg = screen._pg()
    w, h = pg.size()
    margin = max(40, min(w, h) // 20)
    points = [
        ("top-left", margin, margin),
        ("top-right", w - margin, margin),
        ("bottom-left", margin, h - margin),
        ("bottom-right", w - margin, h - margin),
        ("center", w // 2, h // 2),
    ]
    cursor_overlay.set_enabled(True)
    for label, x, y in points:
        try:
            info = screen._click_at(x, y, "click")
            line(f"click {label}", True, str(info))
        except Exception as e:
            line(f"click {label}", False, str(e))
            ok = False
            continue
        cursor_overlay.move_to(x, y)
        cursor_overlay.click_flash()
        if sys.platform == "darwin":
            from admeasy_desktop import input_darwin

            px, py = input_darwin.pointer_position()
            near = abs(px - x) <= 15 and abs(py - y) <= 15
            line(f"pointer {label}", near, f"at {px},{py} expected ~{x},{y}")
            ok &= near
            tl = screen_coords_mac.window_top_left_for_center(x, y, 28)
            line(
                f"overlay map {label}",
                abs(tl[0] - (x - 14)) < 1 and abs(tl[1] - (y - 14)) < 1,
                f"top-left {tl}",
            )
        else:
            pos = pg.position()
            near = abs(pos[0] - x) <= 15 and abs(pos[1] - y) <= 15
            line(f"pointer {label}", near, f"at {pos} expected ~{x},{y}")
            ok &= near
    line("overlay available", cursor_overlay.is_available(), "Win32 layered or AppKit")
    return 0 if ok else 1


def cmd_doctor(click_test: bool = False) -> int:
    if click_test:
        return cmd_click_test()
    s = Settings.load()
    ok = True

    def line(name, good, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"[{'ok' if good else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    line("version", True, f"{VERSION} on {platform.platform()}")
    from admeasy_desktop.agent import Agent

    line("contract_version", True, Agent(Settings()).capabilities().get("contract_version", "?"))
    from admeasy_desktop.default_browser import default_browser

    db = default_browser()
    line("default_browser", bool(db.get("name")), f"{db.get('name')} profile_path={db.get('profile_path', '')[:80]}")
    try:
        r = httpx.get(s.backend.rstrip("/") + "/health", timeout=8)
        line("backend reachable", r.status_code == 200, s.backend)
    except Exception as e:
        line("backend reachable", False, f"{s.backend}: {e}")
    st = auth.state()
    line("signed in", st["signed_in"], st.get("email") or "run: python -m admeasy_desktop login")
    from admeasy_desktop.entitlements import EntitlementsClient, EntitlementsError

    gate = EntitlementsClient(s.backend)
    if st["signed_in"]:
        try:
            snap = gate.me(fresh=True)
            usage = snap.usage or {}
            left = "n/a" if usage.get("remaining") is None else str(usage.get("remaining"))
            cap = usage.get("limit")
            usage_txt = left if cap is None else f"{left} of {cap}"
            line("invited", snap.invited, snap.plan_name or snap.plan or "no plan on this account")
            line("plan", bool(snap.plan or snap.plan_name), f"{snap.plan_name} · computer actions left {usage_txt}")
            if snap.referral and snap.referral.get("code"):
                ref = snap.referral
                line(
                    "referral code",
                    True,
                    f"{ref.get('code')} · {ref.get('remaining')} of {ref.get('cap')} invites left",
                )
        except EntitlementsError as exc:
            line("invited", False, str(exc))
    else:
        line("invited", False, "enter an invite code, then sign in")
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
        detail = "" if perms.get(k) else "System Settings > Privacy & Security"
        if k == "accessibility" and sys.platform == "darwin" and not perms.get(k):
            detail = "enable Admeasy.app in Privacy & Security → Accessibility (packaged app)"
        if k == "screen" and sys.platform == "darwin" and not perms.get(k):
            detail = "enable Admeasy.app in Privacy & Security → Screen Recording"
        line(f"permission: {k}", perms.get(k), detail)
    if sys.platform == "darwin":
        try:
            from admeasy_desktop import input_darwin

            line(
                "mouse/keyboard (CGEvent)",
                input_darwin.accessibility_trusted(),
                "same Accessibility grant as above; without it only open URL/app works",
            )
        except Exception as e:
            line("mouse/keyboard (CGEvent)", False, str(e))
    chrome = shutil.which("google-chrome") or shutil.which("chrome") or sys.platform in ("darwin", "win32")
    line("Chrome (for browser control)", chrome, "install Google Chrome if browser ops fail")
    try:
        from admeasy_desktop.executors import screen
        shot = screen.screenshot()
        line("screenshot", True, f"{shot['size'][0]}x{shot['size'][1]}")
    except Exception as e:
        line("screenshot", False, str(e))
    from admeasy_desktop import cursor_overlay

    if s.show_agent_cursor and not cursor_overlay.is_available():
        if sys.platform == "darwin":
            line(
                "agent cursor overlay",
                False,
                "pip install pyobjc-framework-Cocoa (or pip install -e '.[macos]')",
            )
        else:
            line(
                "agent cursor (tkinter)",
                False,
                "install python-tk or set show_agent_cursor=false (clicks still work)",
            )
    elif s.show_agent_cursor:
        kind = "AppKit" if sys.platform == "darwin" else "tkinter"
        line(f"agent cursor ({kind})", True, "pink overlay available")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(prog="admeasy-desktop")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--background", action="store_true")
    doc = sub.add_parser("doctor")
    doc.add_argument("--click-test", action="store_true", help="verify clicks/typing really reach apps (TextEdit read-back) + overlay mapping")
    for n in ("login", "devices", "logout"):
        sub.add_parser(n)
    a = ap.parse_args()
    s = Settings.load()
    if a.cmd in (None, "run"):
        cmd_run(getattr(a, "background", False))
    elif a.cmd == "doctor":
        sys.exit(cmd_doctor(click_test=getattr(a, "click_test", False)))
    elif a.cmd == "login":
        from admeasy_desktop.agent import Agent
        from admeasy_desktop.entitlements import EntitlementsClient, EntitlementsError, InviteError

        client = EntitlementsClient(s.backend)
        if auth.state()["signed_in"]:
            try:
                already = client.me(fresh=True)
            except EntitlementsError:
                already = None
            if already and already.invited:
                agent = Agent(s)
                agent._snap = already
                try:
                    auth.enrol(s, agent.capabilities(), platform.platform())
                except (DevicesDisabledError, DevicesNotDeployedError) as e:
                    print(str(e), file=sys.stderr)
                    sys.exit(1)
                permissions.check(prompt=True)
                print("signed in as", auth.load_secret("email"), f"({already.plan_name})")
                return
        code = os.environ.get("ADMEASY_INVITE", "").strip()
        if not code and sys.stdin.isatty():
            code = input("Invite code (required unless this Google account is already invited): ").strip()
        if not code:
            print("An invite code is required. Set ADMEASY_INVITE or run login in a terminal.", file=sys.stderr)
            sys.exit(1)
        try:
            code = client.validate_invite(code).normalized_code
        except InviteError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        except EntitlementsError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        t = auth.login_via_browser(s.backend, invite=code)
        for k in ("access_token", "refresh_token", "email"):
            auth.save_secret(k, t[k])
        try:
            snap = client.me(fresh=True)
        except EntitlementsError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        if not snap.invited:
            print("This account is not invited. Run login again with a valid code.", file=sys.stderr)
            sys.exit(1)
        agent = Agent(s)
        agent._snap = snap
        try:
            auth.enrol(s, agent.capabilities(), platform.platform())
        except (DevicesDisabledError, DevicesNotDeployedError) as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        permissions.check(prompt=True)
        print("signed in as", t["email"], f"({snap.plan_name})")
    elif a.cmd == "devices":
        from admeasy_desktop.ui.server import UiState
        for d in UiState(s).devices():
            print(("online " if d["online"] else "offline"), d["name"], d["platform"])
    elif a.cmd == "logout":
        from admeasy_desktop.ui.server import UiState
        UiState(s).logout()


if __name__ == "__main__":
    main()
