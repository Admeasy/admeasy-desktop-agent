from admeasy_desktop.delivery_check import evaluate_delivery, responsible_app, tcc_advice


def test_responsible_app_is_the_terminal_when_run_from_source():
    ident = {"executable": "/opt/homebrew/bin/python3", "bundle_path": "/opt/homebrew/Frameworks/Python.app",
             "parent": "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"}
    assert responsible_app(ident) == "Terminal"
    assert responsible_app({"bundle_path": "/Applications/Admeasy.app"}) == "Admeasy.app"


def test_advice_names_the_app_and_the_restart():
    tips = tcc_advice({"parent": "/Applications/iTerm.app/Contents/MacOS/iTerm2", "ax_trusted": False, "screen_capture": False})
    assert len(tips) == 2 and all("iTerm" in t and "reopen" in t for t in tips)
    assert tcc_advice({"parent": "Terminal", "ax_trusted": True, "screen_capture": True}) == []


def test_delivery_requires_the_marker_to_arrive():
    assert evaluate_delivery("", "hello admeasyab12", "admeasyab12", "TextEdit")[0]
    ok, why = evaluate_delivery("", "", "admeasyab12", "Finder")
    assert not ok and "click" in why
    ok, why = evaluate_delivery("", "", "admeasyab12", "TextEdit")
    assert not ok and "keys" in why
    assert not evaluate_delivery("", "ERR:denied", "m", "TextEdit")[0]
