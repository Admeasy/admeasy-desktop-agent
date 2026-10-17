from admeasy_desktop import cursor_overlay


def test_cursor_overlay_without_tkinter(monkeypatch):
    monkeypatch.setattr(cursor_overlay, "_tk_available", False)
    cursor_overlay.set_enabled(True)
    cursor_overlay.ensure_started()
    cursor_overlay.move_to(10, 20)
    assert cursor_overlay.is_available() is False
