"""Map logical click points to NSWindow setFrameTopLeftPoint (screen coords, y from top)."""
from __future__ import annotations


def window_top_left_for_center(center_x: float, center_y: float, window_size: float) -> tuple[float, float]:
    """
    pyautogui / CGEvent and NSWindow.setFrameTopLeftPoint both use a top-left-origin
    global coordinate system on modern macOS (y increases downward).
    """
    half = window_size / 2.0
    return float(center_x) - half, float(center_y) - half
