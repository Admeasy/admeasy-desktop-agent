"""Detect login walls, captchas, checkpoints from AX tree + optional backend skill_hints (no site lists)."""
from __future__ import annotations

import re
from typing import Any

# Generic UI phrases only — not tied to any hostname or selector.
_CAPTCHA_RE = re.compile(
    r"\b(captcha|recaptcha|hcaptcha|verify you are human|security check|i.?m not a robot|"
    r"unusual traffic|checkpoint|challenge)\b",
    re.I,
)
_LOGIN_RE = re.compile(
    r"\b(sign in|log in|login|password|two.?factor|2fa|authenticator|enter code)\b",
    re.I,
)


def _text_blob(ax_tree: list[dict], skill_hints: list[str] | None) -> str:
    parts = [str(h) for h in (skill_hints or []) if h]
    for node in ax_tree or []:
        parts.append(str(node.get("name") or ""))
        parts.append(str(node.get("role") or ""))
    return " ".join(parts)


def analyze(
    ax_tree: list[dict] | None = None,
    *,
    skill_hints: list[str] | None = None,
    session_present: bool | None = None,
) -> dict | None:
    """
    Return typed failure dict {status, reason} or None if no signal.
    Never auto-bypass captcha — always needs_human with status captcha when matched.
    """
    blob = _text_blob(ax_tree or [], skill_hints)
    if _CAPTCHA_RE.search(blob):
        return {"status": "captcha", "reason": "captcha_or_checkpoint_detected_in_ui"}
    if session_present is False and _LOGIN_RE.search(blob):
        return {"status": "needs_login", "reason": "login_ui_without_session"}
    if _LOGIN_RE.search(blob) and any(
        (n.get("role") or "").lower() in ("textfield", "securetextfield") for n in (ax_tree or [])
    ):
        if session_present is not False:
            return {"status": "needs_login", "reason": "credential_fields_visible"}
    return None
