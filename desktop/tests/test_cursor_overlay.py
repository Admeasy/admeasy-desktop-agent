import sys

from admeasy_desktop import cursor_overlay


def test_cursor_overlay_without_tkinter(monkeypatch):
    monkeypatch.setattr(cursor_overlay.sys, "platform", "linux")
    monkeypatch.setattr(cursor_overlay, "_tk_available", False)
    cursor_overlay.set_enabled(True)
    cursor_overlay.ensure_started()
    cursor_overlay.move_to(10, 20)
    assert cursor_overlay.is_available() is False


def test_macos_never_starts_tk_overlay(monkeypatch):
    monkeypatch.setattr(cursor_overlay.sys, "platform", "darwin")
    monkeypatch.setattr(cursor_overlay, "_darwin_skip_logged", False)
    monkeypatch.setattr(cursor_overlay, "_tk_available", True)
    monkeypatch.setattr(cursor_overlay, "_thread", None)
    cursor_overlay.set_enabled(True)
    cursor_overlay.ensure_started()
    assert cursor_overlay._thread is None
    assert cursor_overlay.is_available() is False
