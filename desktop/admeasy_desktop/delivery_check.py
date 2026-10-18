"""Doctor --click-test on macOS: prove that a click and typed text actually reach another app.

Moving the pointer is not proof: macOS silently drops synthetic clicks/keys from a process that lacks the
Accessibility grant (TCC judges the *responsible* app, e.g. Terminal when run from source, not Admeasy.app).
So we click into a TextEdit document through the production input path, type a marker, and read the document
back over AppleScript. Pure decision helpers are separate so they are unit-tested off-Mac."""
from __future__ import annotations

import re
import subprocess
import time
import uuid


def responsible_app(identity: dict) -> str:
    """The app macOS checks for Accessibility/Screen Recording."""
    bundle = str(identity.get("bundle_path") or "")
    if bundle.endswith(".app") and "Python.app" not in bundle:
        return bundle.rsplit("/", 1)[-1]
    parent = str(identity.get("parent") or "")
    m = re.search(r"([^/]+)\.app/Contents/MacOS/", parent)  # e.g. .../Terminal.app/Contents/MacOS/Terminal
    if m:
        return m.group(1)
    return parent.rsplit("/", 1)[-1] or str(identity.get("executable") or "this program")


def tcc_advice(identity: dict) -> list[str]:
    app = responsible_app(identity)
    out = []
    if not identity.get("ax_trusted"):
        out.append(f"Accessibility is NOT granted to {app}: System Settings > Privacy & Security > Accessibility "
                   f"> add {app} and switch it on, then fully quit and reopen {app}.")
    if identity.get("screen_capture") is False:
        out.append(f"Screen Recording is NOT granted to {app}: Privacy & Security > Screen Recording > add {app}, "
                   f"then fully quit and reopen {app}.")
    return out


def evaluate_delivery(before: str, after: str, marker: str, front_after: str) -> tuple[bool, str]:
    if after.startswith("ERR:"):
        return False, f"could not read TextEdit ({after[4:60]})"
    if marker in after and marker not in before:
        return True, f"typed text arrived in TextEdit (frontmost={front_after})"
    if "TextEdit" not in front_after:
        return False, (f"the click did not reach TextEdit (frontmost stayed {front_after or '?'}): macOS dropped "
                       "the synthetic click")
    return False, "TextEdit came forward but the typed text never arrived: macOS dropped the synthetic keys"


def _osa(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else "ERR:" + r.stderr.strip()


def _frontmost() -> str:
    return _osa('tell application "System Events" to get name of first application process whose frontmost is true')


def run_delivery_test() -> tuple[bool, str]:
    from . import input_darwin

    _osa('tell application "TextEdit" to activate')
    _osa('tell application "TextEdit" to make new document')
    time.sleep(1.0)
    _osa('tell application "TextEdit" to set bounds of window 1 to {200, 200, 900, 700}')
    time.sleep(0.4)
    _osa('tell application "Finder" to activate')  # the click itself must bring TextEdit forward
    time.sleep(0.8)
    before = _osa('tell application "TextEdit" to get text of document 1')
    marker = "admeasy" + uuid.uuid4().hex[:6]
    try:
        input_darwin.click(550, 450)
        time.sleep(0.6)
        front = _frontmost()
        input_darwin.type_unicode(marker)
        time.sleep(0.6)
        after = _osa('tell application "TextEdit" to get text of document 1')
        return evaluate_delivery(before, after, marker, front)
    finally:
        _osa('tell application "TextEdit" to close document 1 saving no')
