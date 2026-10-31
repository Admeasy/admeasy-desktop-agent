"""Regression: sign-in page probe must tolerate a large <head> (fonts, manifest)."""
from __future__ import annotations

from admeasy_desktop.__main__ import _html_ui_ready


def test_html_probe_accepts_app_id_after_long_head():
    head = "<!doctype html><html><head>" + ("x" * 700) + "</head><body>"
    body = head + '<div id="app">starting</div></body></html>'
    assert _html_ui_ready(body, 200)


def test_html_probe_accepts_meta_marker():
    body = "<!doctype html><html><head><meta name=\"admeasy-ui-root\" content=\"1\"></head><body></body>"
    assert _html_ui_ready(body, 200)
