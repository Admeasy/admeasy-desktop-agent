"""Extra local API used by the chat window. Existing invite/login routes stay in server.py."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .. import VERSION, auth, permissions
from ..backend_client import BackendClient, BackendError
from ..config import platform_name
from ..folders import grant, pick_folder, revoke
from ..links import create_job, register_url_handler
from ..reminders import add_reminder, cancel_reminder, deliver_due, list_reminders
from ..safety import folder_roots, read_audit, toggles
from ..system_hooks import handler_argv, set_autostart

ASSETS = Path(__file__).resolve().parents[2] / "packaging"
GITHUB_SH = "https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.sh"
GITHUB_PS1 = "https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.ps1"


def _offline_install(state) -> dict:
    backend = state.settings.backend
    rel = VERSION
    return {
        "download_macos": f"https://github.com/Admeasy/admeasy-desktop-agent/releases/download/v{rel}/Admeasy-{rel}-macos-unsigned.dmg",
        "download_windows": f"https://github.com/Admeasy/admeasy-desktop-agent/releases/download/v{rel}/Admeasy-{rel}-windows-unsigned.exe",
        "releases_page": "https://github.com/Admeasy/admeasy-desktop-agent/releases/latest",
        "macos": f"curl -fsSL {GITHUB_SH} | bash -s -- --backend {backend}",
        "windows": f"$env:ADMEASY_BACKEND='{backend}'; irm {GITHUB_PS1} | iex",
        "code": "",
        "note": "Sign in first if you want a pairing code. The command still installs the helper.",
        "platform": platform_name(),
    }


def refresh_install_snippet(state) -> None:
    """Background refresh; never call from the HTTP handler thread."""
    backend = state.settings.backend
    code = ""
    try:
        client = BackendClient(state.settings)
        r = client.request("POST", "/devices/pair-codes", json_body={"client": "desktop"}, timeout=4)
        if isinstance(r, dict):
            code = str(r.get("code") or "")
    except Exception:
        code = ""
    pair = f" --pair {code}" if code else ""
    rel = VERSION
    result = {
        "download_macos": f"https://github.com/Admeasy/admeasy-desktop-agent/releases/download/v{rel}/Admeasy-{rel}-macos-unsigned.dmg",
        "download_windows": f"https://github.com/Admeasy/admeasy-desktop-agent/releases/download/v{rel}/Admeasy-{rel}-windows-unsigned.exe",
        "releases_page": "https://github.com/Admeasy/admeasy-desktop-agent/releases/latest",
        "macos": f"curl -fsSL {GITHUB_SH} | bash -s --{pair} --backend {backend}",
        "windows": (
            f"$env:ADMEASY_BACKEND='{backend}'; "
            + (f"$env:ADMEASY_PAIR='{code}'; " if code else "")
            + f"irm {GITHUB_PS1} | iex"
        ),
        "code": code,
        "note": (
            "Send them the download link above (normal users never run curl)."
            + (" Pair code is single-use for another computer on your account." if code
               else " Sign in on this Mac first to mint a pair code.")
        ),
        "platform": platform_name(),
    }
    state._install_cache = (time.time(), result)


def install_snippet(state) -> dict:
    cached = getattr(state, "_install_cache", None)
    if cached and (time.time() - cached[0]) < 60:
        return cached[1]
    if cached:
        threading.Thread(target=refresh_install_snippet, args=(state,), daemon=True).start()
        return cached[1]
    offline = _offline_install(state)
    state._install_cache = (time.time(), offline)
    threading.Thread(target=refresh_install_snippet, args=(state,), daemon=True).start()
    return offline


def install_snippet_legacy_blocking(state) -> dict:
    """Tests only: previous blocking behaviour."""
    cached = getattr(state, "_install_cache", None)
    if cached and (time.time() - cached[0]) < 60:
        return cached[1]
    refresh_install_snippet(state)
    cached = getattr(state, "_install_cache", None)
    return cached[1] if cached else _offline_install(state)


def asset_bytes(name: str) -> bytes | None:
    path = ASSETS / name
    if path.is_file():
        return path.read_bytes()
    return None


def live_payload(state) -> dict:
    notices = []
    try:
        notices = deliver_due(notify=toggles(state.settings).get("notify", True))
    except Exception:
        notices = []
    events = state.chat.drain() if getattr(state, "chat", None) else []
    feed = []
    approvals = []
    if state.agent is not None:
        feed = list(state.agent.feed)[-40:]
        approvals = list(state.agent.local_approvals.values())
    return {"events": events, "feed": feed, "approvals": approvals, "notices": notices}


def handle_post(state, name: str, body: dict) -> dict | None:
    """Return a JSON body when this route is ours, else None."""
    if name == "chat":
        if not state.snapshot().get("perms_ready"):
            raise ValueError("grant screen, accessibility, keyboard and clipboard before sending")
        if not getattr(state, "chat", None):
            raise ValueError("chat is not running")
        text = str(body.get("text") or "")
        state.chat.send(text)
        return {"ok": True}
    if name == "onboarding":
        if body.get("skip_clipboard"):
            state.settings.clipboard_skipped = True
        if body.get("complete"):
            snap = permissions.detail()
            if not permissions.ready(snap, state.settings.clipboard_skipped):
                raise ValueError("those permissions are not granted yet")
            state.settings.onboarding_complete = True
        state.settings.save()
        return {"ok": True}
    if name == "capabilities":
        caps = toggles(state.settings)
        for key in ("shell", "files", "screen", "input", "browser", "notify"):
            if key in body:
                caps[key] = bool(body[key])
        state.settings.capability_toggles = caps
        state.settings.save()
        return {"ok": True, "capabilities": caps}
    if name == "folders":
        path = grant(state.settings, str(body.get("path") or ""))
        return {"ok": True, "path": path, "folders": folder_roots(state.settings)}
    if name == "folders/revoke":
        revoke(state.settings, str(body.get("path") or ""))
        return {"ok": True, "folders": folder_roots(state.settings)}
    if name == "folders/pick":
        picked = pick_folder()
        if not picked:
            raise ValueError("no folder selected")
        path = grant(state.settings, picked)
        return {"ok": True, "path": path}
    if name == "commands":
        state.settings.command_allowlist = [str(x) for x in (body.get("allowlist") or [])][:100]
        state.settings.command_blocklist = [str(x) for x in (body.get("blocklist") or [])][:100]
        state.settings.save()
        return {"ok": True}
    if name == "reminders":
        from .. import auth
        token = auth.load_secret("access_token")
        row = add_reminder(state.settings, str(body.get("text") or ""), str(body.get("at") or ""), token)
        return {"ok": True, "reminder": row}
    if name == "reminders/cancel":
        from .. import auth
        cancel_reminder(str(body.get("id") or ""), state.settings, auth.load_secret("access_token"))
        return {"ok": True}
    if name == "terminal-jobs":
        job = create_job(
            str(body.get("command") or ""),
            folder_roots(state.settings),
            state.settings.approval_mode,
            allowlist=state.settings.command_allowlist,
            blocklist=state.settings.command_blocklist,
        )
        return {"ok": True, **job}
    if name == "approvals":
        if state.agent is None:
            raise ValueError("agent is not running")
        fut = state.agent.approvals.get(str(body.get("id") or ""))
        if fut is None or fut.done():
            raise ValueError("that approval is gone")
        fut.set_result(bool(body.get("allow")))
        return {"ok": True}
    if name == "register-handler":
        where = register_url_handler(handler_argv())
        set_autostart(True)
        return {"ok": True, "handler": where}
    return None


def public_state(state, base: dict) -> dict:
    detail = permissions.detail()
    ready = permissions.ready(detail, bool(getattr(state.settings, "clipboard_skipped", False)))
    token = auth.load_secret("access_token")
    base.update({
        "permission_detail": detail,
        "perms_ready": ready,
        "onboarding_complete": bool(state.settings.onboarding_complete),
        "capabilities": toggles(state.settings),
        "folders": folder_roots(state.settings),
        "reminders": (
            state._reminders_cache
            if getattr(state, "_reminders_cache", None) is not None
            else list_reminders(state.settings, token)
        ),
        "audit": read_audit(40),
        "install": install_snippet(state) if base.get("signed_in") else {
            "macos": f"curl -fsSL {GITHUB_SH} | bash -s -- --backend {state.settings.backend}",
            "windows": f"$env:ADMEASY_BACKEND='{state.settings.backend}'; irm {GITHUB_PS1} | iex",
            "note": "Sign in first if you want a pairing code. The command still installs the helper.",
            "code": "",
        },
    })
    return base
