"""See the screen and drive mouse + keyboard.

Coordinates: the model sees a downscaled screenshot (long edge <= MAX_EDGE). Clicks arrive in that space and are mapped
back to the OS's logical points, which is what pyautogui expects (on a Retina Mac the screenshot has 2x the pixels of
the logical size, so skipping this mapping clicks in the wrong place).
"""
from __future__ import annotations

import base64
import io
import sys
import time

MAX_EDGE = 1280
MAX_PIXELS = 1_150_000


class Scaler:
    def __init__(self, logical: tuple[int, int], physical: tuple[int, int]):
        self.lw, self.lh = logical
        pw, ph = physical
        k = min(1.0, MAX_EDGE / max(pw, ph), (MAX_PIXELS / (pw * ph)) ** 0.5)
        self.w, self.h = max(1, int(pw * k)), max(1, int(ph * k))

    def to_logical(self, x: float, y: float) -> tuple[int, int]:
        x = min(max(x, 0), self.w - 1)
        y = min(max(y, 0), self.h - 1)
        return int(x * self.lw / self.w), int(y * self.lh / self.h)


def _pg():
    import pyautogui
    pyautogui.FAILSAFE = True   # slam the mouse into a screen corner to abort any action, locally, instantly
    pyautogui.PAUSE = 0.05
    return pyautogui


def _use_quartz() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        from .. import input_darwin

        return input_darwin.accessibility_trusted()
    except Exception:
        return False


def _click_at(x: int, y: int, kind: str = "click") -> None:
    if _use_quartz():
        from .. import input_darwin

        if kind == "right_click":
            input_darwin.click(x, y, button="right")
        elif kind == "double_click":
            input_darwin.click(x, y, clicks=2)
        elif kind == "middle_click":
            input_darwin.click(x, y, button="middle")
        else:
            input_darwin.click(x, y)
        if not input_darwin.verify_click(x, y):
            raise RuntimeError(
                "mouse click did not move the cursor — grant Accessibility to this app "
                "(Terminal, iTerm, or Admeasy.app) in System Settings"
            )
        return
    pg = _pg()
    pg.moveTo(x, y, duration=0.15)
    {"click": pg.click, "right_click": pg.rightClick, "double_click": pg.doubleClick,
     "middle_click": pg.middleClick}[kind]()


def _move_to(x: int, y: int) -> None:
    if _use_quartz():
        from .. import input_darwin

        input_darwin.move_to(x, y)
        return
    _pg().moveTo(x, y, duration=0.15)


def screenshot(monitor: int = 1, quality: int = 60, *, som: bool = True) -> dict:
    import mss
    from PIL import Image

    from .. import a11y_tree, som as som_mod

    pg = _pg()
    with mss.mss() as sct:
        mon = sct.monitors[min(monitor, len(sct.monitors) - 1)]
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    sc = Scaler(tuple(pg.size()), img.size)
    img = img.resize((sc.w, sc.h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    shot = {"screenshot_b64": base64.b64encode(buf.getvalue()).decode(), "size": [sc.w, sc.h]}
    if som:
        ax = a11y_tree.snapshot()
        if ax:
            shot = som_mod.annotate_screenshot(shot, ax)
    return shot


_KEYS = {"return": "enter", "ctrl": "ctrl", "control": "ctrl", "super": "command" if sys.platform == "darwin" else "win",
         "cmd": "command", "meta": "command", "win": "win", "alt": "alt", "option": "alt", "esc": "esc",
         "escape": "esc", "page_down": "pagedown", "page_up": "pageup", "backspace": "backspace", "delete": "delete",
         "space": "space", "tab": "tab", "up": "up", "down": "down", "left": "left", "right": "right"}


def parse_key(spec: str) -> list[str]:
    """'ctrl+shift+t' / 'Return' / 'super+space' -> pyautogui key names."""
    return [_KEYS.get(k.strip().lower(), k.strip().lower()) for k in str(spec).split("+") if k.strip()]


def settle_seconds(action: dict) -> float:
    """Wait after an action so the UI can update before the next screenshot."""
    t = str(action.get("type") or "")
    if t in ("click", "click_mark", "right_click", "double_click", "middle_click", "ax_press"):
        return 1.25
    if t == "key":
        return 1.0
    if t == "scroll":
        return 0.65
    if t == "type" or t == "ax_type":
        return 0.5
    if t == "drag":
        return 0.9
    if t == "wait":
        return 0.15
    return 0.85


def act(action: dict, scaler: Scaler | None = None) -> None:
    from ..config import Settings
    from .. import cursor_overlay

    pg = _pg()
    t = action.get("type")
    sc = scaler or Scaler(tuple(pg.size()), tuple(pg.size()))
    show_cursor = Settings.load().show_agent_cursor

    def pt(prefix=""):
        return sc.to_logical(float(action[prefix + "x"]), float(action[prefix + "y"]))

    def _show(x: int, y: int, flash: bool = False) -> None:
        if not show_cursor:
            return
        cursor_overlay.set_enabled(True)
        cursor_overlay.move_to(x, y)
        if flash:
            cursor_overlay.click_flash()

    if t in ("click_mark",) or (t == "click" and (action.get("element_id") or action.get("mark")) is not None):
        from .. import som as som_mod

        center = som_mod.center_for_mark(int(action.get("element_id") or action.get("mark") or 0))
        if not center:
            raise ValueError(f"unknown element_id {action.get('element_id')}")
        x, y = center
        _show(x, y, flash=True)
        _click_at(x, y, "click")
        return
    if t in ("click", "right_click", "double_click", "middle_click"):
        x, y = pt()
        _show(x, y, flash=True)
        _click_at(x, y, t)
    elif t == "move":
        x, y = pt()
        _show(x, y)
        _move_to(x, y)
    elif t == "drag":
        fx, fy = sc.to_logical(float(action["from_x"]), float(action["from_y"]))
        tx, ty = pt()
        _show(fx, fy)
        _move_to(fx, fy)
        _show(tx, ty)
        if _use_quartz():
            from .. import input_darwin

            input_darwin.move_to(tx, ty)
            input_darwin.click(tx, ty)
        else:
            pg.moveTo(fx, fy, duration=0.1)
            pg.dragTo(tx, ty, duration=0.4, button="left")
    elif t == "type":
        eid = action.get("element_id") or action.get("mark")
        if eid is not None:
            from .. import som as som_mod

            center = som_mod.center_for_mark(int(eid))
            if center:
                _show(center[0], center[1], flash=True)
                _click_at(center[0], center[1], "click")
                time.sleep(0.12)
        paste_text(str(action.get("text") or ""))
    elif t == "key":
        keys = parse_key(action.get("key") or "enter")
        pg.hotkey(*keys) if len(keys) > 1 else pg.press(keys[0])
    elif t == "scroll":
        sx, sy = pt() if action.get("x") is not None else (None, None)
        dy = int(action.get("dy") or 0)
        dx = int(action.get("dx") or 0)
        if _use_quartz() and sx is not None:
            from .. import input_darwin

            # Model scroll_amount is usually small; scale to wheel lines
            input_darwin.scroll_at(sx, sy, max(-30, min(30, dy // 3)), max(-30, min(30, dx // 3)))
        else:
            if sx is not None:
                _move_to(sx, sy)
            if dy:
                pg.scroll(-dy // 10 if sys.platform != "darwin" else -dy // 20)
            if dx:
                pg.hscroll(dx // 10)
    elif t in ("ax_press", "ax_type"):
        from .. import som as som_mod

        eid = int(action.get("element_id") or action.get("mark") or 0)
        center = som_mod.center_for_mark(eid)
        if center:
            _show(center[0], center[1], flash=True)
        if sys.platform == "darwin" and (som_mod.LAST_ELEMENTS.get(eid) or {}).get("name"):
            import subprocess

            if t == "ax_type":
                paste_text(str(action.get("text") or ""))
            elif center:
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'tell application "System Events" to click at {{{center[0]}, {center[1]}}}',
                    ],
                    check=False,
                    timeout=5,
                )
        elif center:
            if t == "ax_type":
                _click_at(center[0], center[1], "click")
                paste_text(str(action.get("text") or ""))
            else:
                _click_at(center[0], center[1], "click")
    elif t == "wait":
        time.sleep(min(float(action.get("seconds") or 1), 10))


def paste_text(text: str) -> None:
    """Type via the clipboard: reliable for any language and emoji. The previous clipboard is restored."""
    import pyperclip

    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    time.sleep(0.05)
    if _use_quartz():
        from .. import input_darwin

        input_darwin.key_combo(["command"], "v")
    else:
        pg = _pg()
        pg.hotkey("command" if sys.platform == "darwin" else "ctrl", "v")
    time.sleep(0.15)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass
