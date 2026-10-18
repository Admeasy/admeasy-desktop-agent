"""Low-level mouse/keyboard on macOS via Quartz CGEvent (needs Accessibility for the running executable).

macOS grants Accessibility / Screen Recording per *executable* (TCC): a grant for Terminal does not cover
Admeasy.app, and a grant for an old build does not cover a re-signed one. When the process is not trusted,
CGEventPost drops events silently. So every input path here verifies its effect instead of assuming it.
"""
from __future__ import annotations

import logging
import os
import sys
import time

log = logging.getLogger("admeasy-desktop")

# Which Quartz event tap to post to. HID is the lowest level (works for most apps); session tap is
# what some sandboxed apps listen on. Selectable for the self-test: ADMEASY_EVENT_TAP=hid|session
_TAP_ENV = "ADMEASY_EVENT_TAP"


def accessibility_trusted() -> bool:
    try:
        import ApplicationServices as AS

        return bool(AS.AXIsProcessTrusted())
    except Exception as e:  # pyobjc missing or broken: say so instead of silently "untrusted"
        log.warning("AXIsProcessTrusted check failed: %s: %s", type(e).__name__, e)
        return False


def screen_capture_allowed() -> bool | None:
    try:
        import Quartz

        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception as e:
        log.warning("CGPreflightScreenCaptureAccess failed: %s: %s", type(e).__name__, e)
        return None


def process_identity() -> dict:
    """What TCC actually judges: the executable, its bundle, and who launched it."""
    info: dict = {"executable": sys.executable, "pid": os.getpid(), "ppid": os.getppid()}
    try:
        from Foundation import NSBundle

        b = NSBundle.mainBundle()
        info["bundle_id"] = str(b.bundleIdentifier() or "")
        info["bundle_path"] = str(b.bundlePath() or "")
    except Exception as e:
        info["bundle_id"] = f"unknown ({type(e).__name__})"
    try:
        import subprocess

        info["parent"] = subprocess.run(["ps", "-o", "comm=", "-p", str(os.getppid())],
                                        capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        info["parent"] = ""
    info["ax_trusted"] = accessibility_trusted()
    info["screen_capture"] = screen_capture_allowed()
    return info


def log_identity(context: str = "") -> dict:
    info = process_identity()
    log.info("tcc identity %s executable=%s bundle_id=%s bundle=%s parent=%s ax_trusted=%s screen_capture=%s",
             context, info.get("executable"), info.get("bundle_id"), info.get("bundle_path"),
             info.get("parent"), info.get("ax_trusted"), info.get("screen_capture"))
    return info


def _quartz():
    import Quartz

    return Quartz


def _tap(q):
    which = os.environ.get(_TAP_ENV, "hid").strip().lower()
    return q.kCGSessionEventTap if which == "session" else q.kCGHIDEventTap


def pointer_position() -> tuple[int, int]:
    q = _quartz()
    loc = q.CGEventGetLocation(q.CGEventCreate(None))
    return int(loc.x), int(loc.y)


def move_to(x: int, y: int) -> None:
    q = _quartz()
    pt = (float(x), float(y))
    move = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, pt, q.kCGMouseButtonLeft)
    q.CGEventPost(_tap(q), move)


def _button_map(q, which: str):
    return {
        "left": (q.kCGEventLeftMouseDown, q.kCGEventLeftMouseUp, q.kCGMouseButtonLeft),
        "right": (q.kCGEventRightMouseDown, q.kCGEventRightMouseUp, q.kCGMouseButtonRight),
        "middle": (q.kCGEventOtherMouseDown, q.kCGEventOtherMouseUp, q.kCGMouseButtonCenter),
    }[which]


def app_at_point(x: int, y: int) -> dict | None:
    """Owner (pid, name) of the topmost normal window under a global point."""
    try:
        q = _quartz()
        wins = q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements, q.kCGNullWindowID)
        for w in wins or []:
            if int(w.get("kCGWindowLayer", 1)) != 0:
                continue
            b = w.get("kCGWindowBounds") or {}
            bx, by, bw, bh = (float(b.get(k, 0)) for k in ("X", "Y", "Width", "Height"))
            if bx <= x <= bx + bw and by <= y <= by + bh:
                if str(w.get("kCGWindowOwnerName") or "") in ("Admeasy", "Window Server"):
                    continue
                return {"pid": int(w.get("kCGWindowOwnerPID")), "name": str(w.get("kCGWindowOwnerName") or "")}
    except Exception as e:
        log.debug("app_at_point failed: %s", e)
    return None


def frontmost_pid() -> int | None:
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app else None
    except Exception:
        return None


def activate_pid(pid: int, timeout_s: float = 1.0) -> bool:
    """Bring an app to the front and confirm it is frontmost (first click on a background window is
    often swallowed as 'activate window' only)."""
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception as e:
        log.debug("activate failed: %s", e)
        return False
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if frontmost_pid() == pid:
            return True
        time.sleep(0.05)
    return frontmost_pid() == pid


def click(x: int, y: int, button: str = "left", clicks: int = 1, activate: bool = True) -> dict:
    """Post a real click (with click-state, so double-clicks register) and report what happened."""
    q = _quartz()
    pt = (float(x), float(y))
    down, up, btn = _button_map(q, button)
    report: dict = {"tap": os.environ.get(_TAP_ENV, "hid")}
    if activate:
        owner = app_at_point(x, y)
        if owner:
            report["target_app"] = owner["name"]
            if frontmost_pid() != owner["pid"]:
                report["activated"] = activate_pid(owner["pid"])
    move_to(x, y)
    time.sleep(0.04)
    tap = _tap(q)
    n = max(1, clicks)
    for i in range(1, n + 1):
        ev_down = q.CGEventCreateMouseEvent(None, down, pt, btn)
        ev_up = q.CGEventCreateMouseEvent(None, up, pt, btn)
        q.CGEventSetIntegerValueField(ev_down, q.kCGMouseEventClickState, i)
        q.CGEventSetIntegerValueField(ev_up, q.kCGMouseEventClickState, i)
        q.CGEventPost(tap, ev_down)
        time.sleep(0.05)
        q.CGEventPost(tap, ev_up)
        time.sleep(0.06)
    report["pointer_ok"] = verify_click(x, y)
    return report


def scroll_at(x: int, y: int, dy: int, dx: int = 0) -> None:
    q = _quartz()
    move_to(x, y)
    if dy:
        ev = q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitLine, 1, int(dy))
        q.CGEventPost(_tap(q), ev)
    if dx:
        ev = q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitLine, 2, 0, int(dx))
        q.CGEventPost(_tap(q), ev)


_MODS = {"command": "kCGEventFlagMaskCommand", "cmd": "kCGEventFlagMaskCommand", "super": "kCGEventFlagMaskCommand",
         "meta": "kCGEventFlagMaskCommand", "shift": "kCGEventFlagMaskShift", "alt": "kCGEventFlagMaskAlternate",
         "option": "kCGEventFlagMaskAlternate", "ctrl": "kCGEventFlagMaskControl",
         "control": "kCGEventFlagMaskControl", "fn": "kCGEventFlagMaskSecondaryFn"}

# US ANSI virtual key codes (Carbon kVK_*).
_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
    "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25,
    "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38,
    "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
    "enter": 36, "return": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51, "escape": 53, "esc": 53,
    "forwarddelete": 117, "home": 115, "end": 119, "pageup": 116, "page_up": 116, "pagedown": 121,
    "page_down": 121, "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
    "f10": 109, "f11": 103, "f12": 111,
}


def _keycode(name: str) -> int | None:
    return _KEYCODES.get(str(name).lower())


def key_combo(modifiers: list[str], key: str) -> None:
    """modifiers: command, shift, alt, ctrl, fn; key: a name from _KEYCODES or any single character."""
    q = _quartz()
    flags = 0
    for m in modifiers:
        attr = _MODS.get(m.lower())
        if attr:
            flags |= getattr(q, attr)
    code = _keycode(key)
    tap = _tap(q)
    if code is None:
        if len(key) != 1:
            raise ValueError(f"unsupported key: {key}")
        # Any other single character: send its unicode with a neutral key code.
        down = q.CGEventCreateKeyboardEvent(None, 0, True)
        up = q.CGEventCreateKeyboardEvent(None, 0, False)
        q.CGEventKeyboardSetUnicodeString(down, len(key), key)
        q.CGEventKeyboardSetUnicodeString(up, len(key), key)
    else:
        down = q.CGEventCreateKeyboardEvent(None, code, True)
        up = q.CGEventCreateKeyboardEvent(None, code, False)
    if flags:
        q.CGEventSetFlags(down, flags)
        q.CGEventSetFlags(up, flags)
    q.CGEventPost(tap, down)
    time.sleep(0.02)
    q.CGEventPost(tap, up)


def type_unicode(text: str, chunk: int = 20) -> None:
    """Type text directly as unicode key events (no clipboard)."""
    q = _quartz()
    tap = _tap(q)
    for i in range(0, len(text), chunk):
        part = text[i:i + chunk]
        down = q.CGEventCreateKeyboardEvent(None, 0, True)
        up = q.CGEventCreateKeyboardEvent(None, 0, False)
        q.CGEventKeyboardSetUnicodeString(down, len(part), part)
        q.CGEventKeyboardSetUnicodeString(up, len(part), part)
        q.CGEventPost(tap, down)
        q.CGEventPost(tap, up)
        time.sleep(0.02)


def focused_value() -> str | None:
    """AXValue of the focused UI element (to read back typed text). None when unreadable."""
    try:
        import ApplicationServices as AS

        sys_el = AS.AXUIElementCreateSystemWide()
        err, focused = AS.AXUIElementCopyAttributeValue(sys_el, AS.kAXFocusedUIElementAttribute, None)
        if err or focused is None:
            return None
        err, val = AS.AXUIElementCopyAttributeValue(focused, AS.kAXValueAttribute, None)
        if err or val is None:
            return None
        return str(val)
    except Exception:
        return None


def verify_click(x: int, y: int, tolerance: int = 8) -> bool:
    """True only if the cursor really is at the intended point. An exception is a failure, not a pass."""
    try:
        px, py = pointer_position()
        return abs(px - x) <= tolerance and abs(py - y) <= tolerance
    except Exception as e:
        log.warning("verify_click failed: %s: %s", type(e).__name__, e)
        return False
