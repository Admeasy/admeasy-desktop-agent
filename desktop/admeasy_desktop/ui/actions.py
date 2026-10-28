"""Extra local API used by the chat window. Existing invite/login routes stay in server.py."""
from __future__ import annotations

import time
from pathlib import Path

from .. import permissions
from ..config import platform_name
from ..folders import grant, pick_folder, revoke
from ..links import create_job, register_url_handler
from ..reminders import add_reminder, cancel_reminder, deliver_due, list_reminders
from ..safety import folder_roots, read_audit, toggles
from ..system_hooks import handler_argv, set_autostart

ASSETS = Path(__file__).resolve().parents[2] / "packaging"
GITHUB_SH = "https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.sh"
GITHUB_PS1 = "https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.ps1"


def install_snippet(state) -> dict:
    cached = getattr(state, "_install_cache", None)
    if cached and (time.time() - cached[0]) < 60:
        return cached[1]
    backend = state.settings.backend
    code = ""
    try:
        import httpx
        from .. import auth
        token = auth.refresh(backend) or auth.load_secret("access_token")
        if token:
            r = httpx.post(
                f"{backend.rstrip('/')}/devices/pair-codes",
                headers={"Authorization": f"Bearer {token}"},
                json={"client": "desktop"},
                timeout=6,
            )
            if r.status_code == 200 and isinstance(r.json(), dict):
                code = str(r.json().get("code") or "")
    except Exception:
        code = ""
    pair = f" --pair {code}" if code else ""
    note = (
        "This code is single-use. The helper trades it for a device token on the same account."
        if code else
        "The backend does not issue pairing codes yet. The command installs the helper and "
        "opens Google sign-in so this computer joins the same account as your phone and WhatsApp."
    )
    result = {
        "macos": f"curl -fsSL {GITHUB_SH} | bash -s --{pair} --backend {backend}",
        "windows": (
            f"$env:ADMEASY_BACKEND='{backend}'; "
            + (f"$env:ADMEASY_PAIR='{code}'; " if code else "")
            + f"irm {GITHUB_PS1} | iex"
        ),
        "code": code,
        "note": note,
        "platform": platform_name(),
    }
    state._install_cache = (time.time(), result)
    return result


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
    base.update({
        "permission_detail": detail,
        "perms_ready": ready,
        "onboarding_complete": bool(state.settings.onboarding_complete),
        "capabilities": toggles(state.settings),
        "folders": folder_roots(state.settings),
        "reminders": list_reminders(),
        "audit": read_audit(40),
        "install": install_snippet(state) if base.get("signed_in") else {
            "macos": f"curl -fsSL {GITHUB_SH} | bash -s -- --backend {state.settings.backend}",
            "windows": f"$env:ADMEASY_BACKEND='{state.settings.backend}'; irm {GITHUB_PS1} | iex",
            "note": "Sign in first if you want a pairing code. The command still installs the helper.",
            "code": "",
        },
    })
    return base
