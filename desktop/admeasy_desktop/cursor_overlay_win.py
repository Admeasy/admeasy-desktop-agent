"""Pink agent cursor on Windows via layered topmost click-through HWND."""
from __future__ import annotations

import logging
import sys
import threading
import time

log = logging.getLogger("admeasy-desktop")

_enabled = True
_lock = threading.Lock()
_hwnd = None
_thread: threading.Thread | None = None
_ready = threading.Event()
SIZE = 28
IDLE_HIDE_S = 2.5

_state = {"x": 100, "y": 100, "flash": 0, "last_active": 0.0, "visible": False}


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = on
    if not on:
        hide()


def is_available() -> bool:
    return sys.platform == "win32"


def hide() -> None:
    if _hwnd:
        try:
            import ctypes

            ctypes.windll.user32.ShowWindow(_hwnd, 0)  # SW_HIDE
            with _lock:
                _state["visible"] = False
        except Exception:
            pass


def _run_ui() -> None:
    global _hwnd
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

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == 0x000F:  # WM_PAINT
                ps = wintypes.PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                with _lock:
                    flash = _state["flash"] > 0
                pen = gdi32.CreatePen(0, 3 if not flash else 4, 0x00952DFF)  # BGR pink
                brush = gdi32.CreateSolidBrush(0x44952DFF)
                gdi32.SelectObject(hdc, pen)
                gdi32.SelectObject(hdc, brush)
                gdi32.Ellipse(hdc, 2, 2, SIZE - 2, SIZE - 2)
                gdi32.DeleteObject(pen)
                gdi32.DeleteObject(brush)
                user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == 0x0010:  # WM_CLOSE
                user32.DestroyWindow(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        proc = WNDPROC(wnd_proc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = proc
        wc.lpszClassName = "AdmeasyCursorOverlay"
        wc.hInstance = cw.module_handle()
        if not user32.RegisterClassW(ctypes.byref(wc)):
            pass
        hwnd = user32.CreateWindowExW(
            0x00080088,  # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST
            "AdmeasyCursorOverlay",
            None,
            0x80000000,  # WS_POPUP
            0,
            0,
            SIZE,
            SIZE,
            None,
            None,
            wc.hInstance,
            None,
        )
        user32.SetLayeredWindowAttributes(hwnd, 0, 220, 0x02)  # LWA_ALPHA
        _hwnd = hwnd
        _ready.set()

        while _enabled:
            with _lock:
                x, y = _state["x"], _state["y"]
                flash = _state["flash"]
                idle = time.time() - _state["last_active"]
                visible = _state["visible"]
            if idle > IDLE_HIDE_S and flash <= 0:
                if visible:
                    user32.ShowWindow(hwnd, 0)
                    with _lock:
                        _state["visible"] = False
            else:
                user32.SetWindowPos(hwnd, -1, x - SIZE // 2, y - SIZE // 2, SIZE, SIZE, 0x0040)  # HWND_TOPMOST
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                user32.InvalidateRect(hwnd, None, True)
                with _lock:
                    _state["visible"] = True
                if flash > 0:
                    with _lock:
                        _state["flash"] -= 1
            user32.MsgWaitForMultipleObjects(0, None, 0, 16, 0x04FF)
    except Exception as e:
        log.warning("windows cursor overlay disabled: %s", e)
        _ready.set()


def ensure_started() -> None:
    global _thread
    if not _enabled or not is_available():
        return
    if _thread is None:
        _thread = threading.Thread(target=_run_ui, name="admeasy-cursor-win", daemon=True)
        _thread.start()
    _ready.wait(timeout=2.0)


def move_to(x: int, y: int) -> None:
    if not _enabled or not is_available():
        return
    with _lock:
        _state["x"], _state["y"] = int(x), int(y)
        _state["last_active"] = time.time()
    ensure_started()


def click_flash() -> None:
    if not _enabled or not is_available():
        return
    with _lock:
        _state["flash"] = 8
        _state["last_active"] = time.time()
    ensure_started()


def pointer_at(x: int, y: int, flash: bool = False) -> None:
    move_to(x, y)
    if flash:
        click_flash()
