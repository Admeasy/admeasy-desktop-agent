"""Pink screen-edge frame while the agent is actively using the computer.

macOS: per-display AppKit windows at screen-saver level, click-through.
Windows: layered topmost HWNDs per monitor.
Linux: optional Tk fullscreen frame on the primary display (dev / source runs).
"""
from __future__ import annotations

import logging
import math
import queue
import sys
import threading
import time

from .brand import EDGE_ALPHA_PULSE_MAX, EDGE_ALPHA_PULSE_MIN, EDGE_ALPHA_STATIC, EDGE_WIDTH_PX, PULSE_PERIOD_S, PRIMARY_PINK_HEX

log = logging.getLogger("admeasy-desktop")

if sys.platform == "darwin":
    from . import agent_edge_overlay_mac as _impl

    set_enabled = _impl.set_enabled
    is_available = _impl.is_available
    ensure_started = _impl.ensure_started
    set_active = _impl.set_active
    hide = _impl.hide

elif sys.platform == "win32":
    from . import agent_edge_overlay_win as _impl

    set_enabled = _impl.set_enabled
    is_available = _impl.is_available
    ensure_started = _impl.ensure_started
    set_active = _impl.set_active
    hide = _impl.hide

else:
    _enabled = True
    _thread: threading.Thread | None = None
    _cmds: queue.Queue | None = None
    _tk_available: bool | None = None
    _state = {"active": False, "pulse": False, "t0": time.monotonic()}

    def set_enabled(on: bool) -> None:
        global _enabled
        _enabled = on
        if not on:
            set_active(False, pulse=False)

    def _probe_tk() -> bool:
        global _tk_available
        if _tk_available is not None:
            return _tk_available
        try:
            import importlib

            importlib.import_module("_tkinter")
            _tk_available = True
        except Exception:
            _tk_available = False
        return _tk_available

    def is_available() -> bool:
        return _probe_tk()

    def _alpha() -> float:
        if not _state["active"]:
            return 0.0
        if not _state["pulse"]:
            return EDGE_ALPHA_STATIC
        phase = (time.monotonic() - _state["t0"]) % PULSE_PERIOD_S
        t = (math.sin(2 * math.pi * phase / PULSE_PERIOD_S) + 1.0) / 2.0
        return EDGE_ALPHA_PULSE_MIN + t * (EDGE_ALPHA_PULSE_MAX - EDGE_ALPHA_PULSE_MIN)

    def _run_ui() -> None:
        global _tk_available
        try:
            import tkinter as tk
        except Exception as e:
            _tk_available = False
            log.warning("agent edge overlay disabled: %s", e)
            return
        try:
            root = tk.Tk()
            root.withdraw()
            win = tk.Toplevel(root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            win.geometry(f"{sw}x{sh}+0+0")
            try:
                win.attributes("-transparentcolor", "#010101")
            except tk.TclError:
                pass
            win.configure(bg="#010101")
            canvas = tk.Canvas(win, width=sw, height=sh, highlightthickness=0, bg="#010101", bd=0)
            canvas.pack()
            w = EDGE_WIDTH_PX

            def redraw():
                canvas.delete("all")
                if not _state["active"]:
                    win.withdraw()
                    root.after(33, redraw)
                    return
                win.deiconify()
                a = _alpha()
                if a <= 0:
                    root.after(33, redraw)
                    return
                # Tk has no per-primitive alpha; use stipple for a soft pink frame.
                color = PRIMARY_PINK_HEX
                stipple = "gray50" if a < 0.2 else "gray25"
                for coords in [
                    (0, 0, sw, w),
                    (0, sh - w, sw, sh),
                    (0, 0, w, sh),
                    (sw - w, 0, sw, sh),
                ]:
                    canvas.create_rectangle(*coords, fill=color, outline="", stipple=stipple)
                root.after(33, redraw)

            def pump():
                try:
                    while True:
                        cmd = _cmds.get_nowait()
                        if cmd[0] == "active":
                            _state["active"] = cmd[1] and _enabled
                            _state["pulse"] = cmd[2] and _state["active"]
                            if _state["active"] and _state["pulse"]:
                                _state["t0"] = time.monotonic()
                        elif cmd[0] == "stop":
                            root.quit()
                            return
                except queue.Empty:
                    pass
                root.after(16, pump)

            redraw()
            pump()
            root.mainloop()
        except Exception as e:
            _tk_available = False
            log.warning("agent edge overlay stopped: %s", e)

    def ensure_started() -> None:
        global _thread, _cmds
        if not _enabled or _thread is not None:
            return
        if not is_available():
            return
        _cmds = queue.Queue()
        _thread = threading.Thread(target=_run_ui, name="admeasy-edge", daemon=True)
        _thread.start()

    def set_active(active: bool, *, pulse: bool = True) -> None:
        if not _enabled:
            active = False
        ensure_started()
        if _cmds is None:
            return
        _cmds.put(("active", active, pulse))

    def hide() -> None:
        set_active(False, pulse=False)
