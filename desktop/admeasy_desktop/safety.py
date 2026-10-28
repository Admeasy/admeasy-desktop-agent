"""Capability toggles, folder roots, and the on-disk audit log.

The phone tunnel keeps working for computers that already have a config file.
A brand-new config (see Settings.load) refuses computer actions until the window's
permission steps are finished.
"""
from __future__ import annotations

import json
import time

from . import config

# Kinds that drive the machine. status and signin stay available so the phone
# can see why the computer is waiting.
GATED_KINDS = frozenset({
    "shell", "terminal", "cli", "files", "screenshot", "cua", "browser", "clipboard",
    "open", "app", "messages", "whatsapp", "mail", "comms", "ide",
})

_KIND_TOGGLE = {
    "shell": "shell",
    "terminal": "shell",
    "cli": "shell",
    "files": "files",
    "screenshot": "screen",
    "cua": "input",
    "browser": "browser",
}


def toggles(settings) -> dict:
    raw = getattr(settings, "capability_toggles", None) or {}
    base = {"shell": True, "files": True, "screen": True, "input": True, "browser": True, "notify": True}
    base.update({k: bool(v) for k, v in raw.items() if k in base})
    return base


def folder_roots(settings) -> list[str]:
    if getattr(settings, "use_approved_folders_only", False):
        return [str(p) for p in (getattr(settings, "approved_folders", None) or [])]
    return [str(p) for p in (getattr(settings, "shared_folders", None) or [])]


def gate_job(settings, kind: str, params: dict | None) -> dict | None:
    """Return a result dict when this job must not run, else None."""
    if (
        getattr(settings, "gate_until_onboarding", False)
        and not getattr(settings, "onboarding_complete", False)
        and kind in GATED_KINDS
    ):
        return {
            "status": "permission_missing",
            "error": "finish screen, accessibility, keyboard and clipboard setup in the Admeasy window",
            "result": {"reason": "onboarding", "permissions_missing": ["screen", "accessibility"]},
        }
    caps = toggles(settings)
    if kind == "cua" and not caps.get("screen", True):
        return _cap("screen")
    need = _KIND_TOGGLE.get(kind)
    if need and not caps.get(need, True):
        return _cap(need)
    if kind == "files" and not caps.get("files", True):
        return _cap("files")
    return None


def _cap(name: str) -> dict:
    return {
        "status": "blocked",
        "error": f"{name} is turned off for this computer",
        "result": {"reason": "capability_off", "capability": name},
    }


def audit(event: dict) -> None:
    """Append one JSON line. Never raises into a job."""
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        row = {"ts": int(time.time()), **{k: v for k, v in event.items() if k != "token"}}
        with (config.HOME / "audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        return


def read_audit(limit: int = 80) -> list[dict]:
    path = config.HOME / "audit.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
