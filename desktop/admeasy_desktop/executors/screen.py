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
        pg.moveTo(x, y, duration=0.15)
        pg.click()
        return
    if t in ("click", "right_click", "double_click", "middle_click"):
        x, y = pt()
        _show(x, y, flash=True)
        pg.moveTo(x, y, duration=0.15)
        {"click": pg.click, "right_click": pg.rightClick, "double_click": pg.doubleClick,
         "middle_click": pg.middleClick}[t]()
    elif t == "move":
        x, y = pt()
        _show(x, y)
        pg.moveTo(x, y, duration=0.15)
    elif t == "drag":
        fx, fy = sc.to_logical(float(action["from_x"]), float(action["from_y"]))
        tx, ty = pt()
        _show(fx, fy)
        pg.moveTo(fx, fy, duration=0.1)
        _show(tx, ty)
        pg.dragTo(tx, ty, duration=0.4, button="left")
    elif t == "type":
        paste_text(str(action.get("text") or ""))
    elif t == "key":
        keys = parse_key(action.get("key") or "enter")
        pg.hotkey(*keys) if len(keys) > 1 else pg.press(keys[0])
    elif t == "scroll":
        if action.get("x") is not None:
            pg.moveTo(*pt())
        if action.get("dy"):
            pg.scroll(-int(action["dy"]) // 10 if sys.platform != "darwin" else -int(action["dy"]) // 20)
        if action.get("dx"):
            pg.hscroll(int(action["dx"]) // 10)
    elif t == "wait":
        time.sleep(min(float(action.get("seconds") or 1), 10))


def paste_text(text: str) -> None:
    """Type via the clipboard: reliable for any language and emoji. The previous clipboard is restored."""
    import pyperclip
    pg = _pg()
    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    time.sleep(0.05)
    pg.hotkey("command" if sys.platform == "darwin" else "ctrl", "v")
    time.sleep(0.15)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass
