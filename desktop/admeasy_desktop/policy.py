"""What the agent may do, and what needs a yes from the user.

Three layers, in order:
  1. HARD BLOCK  never runs, in any mode (disk wipe, shutdown, credential stores, the agent's own secrets).
  2. APPROVAL    risky actions pause and ask the user (answered from the phone or the desktop window). No answer in 300 s = no.
  3. FREE        read-only and routine UI actions run without asking.
Modes: autopilot (default) never asks for opening, clicking, typing or navigating; it asks only before a destructive
shell/file step, an install, or a final send/call. ask_risky, ask_always and trusted as before.
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


DELETE_KEYS = re.compile(r"(?i)^(cmd|command|super|win|ctrl|control)\+(delete|backspace)$")


def _autopilot(kind: str, p: dict, roots) -> Verdict:
    """UI work runs on its own; only irreversible steps pause. Captcha / needs_login stops are separate (executors)."""
    if kind in ("shell", "terminal", "cli"):
        cmd = str(p.get("command") or p.get("prompt") or p.get("data") or "")
        if HARD_BLOCK.search(cmd):
            return Verdict(False, reason="blocked: this command can destroy data or leak credentials", risk="blocked")
        if RISKY_SHELL.search(cmd):
            return Verdict(True, ask=True, reason=f"run: {cmd[:160]}", risk="high")
        return Verdict(True, risk="medium")
    if kind == "files":
        op, path = p.get("op", "list"), str(p.get("path") or "")
        if path and not in_roots(path, roots):
            return Verdict(False, reason="that folder is not shared with Admeasy", risk="blocked")
        return Verdict(True, ask=op == "delete", reason=f"{op} {path}", risk="high" if op == "delete" else "low")
    if kind == "cua":
        a = p.get("action") or {}
        if a.get("type") == "key" and DELETE_KEYS.match(str(a.get("key") or "")):
            return Verdict(True, ask=True, reason=f"press {a.get('key')}", risk="high")
        return Verdict(True, reason=str(a.get("type")), risk="low")
    if kind == "app" and p.get("op") in ("install", "uninstall"):
        return Verdict(True, ask=True, reason=f"{p.get('op')} {p.get('name')}", risk="high")
    if kind == "messages" and p.get("op") == "send":
        return Verdict(True, ask=True, reason=f"SMS/iMessage to {p.get('to')}", risk="high")
    if kind == "comms" and p.get("op") == "continuity_call":
        return Verdict(True, ask=True, reason=f"call {p.get('number')}", risk="high")
    if kind == "whatsapp" and p.get("op") == "send":
        return Verdict(True, ask=True, reason="WhatsApp send", risk="high")
    return Verdict(True, reason=kind, risk="low")


def _command_text(kind: str, params: dict) -> str:
    if kind not in ("shell", "terminal", "cli"):
        return ""
    return str(params.get("command") or params.get("prompt") or params.get("data") or "")


def _listed(command: str, patterns) -> bool:
    import fnmatch
    text = (command or "").strip()
    if not text:
        return False
    for raw in patterns or []:
        pattern = str(raw or "").strip()
        if not pattern:
            continue
        if text == pattern:
            return True
        if any(ch in pattern for ch in "*?["):
            if fnmatch.fnmatchcase(text, pattern):
                return True
    return False


def _judge_core(kind: str, params: dict, mode: str, roots, allowlist=None, blocklist=None) -> Verdict:
    p = params or {}
    cmd = _command_text(kind, p)
    if cmd and _listed(cmd, blocklist):
        return Verdict(False, reason="blocked by your blocklist", risk="blocked")
    if cmd and HARD_BLOCK.search(cmd):
        return Verdict(False, reason="blocked: this command can destroy data or leak credentials", risk="blocked")
    if cmd and _listed(cmd, allowlist):
        return Verdict(True, ask=False, reason="on your allowlist", risk="low")
    if mode == "autopilot":
        return _autopilot(kind, p, roots)
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
        op = p.get("op")
        destructive = op in ("click", "type", "press", "fill", "select", "download")
        sendish = op == "type" and SEND_WORDS.search(str(p.get("text") or ""))
        return Verdict(
            True,
            ask=mode != "trusted" and (sendish or (mode == "ask_always" and destructive)),
            reason=f"browser {op}",
            risk="high" if sendish else "low",
        )
    if kind in ("terminal", "cli"):
        cmd = str(p.get("command") or p.get("prompt") or p.get("data") or "")
        if HARD_BLOCK.search(cmd):
            return Verdict(False, reason="blocked: destructive shell pattern", risk="blocked")
        if mode == "trusted":
            return Verdict(True, risk="medium")
        return Verdict(True, ask=True, reason=f"{kind} {p.get('op', 'run')}", risk="high" if RISKY_SHELL.search(cmd) else "medium")
    if kind == "app":
        op = p.get("op")
        if op in ("install", "uninstall"):
            return Verdict(True, ask=mode != "trusted", reason=f"{op} {p.get('name')}", risk="high")
        return Verdict(True, ask=mode == "ask_always", reason=f"app {op}", risk="low")
    if kind == "ide":
        if p.get("op") in ("command",) and mode != "trusted":
            return Verdict(True, ask=True, reason="ide command", risk="medium")
        return Verdict(True, ask=mode == "ask_always", reason=f"ide {p.get('op')}", risk="low")
    if kind == "whatsapp":
        if p.get("op") in ("type", "click", "press") or SEND_WORDS.search(str(p.get("text") or "")):
            return Verdict(True, ask=mode != "trusted", reason="WhatsApp send/action", risk="high")
        return Verdict(True, ask=mode == "ask_always", reason=f"whatsapp {p.get('op')}", risk="low")
    if kind == "messages":
        if p.get("op") == "send":
            return Verdict(True, ask=True, reason=f"SMS/iMessage to {p.get('to')}", risk="high")
        return Verdict(True, ask=mode == "ask_always", reason=f"messages {p.get('op')}", risk="low")
    if kind == "comms":
        if p.get("op") == "continuity_call":
            return Verdict(True, ask=True, reason=f"call {p.get('number')}", risk="high")
        return Verdict(True, ask=mode == "ask_always", reason=f"comms {p.get('op')}", risk="low")
    if kind == "mail":
        if p.get("op") == "compose":
            return Verdict(True, ask=mode != "trusted", reason="compose email", risk="high")
        return Verdict(True, ask=mode == "ask_always", reason=f"mail {p.get('op')}", risk="low")
    return Verdict(True, risk="low")  # screenshot, login_check, verify, ...


def judge(kind: str, params: dict, mode: str, roots, allowlist=None, blocklist=None, autonomous: bool = False) -> Verdict:
    """kind = the job kind the backend sent. params = its arguments.

    A blocklist entry always denies, including in trusted mode and even when the same
    command is also on the allowlist. An allowlist entry skips the approval prompt.
    Autonomous or scheduled jobs cannot run anything that would have asked.
    """
    verdict = _judge_core(kind, params, mode, roots, allowlist, blocklist)
    if autonomous and verdict.ask:
        return Verdict(False, reason="scheduled jobs cannot run commands that need approval", risk="blocked")
    return verdict
