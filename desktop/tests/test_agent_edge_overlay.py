import sys

from admeasy_desktop import agent_edge_overlay


def test_edge_overlay_facade_on_linux_without_tk(monkeypatch):
    if sys.platform in ("darwin", "win32"):
        return
    monkeypatch.setattr(agent_edge_overlay, "_tk_available", False)
    agent_edge_overlay.set_enabled(True)
    agent_edge_overlay.ensure_started()
    assert agent_edge_overlay.is_available() is False
