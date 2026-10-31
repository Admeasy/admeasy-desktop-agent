"""Full-screen pink edge frame on Windows (layered topmost, click-through)."""
from __future__ import annotations

import logging
import math
import sys
import threading
import time

from .brand import EDGE_ALPHA_PULSE_MAX, EDGE_ALPHA_PULSE_MIN, EDGE_ALPHA_STATIC, EDGE_WIDTH_PX, PULSE_PERIOD_S, PRIMARY_PINK_HEX

log = logging.getLogger("admeasy-desktop")

_enabled = True
_lock = threading.Lock()
_thread: threading.Thread | None = None
_ready = threading.Event()
_hwnds: list[int] = []
_active = False
_pulse = False
_t0 = time.monotonic()

# BGR for GDI
def _hex_bgr(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


_PINK_BGR = _hex_bgr(PRIMARY_PINK_HEX)


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = on
    if not on:
        set_active(False, pulse=False)


def is_available() -> bool:
    return sys.platform == "win32"


def hide() -> None:
    set_active(False, pulse=False)


def _alpha() -> float:
    with _lock:
        pulse = _pulse
        active = _active
    if not active:
        return 0.0
    if not pulse:
        return EDGE_ALPHA_STATIC
    phase = (time.monotonic() - _t0) % PULSE_PERIOD_S
    t = (math.sin(2 * math.pi * phase / PULSE_PERIOD_S) + 1.0) / 2.0
    return EDGE_ALPHA_PULSE_MIN + t * (EDGE_ALPHA_PULSE_MAX - EDGE_ALPHA_PULSE_MIN)


def set_active(active: bool, *, pulse: bool = True) -> None:
    global _active, _pulse, _t0
    with _lock:
        _active = active and _enabled
        _pulse = pulse and _active
        if _active and pulse:
            _t0 = time.monotonic()
    ensure_started()


def _run_ui() -> None:
    global _hwnds
    try:
        import ctypes
        from ctypes import wintypes
        from . import ctypes_win as cw

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", cw.HINSTANCE),
                ("hIcon", cw.HICON),
                ("hCursor", cw.HCURSOR),
                ("hbrBackground", cw.HBRUSH),
                ("lpszMenuName", cw.LPCWSTR),
                ("lpszClassName", cw.LPCWSTR),
            ]

        monitors: list[tuple[int, int, int, int]] = []

        def _enum(hmon, hdc, lprect, _data):
            r = lprect.contents
            monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return 1

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
        )
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_enum), 0)
        if not monitors:
            monitors.append((0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)))

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == 0x000F:  # WM_PAINT
                ps = wintypes.PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                w = EDGE_WIDTH_PX
                alpha = _alpha()
                if alpha > 0:
                    # Approximate alpha on a single layered window via color key + solid bars.
                    a = max(0, min(255, int(alpha * 255)))
                    color = _PINK_BGR | (a << 24)
                    brush = gdi32.CreateSolidBrush(color & 0xFFFFFF)
                    gdi32.SelectObject(hdc, brush)
                    for (x, y, ww, hh) in (
                        (0, 0, rect.right, w),
                        (0, rect.bottom - w, rect.right, w),
                        (0, 0, w, rect.bottom),
                        (rect.right - w, 0, w, rect.bottom),
                    ):
                        gdi32.PatBlt(hdc, x, y, ww, hh, 0x00F00021)  # PATCOPY
                    gdi32.DeleteObject(brush)
                user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == 0x0010:
                user32.DestroyWindow(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        proc = WNDPROC(wnd_proc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = proc
        wc.lpszClassName = "AdmeasyEdgeOverlay"
        wc.hInstance = cw.module_handle()
        user32.RegisterClassW(ctypes.byref(wc))

        hwnds = []
        for left, top, width, height in monitors:
            hwnd = user32.CreateWindowExW(
                0x00080088,  # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST
                "AdmeasyEdgeOverlay",
                None,
                0x80000000,
                left,
                top,
                width,
                height,
                None,
                None,
                wc.hInstance,
                None,
            )
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x02)
            hwnds.append(hwnd)
        _hwnds = hwnds
        _ready.set()

        while True:
            with _lock:
                show = _active and _enabled
            for hwnd in hwnds:
                if show:
                    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
                    user32.ShowWindow(hwnd, 5)
                    user32.InvalidateRect(hwnd, None, True)
                else:
                    user32.ShowWindow(hwnd, 0)
            user32.MsgWaitForMultipleObjects(0, None, 0, 33, 0x04FF)
    except Exception as e:
        log.warning("windows agent edge overlay disabled: %s", e)
        _ready.set()


def ensure_started() -> None:
    global _thread
    if not _enabled or not is_available():
        return
    if _thread is None:
        _thread = threading.Thread(target=_run_ui, name="admeasy-edge-win", daemon=True)
        _thread.start()
    _ready.wait(timeout=3.0)
