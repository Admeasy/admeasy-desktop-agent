"""Windows ctypes bindings for agent overlays (no UI thread required)."""
from __future__ import annotations

import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_ctypes_win_module_handle():
    from admeasy_desktop import ctypes_win as cw

    h = cw.module_handle()
    assert h


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_cursor_overlay_win_bindings():
    from ctypes import wintypes

    from admeasy_desktop import ctypes_win as cw
    from admeasy_desktop import cursor_overlay_win as ov

    assert ov.is_available()
    _ = wintypes.HWND
    assert cw.module_handle()
    assert ov._enabled is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_agent_edge_overlay_win_bindings():
    from ctypes import wintypes

    from admeasy_desktop import agent_edge_overlay_win as ov
    from admeasy_desktop import ctypes_win as cw

    assert ov.is_available()
    _ = wintypes.RECT
    assert cw.module_handle()
