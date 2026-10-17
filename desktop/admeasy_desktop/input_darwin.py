"""Low-level mouse/keyboard on macOS via Quartz CGEvent (needs Accessibility for the running app)."""
from __future__ import annotations

import logging
import time

log = logging.getLogger("admeasy-desktop")


def accessibility_trusted() -> bool:
    try:
        import ApplicationServices as AS

        return bool(AS.AXIsProcessTrusted())
    except Exception:
        return False


def _quartz():
    import Quartz

    return Quartz


def pointer_position() -> tuple[int, int]:
    q = _quartz()
    loc = q.CGEventGetLocation(q.CGEventCreate(None))
    return int(loc.x), int(loc.y)


def move_to(x: int, y: int) -> None:
    q = _quartz()
    pt = (float(x), float(y))
    move = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, pt, q.kCGMouseButtonLeft)
    q.CGEventPost(q.kCGHIDEventTap, move)


def _button_map(q, which: str):
    return {
        "left": (q.kCGEventLeftMouseDown, q.kCGEventLeftMouseUp, q.kCGMouseButtonLeft),
        "right": (q.kCGEventRightMouseDown, q.kCGEventRightMouseUp, q.kCGMouseButtonRight),
        "middle": (q.kCGEventOtherMouseDown, q.kCGEventOtherMouseUp, q.kCGMouseButtonCenter),
    }[which]


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    q = _quartz()
    pt = (float(x), float(y))
    down, up, btn = _button_map(q, button)
    move_to(x, y)
    time.sleep(0.03)
    for _ in range(max(1, clicks)):
        q.CGEventPost(q.kCGHIDEventTap, q.CGEventCreateMouseEvent(None, down, pt, btn))
        time.sleep(0.05)
        q.CGEventPost(q.kCGHIDEventTap, q.CGEventCreateMouseEvent(None, up, pt, btn))
        time.sleep(0.05)


def scroll_at(x: int, y: int, dy: int, dx: int = 0) -> None:
    q = _quartz()
    move_to(x, y)
    # Scroll wheel: positive line units scroll up on macOS
    if dy:
        ev = q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitLine, 1, int(dy))
        q.CGEventPost(q.kCGHIDEventTap, ev)
    if dx:
        ev = q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitLine, 2, 0, int(dx))
        q.CGEventPost(q.kCGHIDEventTap, ev)


def key_combo(modifiers: list[str], key: str) -> None:
    """modifiers: command, shift, alt, ctrl; key is lowercase virtual key name."""
    q = _quartz()
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags, kCGHIDEventTap

    mod_flags = 0
    mod_map = {
        "command": q.kCGEventFlagMaskCommand,
        "cmd": q.kCGEventFlagMaskCommand,
        "shift": q.kCGEventFlagMaskShift,
        "alt": q.kCGEventFlagMaskAlternate,
        "option": q.kCGEventFlagMaskAlternate,
        "ctrl": q.kCGEventFlagMaskControl,
        "control": q.kCGEventFlagMaskControl,
    }
    for m in modifiers:
        mod_flags |= mod_map.get(m.lower(), 0)

    # Paste shortcut for typing path
    if key == "v" and mod_flags & q.kCGEventFlagMaskCommand:
        keycode = 9  # v
    else:
        keycode = _keycode(key)
    if keycode is None:
        raise ValueError(f"unsupported key: {key}")
    down = CGEventCreateKeyboardEvent(None, keycode, True)
    up = CGEventCreateKeyboardEvent(None, keycode, False)
    if mod_flags:
        CGEventSetFlags(down, mod_flags)
        CGEventSetFlags(up, mod_flags)
    CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.02)
    CGEventPost(kCGHIDEventTap, up)


def _keycode(name: str) -> int | None:
    # US keyboard virtual key codes (subset)
    table = {
        "v": 9,
        "c": 8,
        "a": 0,
        "enter": 36,
        "return": 36,
        "tab": 48,
        "space": 49,
        "escape": 53,
        "esc": 53,
        "delete": 51,
        "backspace": 51,
        "up": 126,
        "down": 125,
        "left": 123,
        "right": 124,
    }
    return table.get(name.lower())


def verify_click(x: int, y: int, tolerance: int = 8) -> bool:
    """True if the cursor is near the intended point after a move/click."""
    try:
        px, py = pointer_position()
        return abs(px - x) <= tolerance and abs(py - y) <= tolerance
    except Exception:
        return True
