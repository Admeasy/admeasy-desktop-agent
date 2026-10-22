"""Full-screen pink edge frame on macOS (click-through, one window per display)."""
from __future__ import annotations

import logging
import math
import sys
import threading
import time

from .brand import EDGE_ALPHA_PULSE_MAX, EDGE_ALPHA_PULSE_MIN, EDGE_ALPHA_STATIC, EDGE_WIDTH_PX, PULSE_PERIOD_S, PRIMARY_PINK_RGB

log = logging.getLogger("admeasy-desktop")

_enabled = True
_lock = threading.Lock()
_ui_started = False
_windows: list = []
_cocoa_ok: bool | None = None
_active = False
_pulse = False
_t0 = time.monotonic()


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = on
    if not on:
        set_active(False, pulse=False)


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
        log.warning("mac agent edge overlay: %s", e)


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


def hide() -> None:
    set_active(False, pulse=False)


def set_active(active: bool, *, pulse: bool = True) -> None:
    global _active, _pulse, _t0
    with _lock:
        _active = active and _enabled
        _pulse = pulse and _active
        if _active and pulse:
            _t0 = time.monotonic()

    def _apply():
        if not is_available():
            return
        ensure_started()
        _sync_visibility()

    _on_main(_apply)


def _sync_visibility() -> None:
    with _lock:
        show = _active and _enabled
    for win in _windows:
        if show:
            win.orderFrontRegardless()
        else:
            win.orderOut_(None)


def _create_ui() -> None:
    global _ui_started, _windows
    if _ui_started or not _enabled:
        return
    try:
        from AppKit import (
            NSBackingStoreBuffered,
            NSBezierPath,
            NSColor,
            NSMakeRect,
            NSScreen,
            NSScreenSaverWindowLevel,
            NSTimer,
            NSView,
            NSWindow,
            NSWindowCollectionBehaviorCanJoinAllSpaces,
            NSWindowCollectionBehaviorFullScreenAuxiliary,
            NSWindowCollectionBehaviorIgnoresCycle,
            NSWindowCollectionBehaviorStationary,
            NSWindowStyleMaskBorderless,
        )

        r, g, b = PRIMARY_PINK_RGB

        class EdgeView(NSView):  # type: ignore[misc, valid-type]
            def isOpaque(self):
                return False

            def drawRect_(self, rect):
                NSColor.clearColor().set()
                NSBezierPath.fillRect_(rect)
                alpha = _alpha()
                if alpha <= 0:
                    return
                bounds = self.bounds()
                w = float(EDGE_WIDTH_PX)
                pink = NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)
                pink.set()
                # Four edge bars (frame only, transparent center).
                for frame in (
                    NSMakeRect(0, bounds.size.height - w, bounds.size.width, w),
                    NSMakeRect(0, 0, bounds.size.width, w),
                    NSMakeRect(0, 0, w, bounds.size.height),
                    NSMakeRect(bounds.size.width - w, 0, w, bounds.size.height),
                ):
                    NSBezierPath.fillRect_(frame)

        wins = []
        for screen in NSScreen.screens():
            frame = screen.frame()
            win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                frame,
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False,
            )
            win.setLevel_(NSScreenSaverWindowLevel)
            win.setOpaque_(False)
            win.setBackgroundColor_(NSColor.clearColor())
            win.setIgnoresMouseEvents_(True)
            win.setHasShadow_(False)
            behavior = (
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
                | NSWindowCollectionBehaviorIgnoresCycle
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            win.setCollectionBehavior_(behavior)
            view = EdgeView.alloc().initWithFrame_(NSMakeRect(0, 0, frame.size.width, frame.size.height))
            win.setContentView_(view)
            wins.append(win)

        def tick(_timer):
            with _lock:
                show = _active and _enabled
            if not show:
                for win in wins:
                    win.orderOut_(None)
                return
            for win in wins:
                win.orderFrontRegardless()
                win.contentView().setNeedsDisplay_(True)

        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1.0 / 30.0, True, tick)

        _windows = wins
        _ui_started = True
        _sync_visibility()
    except Exception as e:
        log.warning("mac agent edge overlay disabled: %s", e)


def ensure_started() -> None:
    if not _enabled or not is_available():
        return
    _on_main(_create_ui)
