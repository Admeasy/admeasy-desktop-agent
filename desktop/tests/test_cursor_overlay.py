import sys

from admeasy_desktop import cursor_overlay


def test_cursor_overlay_without_tkinter(monkeypatch):
    monkeypatch.setattr(cursor_overlay.sys, "platform", "linux")
    if hasattr(cursor_overlay, "_tk_available"):
        monkeypatch.setattr(cursor_overlay, "_tk_available", False)
    cursor_overlay.set_enabled(True)
    cursor_overlay.ensure_started()
    cursor_overlay.move_to(10, 20)
    assert cursor_overlay.is_available() is False


def test_macos_does_not_start_tk_thread(monkeypatch):
    monkeypatch.setattr(cursor_overlay.sys, "platform", "darwin")
    monkeypatch.setattr(cursor_overlay, "_thread", None)
    cursor_overlay.set_enabled(True)
    cursor_overlay.ensure_started()
    assert cursor_overlay._thread is None


def test_macos_overlay_available_when_cocoa(monkeypatch):
    from admeasy_desktop import cursor_overlay_mac

    monkeypatch.setattr(cursor_overlay_mac.sys, "platform", "darwin")
    monkeypatch.setattr(cursor_overlay_mac, "_cocoa_ok", True)
    assert cursor_overlay_mac.is_available() is True
