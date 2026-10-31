"""Startup checks for the loopback HTML UI."""
from __future__ import annotations

import urllib.request

from admeasy_desktop.__main__ import _UI_READY_READ_BYTES, _wait_for_html_ui
from admeasy_desktop.config import Settings
from admeasy_desktop.ui.paths import ui_file
from admeasy_desktop.ui.server import UiState, serve


def test_index_app_marker_beyond_legacy_512_byte_probe():
    html = ui_file("index.html").read_text(encoding="utf-8")
    marker = 'id="app"'
    assert marker in html
    assert html.index(marker) >= 512, "regression guard: head assets must fit in _UI_READY_READ_BYTES"
    assert html.index(marker) < _UI_READY_READ_BYTES


def test_wait_for_html_ui_accepts_served_index():
    ui = UiState(Settings())
    srv, port = serve(ui)
    try:
        _wait_for_html_ui(f"http://127.0.0.1:{port}/")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as res:
            body = res.read(_UI_READY_READ_BYTES).decode()
            assert 'id="app"' in body
    finally:
        srv.shutdown()
