"""Visible pink agent cursor during CUA (screen) actions."""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

log = logging.getLogger("admeasy-desktop")

_enabled = True
_thread: threading.Thread | None = None
_cmds: queue.Queue | None = None
_tk_available: bool | None = None


@dataclass
class _State:
    x: int = 100
    y: int = 100
    flash: bool = False


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = on


def is_available() -> bool:
    """True when Tk can be loaded (optional pink overlay)."""
    return _probe_tk()


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


def _run_ui() -> None:
    global _tk_available
    try:
        import tkinter as tk
    except Exception as e:
        _tk_available = False
        log.warning("agent cursor overlay disabled: %s", e)
        return

    try:
        root = tk.Tk()
        root.withdraw()
        size = 28
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.85)
        except tk.TclError:
            pass
        win.configure(bg="#010101")
        try:
            win.attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass
        canvas = tk.Canvas(win, width=size, height=size, highlightthickness=0, bg="#010101", bd=0)
        canvas.pack()
        canvas.create_oval(2, 2, size - 2, size - 2, outline="#ff2d95", width=3, fill="#ff2d9544")
        canvas.create_oval(size // 2 - 3, size // 2 - 3, size // 2 + 3, size // 2 + 3, fill="#ff2d95", outline="")
        state = _State()

        def tick():
            try:
                while True:
                    cmd = _cmds.get_nowait()
                    if cmd[0] == "move":
                        state.x, state.y = cmd[1], cmd[2]
                    elif cmd[0] == "flash":
                        state.flash = True
                    elif cmd[0] == "stop":
                        root.quit()
                        return
            except queue.Empty:
                pass
            win.geometry(f"+{state.x - size // 2}+{state.y - size // 2}")
            if state.flash:
                canvas.itemconfig(1, outline="#ffffff", width=4)
                state.flash = False
            else:
                canvas.itemconfig(1, outline="#ff2d95", width=3)
            root.after(16, tick)

        tick()
        root.mainloop()
    except Exception as e:
        _tk_available = False
        log.warning("agent cursor overlay stopped: %s", e)


def ensure_started() -> None:
    global _thread, _cmds
    if not _enabled or _thread is not None:
        return
    if not _probe_tk():
        log.debug("skip cursor overlay (no _tkinter; brew install python-tk or ADMEASY_SHOW_AGENT_CURSOR=0)")
        return
    _cmds = queue.Queue()
    _thread = threading.Thread(target=_run_ui, name="admeasy-cursor", daemon=True)
    _thread.start()


def move_to(x: int, y: int) -> None:
    if not _enabled:
        return
    ensure_started()
    if _cmds is None:
        return
    _cmds.put(("move", int(x), int(y)))


def click_flash() -> None:
    if not _enabled:
        return
    ensure_started()
    if _cmds is None:
        return
    _cmds.put(("flash",))


def pointer_at(x: int, y: int, flash: bool = False) -> None:
    """Show agent cursor without moving the OS pointer (preview / AX paths)."""
    move_to(x, y)
    if flash:
        click_flash()
