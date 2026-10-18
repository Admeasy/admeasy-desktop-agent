from admeasy_desktop.tab_reuse import _entry, best_tab, parse_tabs

RAW = "1|1|https://mail.google.com/mail/u/0/\n1|2|https://claude.ai/new\n2|1|https://www.github.com/Admeasy\n"


def test_parse_and_pick_by_host():
    tabs = parse_tabs(RAW)
    assert len(tabs) == 3
    assert best_tab(tabs, "https://claude.ai") == (1, 2)
    assert best_tab(tabs, "claude.ai/new") == (1, 2)
    assert best_tab(tabs, "https://github.com/Admeasy") == (2, 1)  # www. ignored
    assert best_tab(tabs, "https://lovable.dev") is None


def test_path_preference():
    tabs = parse_tabs("1|1|https://x.com/home\n1|2|https://x.com/compose/post\n")
    assert best_tab(tabs, "https://x.com/compose") == (1, 2)
    assert best_tab(tabs, "https://x.com/") == (1, 1)


def test_scripts_come_from_json_for_comet_and_safari():
    e, scripts = _entry("Comet")
    assert e["app_name"] == "Comet" and "active tab index" in scripts["activate"]
    assert "current tab" in _entry("Safari")[1]["activate"]
    assert _entry("Firefox") is None
