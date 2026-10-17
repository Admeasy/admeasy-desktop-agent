"""What the agent may do, and what needs a yes from the user.

Three layers, in order:
  1. HARD BLOCK  never runs, in any mode (disk wipe, shutdown, credential stores, the agent's own secrets).
  2. APPROVAL    risky actions pause and ask the user (answered from the phone). No answer in 120 s = no.
  3. FREE        read-only and routine UI actions run without asking.
This is a code-level gate on the machine itself, so it holds even if the cloud model is prompt-injected by a web page.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

HARD_BLOCK = re.compile(
    r"(?ix)(\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(/|~|\$HOME|\*)(\s|$)|\bmkfs\b|\bdd\s+if=.*of=/dev/|:\(\)\s*\{|"
    r"\bdiskutil\s+(erase|partition|apfs\s+delete)|\bformat\s+[a-z]:|\bdiskpart\b|\bcipher\s+/w|"
    r"\b(shutdown|poweroff|halt)\b|\breboot\b|\bcsrutil\b|\bspctl\s+--master-disable|"
    r"security\s+(find|dump)-(generic|internet)-password|\bsecurity\s+export\b|"
    r"\.admeasy/(secrets|config)|login\.keychain|Login\s+Data|Cookies\b.*(cat|cp|scp|curl)|"
    r"\bcurl\b[^|;]*\|\s*(ba|z)?sh\b|\bwget\b[^|;]*\|\s*(ba|z)?sh\b)")
RISKY_SHELL = re.compile(
    r"(?ix)(\bsudo\b|\brm\b|\bmv\b|\bchmod\b|\bchown\b|\bkill(all)?\b|\bpkill\b|\bgit\s+(push|reset|clean|checkout\s+--)|"
    r"\bnpm\s+(publish|install\s+-g)|\bpip\s+install|\bbrew\s+(install|uninstall)|\bdel\b|\brmdir\b|\bRemove-Item\b|"
    r"\bscp\b|\bssh\b|\bcurl\b.*(-X\s*(POST|PUT|DELETE)|-d\s|--data)|>\s*/|\bosascript\b|\bdefaults\s+write\b)")
# Shortcuts that quit, close, delete, lock or send. Typing them through the keyboard needs approval.
RISKY_KEYS = re.compile(r"(?i)^(cmd|command|super|win|ctrl|control|alt|option)\+(q|w|delete|backspace|l|shift\+q)$")
SEND_WORDS = re.compile(r"(?i)\b(send|submit|pay|purchase|buy|confirm|delete|remove|transfer|post|publish)\b")


@dataclass
class Verdict:
    allow: bool
    ask: bool = False
    reason: str = ""
    risk: str = "low"


def _roots(roots):
    return [os.path.realpath(os.path.expanduser(r)) for r in roots]


def in_roots(path: str, roots) -> bool:
    full = os.path.realpath(os.path.expanduser(path))
    return any(full == r or full.startswith(r + os.sep) for r in _roots(roots))


def judge(kind: str, params: dict, mode: str, roots) -> Verdict:
    """kind = the job kind the backend sent. params = its arguments."""
    p = params or {}
    if kind == "shell":
        cmd = str(p.get("command") or "")
        if HARD_BLOCK.search(cmd):
            return Verdict(False, reason="blocked: this command can destroy data or leak credentials", risk="blocked")
        if mode == "trusted":
            return Verdict(True, risk="medium")
        # Shell asks in every mode but "trusted": one wrong command is not undoable. RISKY_SHELL only raises the label.
        return Verdict(True, ask=True, reason=f"run: {cmd[:160]}", risk="high" if RISKY_SHELL.search(cmd) else "medium")
    if kind == "files":
        op, path = p.get("op", "list"), str(p.get("path") or "")
        if path and not in_roots(path, roots):
            return Verdict(False, reason="that folder is not shared with Admeasy", risk="blocked")
        if op in ("delete", "write", "mkdir"):
            return Verdict(True, ask=mode != "trusted", reason=f"{op} {path}", risk="high" if op == "delete" else "medium")
        return Verdict(True, ask=mode == "ask_always", reason=f"{op} {path}", risk="low")
    if kind == "cua":
        a = p.get("action") or {}
        t = a.get("type")
        if t == "key" and RISKY_KEYS.match(str(a.get("key") or "")):
            return Verdict(True, ask=mode != "trusted", reason=f"press {a.get('key')}", risk="high")
        if t == "type" and SEND_WORDS.search(str(a.get("text") or "")) and mode == "ask_always":
            return Verdict(True, ask=True, reason="type text", risk="medium")
        return Verdict(True, ask=mode == "ask_always" and t not in (None, "screenshot", "wait", "move"),
                       reason=f"{t}", risk="low")
    if kind == "open":
        return Verdict(True, ask=mode == "ask_always", reason=f"open {p.get('target')}", risk="low")
    if kind == "clipboard":
        return Verdict(True, ask=mode == "ask_always" and p.get("op") == "set", reason="clipboard", risk="low")
    if kind == "browser":
        return Verdict(True, ask=mode == "ask_always" and p.get("op") in ("click", "type", "press"),
                       reason=f"browser {p.get('op')}", risk="low")
    return Verdict(True, risk="low")  # screenshot, login_check, verify, ...
