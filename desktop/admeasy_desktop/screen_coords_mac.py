"""Map pyautogui / CGEvent (top-left, y down) points to AppKit window placement (per-screen Cocoa space)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _ScreenPy:
    py_left: float
    py_top: float
    width: float
    height: float
    cocoa_left: float
    cocoa_bottom: float
    cocoa_height: float


def _screens_py() -> list[_ScreenPy]:
    from AppKit import NSScreen

    main = NSScreen.mainScreen()
    main_top = main.frame().origin.y + main.frame().size.height
    out: list[_ScreenPy] = []
    for scr in NSScreen.screens():
        f = scr.frame()
        cocoa_left = float(f.origin.x)
        cocoa_bottom = float(f.origin.y)
        w = float(f.size.width)
        h = float(f.size.height)
        cocoa_top = cocoa_bottom + h
        py_top = main_top - cocoa_top
        py_left = cocoa_left
        out.append(_ScreenPy(py_left, py_top, w, h, cocoa_left, cocoa_bottom, h))
    return out


def screen_for_point(x: float, y: float) -> _ScreenPy | None:
    for s in _screens_py():
        if s.py_left <= x < s.py_left + s.width and s.py_top <= y < s.py_top + s.height:
            return s
    # Fallback: nearest screen by horizontal overlap
    screens = _screens_py()
    return screens[0] if screens else None


def window_top_left_for_center(center_x: float, center_y: float, window_size: float) -> tuple[float, float]:
    """
    NSWindow setFrameTopLeftPoint: top-left corner in global screen coordinates (Cocoa, y up).
    center_x/center_y: pyautogui-style global logical point (y down from primary top).
    """
    s = screen_for_point(center_x, center_y)
    if s is None:
        from AppKit import NSScreen

        f = NSScreen.mainScreen().frame()
        cocoa_cx = center_x
        cocoa_cy = f.origin.y + f.size.height - center_y
        half = window_size / 2.0
        return cocoa_cx - half, cocoa_cy + half
    cocoa_cx = s.cocoa_left + (center_x - s.py_left)
    cocoa_cy = s.cocoa_bottom + s.cocoa_height - (center_y - s.py_top)
    half = window_size / 2.0
    return cocoa_cx - half, cocoa_cy + half
