from admeasy_desktop import browser_cdp


def test_parse_cdp_from_process_list():
    ps = "  123  /Applications/Google Chrome --remote-debugging-port=9333"
    assert browser_cdp.parse_cdp_from_process_list(ps) == 9333


def test_relaunch_hint_shape():
    hint = browser_cdp.relaunch_hint()
    assert hint["mode"] == "relaunch_with_debug_port"
    assert "9222" in " ".join(hint["args"])


def test_detect_debug_port_empty(monkeypatch):
    monkeypatch.setattr(browser_cdp, "_read_json_url", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert browser_cdp.detect_debug_port() is None