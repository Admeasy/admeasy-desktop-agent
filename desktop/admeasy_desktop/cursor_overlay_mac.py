"""Pink agent cursor on macOS via AppKit (main-thread safe; no Tk on a worker thread)."""
from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass

log = logging.getLogger("admeasy-desktop")

_enabled = True
_lock = threading.Lock()
_ui_started = False
_window = None
_cocoa_ok: bool | None = None

SIZE = 28


@dataclass
class _State:
    x: int = 100
    y: int = 100
    flash_frames: int = 0


_state = _State()


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = on


def _probe_cocoa() -> bool:
    global _cocoa_ok
    if _cocoa_ok is not None:
        return _cocoa_ok
    if sys.platform != "darwin":
        _cocoa_ok = False
        return False
    try:
        import AppKit  # noqa: F401

        _cocoa_ok = True
    except Exception:
        _cocoa_ok = False
    return _cocoa_ok


def is_available() -> bool:
    return sys.platform == "darwin" and _probe_cocoa()


def _on_main(block) -> None:
    try:
        from Foundation import NSOperationQueue

        NSOperationQueue.mainQueue().addOperationWithBlock_(block)
    except Exception as e:
        log.warning("mac agent cursor overlay: %s", e)


def _create_ui() -> None:
    global _ui_started, _window
    if _ui_started or not _enabled:
        return
    try:
        from AppKit import (
            NSBackingStoreBuffered,
            NSBezierPath,
            NSColor,
            NSFloatingWindowLevel,
            NSMakeRect,
            NSTimer,
            NSView,
            NSWindow,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorIgnoresCycle,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskBorderless,
        )

        class CursorView(NSView):  # type: ignore[misc, valid-type]
            def isOpaque(self):
                return False

            def drawRect_(self, rect):
                NSColor.clearColor().set()
                NSBezierPath.fillRect_(rect)
                bounds = self.bounds()
                inset = 2.0
                oval = NSMakeRect(inset, inset, bounds.size.width - 2 * inset, bounds.size.height - 2 * inset)
                with _lock:
                    flash_on = _state.flash_frames > 0
                pink = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.18, 0.58, 1.0)
                outline = NSColor.whiteColor() if flash_on else pink
                fill = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.18, 0.58, 0.27)
                path = NSBezierPath.bezierPathWithOvalInRect_(oval)
                fill.set()
                path.fill()
                outline.set()
                path.setLineWidth_(4.0 if flash_on else 3.0)
                path.stroke()
                cx = bounds.size.width / 2.0
                cy = bounds.size.height / 2.0
                dot = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(cx - 3, cy - 3, 6, 6))
                pink.set()
                dot.fill()

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, SIZE, SIZE),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        win.setLevel_(NSFloatingWindowLevel)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setIgnoresMouseEvents_(True)
        win.setHasShadow_(False)
        behavior = (
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        win.setCollectionBehavior_(behavior)
        view = CursorView.alloc().initWithFrame_(NSMakeRect(0, 0, SIZE, SIZE))
        win.setContentView_(view)
        with _lock:
            x, y = _state.x, _state.y
        win.setFrameOrigin_((float(x - SIZE // 2), float(y - SIZE // 2)))
        win.orderFrontRegardless()

        def tick(_timer):
            with _lock:
                if _state.flash_frames > 0:
                    _state.flash_frames -= 1
                x, y = _state.x, _state.y
            win.setFrameOrigin_((float(x - SIZE // 2), float(y - SIZE // 2)))
            view.setNeedsDisplay_(True)

        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1.0 / 60.0, True, tick)

        _window = win
        _ui_started = True
    except Exception as e:
        log.warning("mac agent cursor overlay disabled: %s", e)


def ensure_started() -> None:
    if not _enabled or not is_available():
        return
    _on_main(_create_ui)


def move_to(x: int, y: int) -> None:
    if not _enabled or not is_available():
        return
    with _lock:
        _state.x, _state.y = int(x), int(y)
    ensure_started()


def click_flash() -> None:
    if not _enabled or not is_available():
        return
    with _lock:
        _state.flash_frames = 8
    ensure_started()


def pointer_at(x: int, y: int, flash: bool = False) -> None:
    move_to(x, y)
    if flash:
        click_flash()
