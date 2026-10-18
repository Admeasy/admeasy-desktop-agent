"""See the screen and drive mouse + keyboard.

Coordinates: the model sees a downscaled screenshot (long edge <= MAX_EDGE). Clicks arrive in that space and are mapped
back to the OS's logical points, which is what pyautogui expects (on a Retina Mac the screenshot has 2x the pixels of
the logical size, so skipping this mapping clicks in the wrong place).
"""
from __future__ import annotations

import base64
import io
import logging
import sys
import time

log = logging.getLogger("admeasy-desktop")

from ..coordinate_scaling import MAX_EDGE, MAX_PIXELS, Scaler


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


def _region_fingerprint(x: int, y: int, half: int = 120) -> bytes | None:
    """Tiny grayscale thumbnail around a logical point: compared before/after an action to prove an effect."""
    try:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            raw = sct.grab({"left": int(x) - half, "top": int(y) - half, "width": half * 2, "height": half * 2})
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX").convert("L").resize((32, 32))
            return img.tobytes()
    except Exception:
        return None


def _changed(a: bytes | None, b: bytes | None, threshold: float = 2.0) -> bool | None:
    if a is None or b is None:
        return None
    diff = sum(abs(p - q) for p, q in zip(a, b)) / max(1, len(a))
    return diff > threshold


def _click_at(x: int, y: int, kind: str = "click") -> dict:
    if sys.platform == "darwin" and not _use_quartz():
        raise RuntimeError(
            "Accessibility not granted to this executable — enable it for Admeasy.app (or the terminal "
            "that launched the agent) in System Settings → Privacy & Security → Accessibility"
        )
    before = _region_fingerprint(x, y)
    if _use_quartz():
        from .. import input_darwin

        button = {"right_click": "right", "middle_click": "middle"}.get(kind, "left")
        rep = input_darwin.click(x, y, button=button, clicks=2 if kind == "double_click" else 1)
        if not rep.get("pointer_ok"):
            raise RuntimeError(
                "click was not delivered (cursor never reached the target) — macOS is dropping synthetic "
                "input for this executable; re-grant Accessibility for it"
            )
        info = {"input": "quartz", "x": x, "y": y, **rep}
    else:
        pg = _pg()
        pg.moveTo(x, y, duration=0.15)
        {"click": pg.click, "right_click": pg.rightClick, "double_click": pg.doubleClick,
         "middle_click": pg.middleClick}[kind]()
        px, py = pg.position()
        info = {"input": "pyautogui", "x": x, "y": y, "pointer_ok": abs(px - x) <= 8 and abs(py - y) <= 8}
    time.sleep(0.35)
    info["screen_changed"] = _changed(before, _region_fingerprint(x, y))
    info["effect"] = {True: "changed", False: "none", None: "unknown"}[info["screen_changed"]]
    return info


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

    with mss.mss() as sct:
        mon = sct.monitors[min(monitor, len(sct.monitors) - 1)]
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    # Geometry comes from the SAME monitor mss captured (points + origin), not pyautogui.size(), which is
    # the main display only and mismatches on multi-monitor / scaled setups.
    logical = (int(mon["width"]), int(mon["height"]))
    origin = (int(mon.get("left", 0)), int(mon.get("top", 0)))
    sc = Scaler(logical, img.size, monitor_origin=origin)
    img = img.resize((sc.w, sc.h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    shot = {"screenshot_b64": base64.b64encode(buf.getvalue()).decode(), "size": [sc.w, sc.h],
            "geometry": {"logical": list(logical), "physical": list(raw.size),
                         "origin": list(origin), "monitor": monitor}}
    if som:
        ax = a11y_tree.snapshot()
        if ax:
            shot = som_mod.annotate_screenshot(shot, ax, logical_size=logical, origin=origin)
        else:
            shot["elements"] = []
    else:
        shot.setdefault("elements", [])
    return shot


_KEYS = {"return": "enter", "ctrl": "ctrl", "control": "ctrl", "super": "command" if sys.platform == "darwin" else "win",
         "cmd": "command", "meta": "command", "win": "win", "alt": "alt", "option": "alt", "esc": "esc",
         "escape": "esc", "page_down": "pagedown", "page_up": "pageup", "backspace": "backspace", "delete": "delete",
         "space": "space", "tab": "tab", "up": "up", "down": "down", "left": "left", "right": "right"}


def scaler_for(shot: dict) -> Scaler:
    g = shot.get("geometry") or {}
    if g.get("logical") and g.get("physical"):
        return Scaler(tuple(g["logical"]), tuple(g["physical"]), monitor_origin=tuple(g.get("origin") or (0, 0)))
    return Scaler(tuple(_pg().size()), tuple(shot["size"]))


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


def act(action: dict, scaler: Scaler | None = None) -> dict:
    from ..config import Settings
    from .. import cursor_overlay

    pg = _pg()
    t = action.get("type")
    if scaler is None and action.get("x") is not None:
        # Never fall back to an identity mapping: model coords are screenshot pixels, not points.
        scaler = scaler_for(screenshot(som=False))
    sc = scaler or Scaler(tuple(pg.size()), tuple(pg.size()))
    show_cursor = Settings.load().show_agent_cursor
    report: dict = {"type": t, "element_id": action.get("element_id") or action.get("mark")}

    def pt(prefix=""):
        return sc.to_logical(float(action[prefix + "x"]), float(action[prefix + "y"]))

    def _show(x: int, y: int, flash: bool = False) -> None:
        if not show_cursor:
            return
        cursor_overlay.set_enabled(True)
        cursor_overlay.move_to(x, y)
        if flash:
            cursor_overlay.click_flash()

    def _finish(extra: dict) -> dict:
        report.update(extra)
        log.info(
            "cua act type=%s element_id=%s at=%s,%s input=%s pointer_ok=%s effect=%s typed_ok=%s app=%s ax=%s",
            report.get("type"),
            report.get("element_id"),
            report.get("x"),
            report.get("y"),
            report.get("input"),
            report.get("pointer_ok"),
            report.get("effect"),
            report.get("typed_ok"),
            report.get("target_app"),
            report.get("ax_ok"),
        )
        return report

    if t in ("click_mark",) or (t == "click" and (action.get("element_id") or action.get("mark")) is not None):
        from .. import som as som_mod

        eid = int(action.get("element_id") or action.get("mark") or 0)
        center = som_mod.center_for_mark(eid)
        if not center:
            raise ValueError(f"unknown element_id {action.get('element_id')}")
        x, y = center
        _show(x, y, flash=True)
        click_info = _click_at(x, y, "click")
        return _finish({**click_info, "element_id": eid, "ax_ok": False})
    if t in ("click", "right_click", "double_click", "middle_click"):
        x, y = pt()
        _show(x, y, flash=True)
        return _finish({**_click_at(x, y, t), "ax_ok": False})
    elif t == "move":
        x, y = pt()
        _show(x, y)
        _move_to(x, y)
        return _finish({"x": x, "y": y, "input": "quartz" if _use_quartz() else "pyautogui",
                        "pointer_ok": _pointer_at(x, y)})
    elif t == "drag":
        fx, fy = sc.to_logical(float(action["from_x"]), float(action["from_y"]))
        tx, ty = pt()
        _show(fx, fy)
        _move_to(fx, fy)
        _show(tx, ty)
        pg.moveTo(fx, fy, duration=0.1)
        pg.dragTo(tx, ty, duration=0.4, button="left")
        return _finish({"x": tx, "y": ty, "input": "pyautogui", "pointer_ok": _pointer_at(tx, ty)})
    elif t == "type":
        eid = action.get("element_id") or action.get("mark")
        click_info: dict = {"pointer_ok": None, "input": "quartz" if _use_quartz() else "pyautogui"}
        if eid is not None:
            from .. import som as som_mod

            center = som_mod.center_for_mark(int(eid))
            if center:
                _show(center[0], center[1], flash=True)
                click_info = _click_at(center[0], center[1], "click")
                time.sleep(0.12)
            else:
                raise ValueError(f"unknown element_id {eid}")
        text = str(action.get("text") or "")
        typed = type_text_verified(text)
        return _finish({**click_info, "element_id": eid, "typed_len": len(text), "ax_ok": False, **typed})
    elif t in ("key", "hotkey"):
        keys = parse_key(action.get("key") or action.get("hotkey") or "enter")
        if _use_quartz() and len(keys) == 1:
            from .. import input_darwin

            input_darwin.key_combo([], keys[0])
        elif _use_quartz() and len(keys) > 1:
            from .. import input_darwin

            input_darwin.key_combo(keys[:-1], keys[-1])
        else:
            pg.hotkey(*keys) if len(keys) > 1 else pg.press(keys[0])
        return _finish({"input": "quartz" if _use_quartz() else "pyautogui", "key": action.get("key"),
                        "pointer_ok": None})
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
        return _finish(
            {
                "x": sx,
                "y": sy,
                "dy": dy,
                "dx": dx,
                "input": "quartz" if _use_quartz() else "pyautogui",
                "pointer_ok": _pointer_at(sx, sy) if sx is not None else None,
            }
        )
    elif t in ("ax_press", "ax_type"):
        from .. import som as som_mod

        eid = int(action.get("element_id") or action.get("mark") or 0)
        center = som_mod.center_for_mark(eid)
        if center:
            _show(center[0], center[1], flash=True)
        ax_ok = False
        if sys.platform == "darwin" and center:
            import subprocess

            if t == "ax_type":
                click_info = _click_at(center[0], center[1], "click")
                typed = type_text_verified(str(action.get("text") or ""))
                return _finish({**click_info, "element_id": eid, "ax_ok": bool(typed.get("typed_ok")),
                                "typed_len": len(str(action.get("text") or "")), **typed})
            proc = subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'tell application "System Events" to click at {{{center[0]}, {center[1]}}}',
                ],
                check=False,
                timeout=5,
                capture_output=True,
            )
            if proc.returncode == 0:
                return _finish(
                    {
                        "element_id": eid,
                        "ax_ok": True,
                        "x": center[0],
                        "y": center[1],
                        "input": "osascript",
                        "pointer_ok": None,
                    }
                )
            click_info = _click_at(center[0], center[1], "click")
            return _finish({**click_info, "element_id": eid, "ax_ok": False})
        elif center:
            if t == "ax_type":
                click_info = _click_at(center[0], center[1], "click")
                typed = type_text_verified(str(action.get("text") or ""))
                return _finish({**click_info, "element_id": eid, "ax_ok": False, **typed})
            click_info = _click_at(center[0], center[1], "click")
            return _finish({**click_info, "element_id": eid, "ax_ok": False})
        raise ValueError(f"unknown element_id {eid}")
    elif t == "wait":
        time.sleep(min(float(action.get("seconds") or 1), 10))
        return _finish({"input": "sleep", "pointer_ok": None})
    elif t in (None, "screenshot"):
        return _finish({"input": "none", "pointer_ok": None})
    raise ValueError(f"unknown action type {t}")


def _pointer_at(x, y) -> bool:
    try:
        if _use_quartz():
            from .. import input_darwin

            return input_darwin.verify_click(int(x), int(y))
        px, py = _pg().position()
        return abs(px - int(x)) <= 8 and abs(py - int(y)) <= 8
    except Exception:
        return False


def type_text_verified(text: str) -> dict:
    """Paste, then read the focused field back through Accessibility. If the paste didn't land, retype
    as unicode key events. typed_ok: True verified, False verified-missing, None unreadable field."""
    if not text:
        return {"typed_ok": None, "typed_via": "none"}
    readback = None
    if _use_quartz():
        from .. import input_darwin

        readback = input_darwin.focused_value
    before = readback() if readback else None
    paste_text(text)
    after = readback() if readback else None
    probe = text.strip()[:40]
    if after is not None and probe and probe in after:
        return {"typed_ok": True, "typed_via": "paste"}
    if readback and after is not None and after == before:
        from .. import input_darwin

        input_darwin.type_unicode(text)
        time.sleep(0.15)
        again = readback()
        if again is not None:
            return {"typed_ok": bool(probe and probe in again), "typed_via": "unicode"}
    return {"typed_ok": None if after is None else False, "typed_via": "paste"}


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
